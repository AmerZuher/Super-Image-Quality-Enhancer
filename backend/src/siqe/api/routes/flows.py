"""Flows: build pipelines from blocks, run them on images, and collect the results."""

import asyncio
import uuid
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from siqe.api.deps import SessionDep, SettingsDep, TemporalDep
from siqe.api.schemas import (
    FlowFileIO,
    FlowIn,
    FlowNodeTypeOut,
    FlowOut,
    FlowRunDetailOut,
    FlowRunIn,
    FlowRunItemOut,
    FlowRunOut,
    FlowUpdateIn,
    RecipeOut,
)
from siqe.core.config import Settings
from siqe.core.errors import AppError, NotFoundError
from siqe.db.base import utcnow
from siqe.db.models import Flow, FlowRun, FlowRunItem, JobState, RunKind
from siqe.flows.catalog import NODES_BY_TYPE, catalog
from siqe.flows.document import FlowDocument, check
from siqe.flows.recipes import RECIPES, RECIPES_BY_ID, validated
from siqe.flows.records import (
    flow_to_dict,
    get_flow,
    get_run,
    item_to_dict,
    outputs_root,
    publish_flow,
    publish_run,
    run_to_dict,
)
from siqe.flows.start import RUN_TIMEOUT, create_run, workflow_args
from siqe.jobs.start import start_workflow
from siqe.library.selection import select_images
from siqe.workflows.flows import FlowRunWorkflow

router = APIRouter(prefix="/flows", tags=["flows"])

DRY_RUN_IMAGES = 10


def _uuid(value: str | None, what: str = "image") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise NotFoundError(f"{what}.not_found", f"No {what} with id {value}.", title="Not found") from exc


async def _flow_out(session: AsyncSession, flow: Flow) -> FlowOut:
    doc, problems = check(FlowDocument.model_validate(flow.document or {}))
    last = (
        await session.execute(
            select(FlowRun).where(FlowRun.flow_id == flow.id).order_by(FlowRun.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    data = flow_to_dict(flow)
    data["document"] = flow.document or doc.model_dump()
    data["problems"] = [p.model_dump() for p in problems]
    data["ai"] = any((s := NODES_BY_TYPE.get(n.type)) is not None and s.ai for n in doc.nodes)
    data["last_run"] = (
        {
            "id": str(last.id),
            "state": last.state.value,
            "done": last.done,
            "failed": last.failed,
            "total": last.total,
            "created_at": last.created_at,
        }
        if last
        else None
    )
    return FlowOut.model_validate(data)


def _store(document: dict[str, Any]) -> dict[str, Any]:
    """Keep the document as drawn (problems and all) but with settings normalised where valid."""
    doc = FlowDocument.model_validate(document)
    checked, _ = check(doc)
    return checked.model_dump()


def _watch_folder(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.replace("\\", "/").strip().strip("/")
    if ".." in cleaned.split("/"):
        raise AppError("flow.bad_folder", "The watched folder must be inside the import folder.", status=422)
    return cleaned


# --------------------------------------------------------------------------- catalog


@router.get("/catalog", response_model=list[FlowNodeTypeOut], summary="Every block a flow can use")
async def flow_catalog() -> list[FlowNodeTypeOut]:
    return [FlowNodeTypeOut.model_validate(n) for n in catalog()]


@router.get("/recipes", response_model=list[RecipeOut], summary="Ready-made flows to start from")
async def flow_recipes() -> list[RecipeOut]:
    return [
        RecipeOut.model_validate(
            {"id": r.id, "name": r.name, "summary": r.summary, "ai": r.ai, "document": validated(r)}
        )
        for r in RECIPES
    ]


# ----------------------------------------------------------------------------- flows


@router.get("", response_model=list[FlowOut], summary="All flows, most recently changed first")
async def list_flows(session: SessionDep) -> list[FlowOut]:
    flows = (await session.execute(select(Flow).order_by(Flow.updated_at.desc()))).scalars().all()
    return [await _flow_out(session, f) for f in flows]


@router.post("", response_model=FlowOut, status_code=status.HTTP_201_CREATED, summary="New flow")
async def create_flow(body: FlowIn, session: SessionDep) -> FlowOut:
    if body.recipe:
        recipe = RECIPES_BY_ID.get(body.recipe)
        if recipe is None:
            raise NotFoundError("flow.recipe_not_found", f"No recipe called '{body.recipe}'.")
        document = validated(recipe)
    elif body.document is not None:
        document = _store(body.document.model_dump())
    else:
        document = {
            "version": 1,
            "nodes": [{"id": "in", "type": "input", "params": {}, "position": {"x": 0, "y": 80}}],
            "edges": [],
        }
    flow = Flow(name=body.name.strip(), description=body.description, document=document, recipe=body.recipe)
    session.add(flow)
    await publish_flow(session, flow)
    return await _flow_out(session, flow)


@router.get("/{flow_id}", response_model=FlowOut, summary="One flow, with anything stopping it from running")
async def one_flow(flow_id: uuid.UUID, session: SessionDep) -> FlowOut:
    return await _flow_out(session, await get_flow(session, flow_id))


@router.put("/{flow_id}", response_model=FlowOut, summary="Change a flow")
async def update_flow(flow_id: uuid.UUID, body: FlowUpdateIn, session: SessionDep) -> FlowOut:
    flow = await get_flow(session, flow_id, for_update=True)
    if body.name is not None:
        flow.name = body.name.strip()
    if body.description is not None:
        flow.description = body.description
    if body.document is not None:
        flow.document = _store(body.document.model_dump())
    if body.watch_folder is not None:
        flow.watch_folder = _watch_folder(body.watch_folder)
    if body.watch_enabled is not None:
        if body.watch_enabled:
            _, problems = check(FlowDocument.model_validate(flow.document or {}))
            if problems:
                raise AppError(
                    "flow.invalid",
                    f"A flow can only watch a folder once it can run: {problems[0].message}.",
                    status=422,
                    fix="Fix the blocks marked in red first.",
                )
        flow.watch_enabled = body.watch_enabled
    flow.updated_at = utcnow()
    await publish_flow(session, flow)
    return await _flow_out(session, flow)


@router.delete(
    "/{flow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a flow (its past runs and exported files stay)",
)
async def delete_flow(flow_id: uuid.UUID, session: SessionDep) -> Response:
    flow = await get_flow(session, flow_id)
    await session.delete(flow)
    await publish_flow(session, flow)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{flow_id}/duplicate", response_model=FlowOut, status_code=status.HTTP_201_CREATED, summary="Copy a flow"
)
async def duplicate_flow(flow_id: uuid.UUID, session: SessionDep) -> FlowOut:
    flow = await get_flow(session, flow_id)
    copy = Flow(
        name=f"{flow.name} (copy)"[:120],
        description=flow.description,
        document=flow.document,
        recipe=flow.recipe,
    )
    session.add(copy)
    await publish_flow(session, copy)
    return await _flow_out(session, copy)


@router.get("/{flow_id}/file", response_model=FlowFileIO, summary="The flow as a .flow.json file")
async def flow_file(flow_id: uuid.UUID, session: SessionDep, response: Response) -> FlowFileIO:
    flow = await get_flow(session, flow_id)
    safe = "".join(c for c in flow.name if c.isalnum() or c in " -_").strip() or "flow"
    response.headers["Content-Disposition"] = f'attachment; filename="{safe}.flow.json"'
    return FlowFileIO.model_validate(
        {"name": flow.name, "description": flow.description, "document": flow.document}
    )


@router.post(
    "/import",
    response_model=FlowOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a flow from a .flow.json file",
)
async def import_flow(body: FlowFileIO, session: SessionDep) -> FlowOut:
    flow = Flow(
        name=body.name.strip(), description=body.description, document=_store(body.document.model_dump())
    )
    session.add(flow)
    await publish_flow(session, flow)
    return await _flow_out(session, flow)


# ------------------------------------------------------------------------------ runs


async def _images(session: AsyncSession, body: FlowRunIn) -> tuple[list[uuid.UUID], dict[str, Any]]:
    source = body.source
    return await select_images(
        session,
        source.kind,
        asset_ids=source.asset_ids,
        album_id=source.album_id,
        rules=source.rules,
        empty_code="flow.no_images",
    )


async def _start(
    session: AsyncSession,
    temporal: Any,
    flow: Flow,
    ids: list[uuid.UUID],
    *,
    kind: RunKind,
    dry_run: bool,
    source: dict[str, Any],
) -> FlowRun:
    run, job = await create_run(session, flow, ids, kind=kind, dry_run=dry_run, source=source)
    try:
        await start_workflow(
            session, temporal, job, FlowRunWorkflow.run, workflow_args(run), run_timeout=RUN_TIMEOUT
        )
    except AppError:
        run.state = JobState.failed
        run.finished_at = utcnow()
        await publish_run(session, run)
        await session.commit()
        raise
    return run


@router.post(
    "/{flow_id}/runs", response_model=FlowRunOut, status_code=status.HTTP_201_CREATED, summary="Run a flow"
)
async def run_flow(
    flow_id: uuid.UUID, body: FlowRunIn, session: SessionDep, temporal: TemporalDep
) -> FlowRunOut:
    flow = await get_flow(session, flow_id)
    ids, described = await _images(session, body)
    limit = body.limit or (DRY_RUN_IMAGES if body.dry_run else None)
    if limit:
        ids = ids[:limit]
    run = await _start(
        session, temporal, flow, ids, kind=RunKind.manual, dry_run=body.dry_run, source=described
    )
    return FlowRunOut.model_validate(run_to_dict(run))


@router.get("/runs/recent", response_model=list[FlowRunOut], summary="Recent runs of every flow")
async def recent_runs(
    session: SessionDep,
    flow_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
) -> list[FlowRunOut]:
    stmt = select(FlowRun).order_by(FlowRun.created_at.desc()).limit(limit)
    if flow_id is not None:
        stmt = stmt.where(FlowRun.flow_id == flow_id)
    return [FlowRunOut.model_validate(run_to_dict(r)) for r in (await session.execute(stmt)).scalars()]


@router.get(
    "/runs/{run_id}", response_model=FlowRunDetailOut, summary="A run and what happened to each image"
)
async def one_run(
    run_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> FlowRunDetailOut:
    run = await get_run(session, run_id)
    items = (
        await session.execute(
            select(FlowRunItem)
            .where(FlowRunItem.run_id == run.id)
            .order_by(FlowRunItem.position)
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    return FlowRunDetailOut(
        run=FlowRunOut.model_validate(run_to_dict(run)),
        items=[FlowRunItemOut.model_validate(item_to_dict(i)) for i in items],
        output_folder=_host_folder(settings, run),
    )


def _host_folder(settings: Settings, run: FlowRun) -> str:
    root = outputs_root()
    base = settings.output_host_path if root == settings.output_dir else "the data volume (outputs)"
    return f"{base.rstrip('/')}/{run.output_dir}"


async def _exports(session: AsyncSession, run: FlowRun) -> list[Path]:
    root = outputs_root().resolve()
    files: list[Path] = []
    rows = await session.execute(select(FlowRunItem.outputs).where(FlowRunItem.run_id == run.id))
    lists: list[list[dict[str, Any]] | None] = list(rows.scalars().all())
    for entries in lists:
        for out in entries or []:
            if out.get("kind") != "export":
                continue
            path = (root / str(out["path"])).resolve()
            if root in path.parents and path.is_file():
                files.append(path)
    return files


def _zip(files: list[Path], base: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for path in files:
            zf.write(path, arcname=str(path.relative_to(base)))


@router.get(
    "/runs/{run_id}/download", response_class=FileResponse, summary="Every file a run exported, as a zip"
)
async def download_run(run_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> FileResponse:
    run = await get_run(session, run_id)
    files = await _exports(session, run)
    if not files:
        raise AppError("flow.no_files", "This run hasn't exported any files.", status=404, title="No files")
    base = (outputs_root() / run.output_dir).resolve()
    tmp = settings.data_dir / "tmp" / f"run-{uuid.uuid4()}.zip"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_zip, files, base, tmp)
    name = f"{run.output_dir.replace('/', ' ')}.zip"
    return FileResponse(
        tmp,
        filename=name,
        media_type="application/zip",
        background=BackgroundTask(tmp.unlink, missing_ok=True),
    )


@router.get("/runs/{run_id}/files/{path:path}", response_class=FileResponse, summary="One exported file")
async def run_file(run_id: uuid.UUID, path: str, session: SessionDep) -> FileResponse:
    run = await get_run(session, run_id)
    root = outputs_root().resolve()
    target = (root / path).resolve()
    if target not in await _exports(session, run):
        raise AppError("media.not_found", "No such file in this run.", status=404, title="Not found")
    return FileResponse(target, filename=target.name)
