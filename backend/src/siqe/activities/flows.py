"""Activities for flows: claiming images, running each block, and keeping score.

Every step reads one working file and writes the next under ``tmp/flows/<run>/<item>/``, named
after the step's position in the flow, so a retried step overwrites its own output and never
another's. Outputs that leave the run (an export, a new Library image) are recorded on the
item first, which makes those steps safe to retry too.
"""

import asyncio
import hashlib
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text, update
from temporalio import activity
from temporalio.exceptions import ApplicationError

from siqe.activities.threaded import run_threaded
from siqe.ai.manifest import ModelSpec
from siqe.ai.registry import get_row, get_spec, require_installed
from siqe.assets.ingest import add_file
from siqe.assets.records import get_asset, megapixel_limit, publish_asset
from siqe.core.config import CPU_TASK_QUEUE, get_settings
from siqe.core.errors import AppError
from siqe.core.logging import get_logger
from siqe.db.base import utcnow
from siqe.db.models import (
    Album,
    AlbumAsset,
    AlbumKind,
    Asset,
    FlowRun,
    FlowRunItem,
    ItemState,
    JobState,
)
from siqe.db.session import session_scope
from siqe.flows import ops
from siqe.flows.catalog import NODES_BY_TYPE
from siqe.flows.records import get_run, outputs_root, publish_run, recount, slug
from siqe.imaging.export import ExportOptions, encode
from siqe.imaging.pipeline import resize_to
from siqe.jobs.progress import HeartbeatOnly
from siqe.jobs.records import apply_update
from siqe.library.rules import RuleSet, matches
from siqe.storage.store import StagedUpload, get_store

log = get_logger(__name__)


@dataclass
class StepCall:
    run_id: str
    item_id: str
    node_id: str
    node_type: str
    params: dict[str, Any]
    label: str
    src: str | None  # None: the original file
    width: int
    height: int
    key: str  # unique for this position in the flow; names the step's output file
    dry_run: bool = False


@dataclass
class ItemFinish:
    run_id: str
    item_id: str
    state: str
    error: dict[str, Any] | None = None


def _fail(code: str, message: str, fix: str | None = None) -> ApplicationError:
    return ApplicationError(message, {"code": code, "fix": fix}, type=code, non_retryable=True)


def _item_dir(run_id: str, item_id: str) -> Path:
    return get_settings().data_dir / "tmp" / "flows" / run_id / item_id


async def _asset_for(item_id: str) -> Asset:
    async with session_scope() as session:
        item = await session.get(FlowRunItem, uuid.UUID(item_id))
        if item is None or item.asset_id is None:
            raise _fail("flow.image_missing", "The image was removed from the Library during the run.")
        try:
            asset = await get_asset(session, item.asset_id)
        except AppError as exc:
            raise _fail(
                "flow.image_missing", "The image was removed from the Library during the run."
            ) from exc
        await session.refresh(asset, ["embedding"])
        session.expunge(asset)
        return asset


def _input(call: StepCall, asset: Asset) -> tuple[Path, int]:
    """The file a step reads, and the megapixel limit that applies to it."""
    if call.src is None:
        path = get_store().original(asset.sha256, asset.extension)
        limit = megapixel_limit(asset) or get_settings().max_input_megapixels
    else:
        path = Path(call.src)
        # Intermediate results were checked on the way in; an upscale may make them larger.
        limit = max(get_settings().max_input_megapixels, call.width * call.height // 1_000_000 + 1)
    if not path.is_file():
        raise _fail("flow.file_missing", "A working file for this image is missing; run the flow again.")
    return path, limit


async def _record(item_id: str, step: dict[str, Any], output: dict[str, Any] | None = None) -> None:
    async with session_scope() as session:
        item = (
            await session.execute(
                select(FlowRunItem).where(FlowRunItem.id == uuid.UUID(item_id)).with_for_update()
            )
        ).scalar_one()
        item.steps = [*(item.steps or []), step]
        if output is not None:
            item.outputs = [*(item.outputs or []), output]


async def _existing_output(item_id: str, node_id: str, key: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        item = await session.get(FlowRunItem, uuid.UUID(item_id))
        for out in (item.outputs if item else None) or []:
            if out.get("node") == node_id and out.get("key") == key:
                return dict(out)
    return None


def _step(call: StepCall, started: float, note: str = "") -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    return {
        "node": call.node_id,
        "key": call.key,
        "label": call.label,
        "ms": round((loop.time() - started) * 1000),
        "note": note,
    }


# ----------------------------------------------------------------------------- run


@activity.defn
async def flow_run_start(run_id: str) -> dict[str, Any]:
    async with session_scope() as session:
        run = await get_run(session, uuid.UUID(run_id), for_update=True)
        run.state = JobState.running
        run.started_at = run.started_at or utcnow()
        await recount(session, run)
        if run.job_id:
            await apply_update(session, run.job_id, state=JobState.running, message=f"0 of {run.total}")
        await publish_run(session, run)
        return {"kind": run.kind.value, "dry_run": run.dry_run, "document": run.document}


@activity.defn
async def flow_next_items(run_id: str, limit: int) -> list[str]:
    """Claim up to ``limit`` waiting images, in order. Claimed images are never handed out twice."""
    async with session_scope() as session:
        rows = await session.execute(
            text(
                """
                UPDATE flow_run_items SET state = 'running', started_at = now()
                WHERE id IN (
                    SELECT id FROM flow_run_items
                    WHERE run_id = :run AND state = 'pending'
                    ORDER BY position
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, position
                """
            ),
            {"run": uuid.UUID(run_id), "limit": limit},
        )
        return [str(r.id) for r in sorted(rows, key=lambda r: r.position)]


@activity.defn
async def flow_run_finish(run_id: str, cancelled: bool) -> dict[str, Any]:
    async with session_scope() as session:
        run = await get_run(session, uuid.UUID(run_id), for_update=True)
        await session.execute(
            update(FlowRunItem)
            .where(
                FlowRunItem.run_id == run.id, FlowRunItem.state.in_([ItemState.pending, ItemState.running])
            )
            .values(state=ItemState.skipped, finished_at=utcnow(), error={"message": "The run was stopped"})
        )
        await recount(session, run)
        run.state = (
            JobState.cancelled
            if cancelled
            else JobState.failed
            if run.total and run.failed == run.total
            else JobState.succeeded
        )
        run.finished_at = utcnow()
        parts = [f"{run.done} done"]
        if run.failed:
            parts.append(f"{run.failed} failed")
        if run.skipped:
            parts.append(f"{run.skipped} skipped")
        message = ", ".join(parts)
        summary = {"run_id": run_id, "done": run.done, "failed": run.failed, "skipped": run.skipped}
        if run.job_id:
            await apply_update(
                session,
                run.job_id,
                state=run.state,
                progress=1.0,
                message=message,
                result=summary,
                error={"code": "flow.all_failed", "message": message}
                if run.state == JobState.failed
                else None,
            )
        await publish_run(session, run)
    await asyncio.to_thread(shutil.rmtree, get_settings().data_dir / "tmp" / "flows" / run_id, True)
    return summary


# ---------------------------------------------------------------------------- item


@activity.defn
async def flow_item_start(run_id: str, item_id: str) -> dict[str, Any]:
    asset = await _asset_for(item_id)
    if asset.status.value != "ready":
        raise _fail("asset.not_ready", f"{asset.original_name} isn't ready (it is {asset.status.value}).")
    async with session_scope() as session:
        item = await session.get(FlowRunItem, uuid.UUID(item_id))
        if item is not None:
            item.state = ItemState.running
            item.started_at = item.started_at or utcnow()
            item.name = asset.original_name
            item.steps, item.outputs, item.error = [], [], None  # a retried item starts clean
    return {
        "asset_id": str(asset.id),
        "name": asset.original_name,
        "width": asset.width,
        "height": asset.height,
    }


@activity.defn
async def flow_item_finish(finish: ItemFinish) -> None:
    async with session_scope() as session:
        item = await session.get(FlowRunItem, uuid.UUID(finish.item_id))
        if item is None:
            return
        item.state = ItemState(finish.state)
        item.finished_at = utcnow()
        item.error = finish.error
        run = await get_run(session, uuid.UUID(finish.run_id), for_update=True)
        await recount(session, run)
        if run.job_id:
            finished = run.done + run.failed + run.skipped
            await apply_update(
                session,
                run.job_id,
                progress=finished / max(1, run.total),
                message=f"{finished} of {run.total}" + (f" · {run.failed} failed" if run.failed else ""),
            )
        await publish_run(session, run)
    await asyncio.to_thread(shutil.rmtree, _item_dir(finish.run_id, finish.item_id), True)


# ------------------------------------------------------------------------- decide


def _facts(asset: Asset, width: int, height: int) -> dict[str, Any]:
    folder = (asset.source or {}).get("path") if (asset.source or {}).get("kind") == "folder" else None
    return {
        "width": width,
        "height": height,
        "format": asset.format,
        "color": asset.color,
        "tags": [*(asset.tags or []), *(asset.auto_tags or [])],
        "sharpness": asset.sharpness,
        "has_gps": asset.has_gps,
        "ai_result": asset.parent_id is not None,
        "duplicate": asset.duplicate_group is not None,
        "taken_at": asset.taken_at,
        "created_at": asset.created_at,
        "name": asset.original_name,
        "folder": folder,
        "faces": asset.faces,
    }


@activity.defn
async def flow_condition(call: StepCall) -> dict[str, Any]:
    started = asyncio.get_running_loop().time()
    asset = await _asset_for(call.item_id)
    if call.node_type == "skip_duplicates":
        keeper = asset.duplicate_group is None or (asset.duplicate_rank or 0) == 0
        note = "" if keeper else "A better copy of this image is in the Library; skipped"
        await _record(call.item_id, _step(call, started, note))
        return {"port": "out" if keeper else None, "note": note}
    yes = matches(RuleSet.model_validate(call.params["rules"]), _facts(asset, call.width, call.height))
    port = "yes" if yes else "no"
    await _record(call.item_id, _step(call, started, port))
    return {"port": port, "note": ""}


# ------------------------------------------------------------------- edit and AI


@activity.defn
async def flow_edit(call: StepCall) -> dict[str, Any]:
    started = asyncio.get_running_loop().time()
    asset = await _asset_for(call.item_id)
    src, limit = _input(call, asset)
    out = _item_dir(call.run_id, call.item_id) / f"{call.key}.png"
    edits = dict(asset.edits or {}) if call.node_type == "studio_edits" else None
    try:
        width, height = await asyncio.to_thread(
            ops.run_step, call.node_type, call.params, src, out, edits=edits, max_megapixels=limit
        )
    except AppError as exc:
        raise _fail(exc.code, exc.detail, exc.fix) from exc
    await _record(call.item_id, _step(call, started, f"{width} × {height}"))
    return {"path": str(out), "width": width, "height": height}


TASK_FOR_NODE = {
    "upscale": "upscale",
    "denoise": "denoise",
    "deblur": "deblur",
    "colorize": "colorize",
    "remove_background": "background",
    "restore_faces": "face",
}


async def _model(call: StepCall) -> tuple[ModelSpec, dict[str, Any]]:
    try:
        spec = get_spec(call.params["model"])
    except AppError as exc:
        raise _fail(exc.code, exc.detail, exc.fix) from exc
    if spec.task != TASK_FOR_NODE[call.node_type]:
        raise _fail("flow.wrong_model", f"{spec.name} can't be used for {call.label}.", "Pick another model.")
    async with session_scope() as session:
        try:
            await require_installed(session, spec)
        except AppError as exc:
            raise _fail(exc.code, exc.detail, exc.fix) from exc
        row = await get_row(session, spec.id)
        return spec, dict(row.calibration or {}) if row else {}


async def _ai(call: StepCall) -> dict[str, Any]:
    from siqe.activities.ai import run_cpu_file, run_model_file
    from siqe.ai.manifest import CPU_ARCHS

    started = asyncio.get_running_loop().time()
    spec, calibrations = await _model(call)
    asset = await _asset_for(call.item_id)
    src, limit = _input(call, asset)
    folder = _item_dir(call.run_id, call.item_id)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{call.key}.png"
    if spec.arch in CPU_ARCHS:
        result = await run_cpu_file(spec, src, out, reporter=HeartbeatOnly(), limit=limit)
    else:
        result = await run_model_file(
            spec,
            src,
            out,
            folder / f"{call.key}.canvas",
            device_request="auto",
            restore_faces=bool(call.params.get("restore_faces")),
            reporter=HeartbeatOnly(),
            limit=limit,
            size=(call.width, call.height),
            calibrations=calibrations,
        )
    where = result.get("device_name") or "CPU"
    note = f"{result['width']} × {result['height']} · {spec.name} on {where}"
    if result.get("fallbacks"):
        note += f" (adjusted: {result['fallbacks'][-1]})"
    await _record(call.item_id, _step(call, started, note))
    return {"path": str(out), "width": result["width"], "height": result["height"]}


@activity.defn
async def flow_ai_gpu(call: StepCall) -> dict[str, Any]:
    return await _ai(call)


@activity.defn
async def flow_ai_cpu(call: StepCall) -> dict[str, Any]:
    return await _ai(call)


# ------------------------------------------------------------------------ outputs


def _file_name(pattern: str, *, original: str, flow: str, n: int, when: datetime) -> str:
    stem = Path(original).stem or "image"
    name = (
        (pattern or "{name}")
        .replace("{name}", stem)
        .replace("{flow}", slug(flow))
        .replace("{n}", str(n))
        .replace("{date}", when.strftime("%Y-%m-%d"))
    )
    cleaned = "".join(c for c in name if c not in '<>:"/\\|?*\0').strip(" .")
    return cleaned[:150] or stem


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise _fail("flow.too_many_files", "Too many files with the same name in the output folder.")


async def _export(call: StepCall, asset: Asset, run: FlowRun, position: int) -> dict[str, Any]:
    p = call.params
    options = ExportOptions.model_validate(
        {
            "format": p["format"],
            "quality": p["quality"],
            "max_side": p.get("max_side"),
            "target_kb": p.get("target_kb"),
            "strip_metadata": p["strip_metadata"],
        }
    )
    src, limit = _input(call, asset)
    root = outputs_root()
    run_dir = (root / run.output_dir).resolve()
    folder = (run_dir / (p.get("folder") or "").strip("/\\")).resolve()
    if run_dir not in folder.parents and folder != run_dir:
        raise _fail("flow.bad_folder", "The export subfolder must stay inside the run folder.")
    from siqe.imaging.formats import OUTPUT_FORMATS

    name = _file_name(
        p.get("name") or "{name}",
        original=asset.original_name,
        flow=run.flow_name,
        n=position,
        when=run.created_at,
    )
    target = _unique(folder / f"{name}{OUTPUT_FORMATS[options.format].extension}")
    tmp = get_settings().data_dir / "tmp"

    def work(state: Any) -> Any:
        folder.mkdir(parents=True, exist_ok=True)
        image = resize_to(ops.load(src, limit), options.max_side)
        return encode(image, options, target, tmp, progress=lambda f: state.update(f, "Encoding"))

    try:
        result = await run_threaded(work, HeartbeatOnly())  # type: ignore[arg-type]
    except AppError as exc:
        raise _fail(exc.code, exc.detail, exc.fix) from exc
    return {
        "kind": "export",
        "path": str(target.relative_to(root)),
        "width": result.width,
        "height": result.height,
        "size_bytes": result.size_bytes,
        "format": options.format,
    }


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


async def _save_to_library(call: StepCall, asset: Asset, run: FlowRun) -> dict[str, Any]:
    from siqe.workflows.assets import IngestAssetWorkflow

    src, _ = _input(call, asset)
    staging = get_settings().data_dir / "tmp" / f"flow-{uuid.uuid4()}.png"
    if src.suffix.lower() == ".png":
        await asyncio.to_thread(shutil.copyfile, src, staging)
    else:  # the original itself: store a PNG so the result is a real copy
        await asyncio.to_thread(lambda: ops.save(ops.load(src), staging))
    sha, size = await asyncio.to_thread(_hash, staging)
    name = f"{Path(asset.original_name).stem}{call.params.get('suffix') or ''}.png"
    async with session_scope() as session:
        added = await add_file(
            session, StagedUpload(staging, sha, size), name, source={"kind": "flow", "run": call.run_id}
        )
        new = added.asset
        if not added.duplicate:
            new.parent_id = asset.id
            new.derivation = {"kind": "flow", "flow": run.flow_name, "run_id": call.run_id}
            new.tags = list(asset.tags or [])
            await publish_asset(session, new)
        job_id = added.job.id if added.job else None
        new_id = new.id
    if job_id is not None:
        await activity.client().start_workflow(
            IngestAssetWorkflow.run,
            args=[str(job_id), str(new_id)],
            id=f"job-{job_id}",
            task_queue=CPU_TASK_QUEUE,
        )
    return {"kind": "asset", "asset_id": str(new_id), "name": name, "duplicate": added.duplicate}


@activity.defn
async def flow_output(call: StepCall) -> dict[str, Any]:
    started = asyncio.get_running_loop().time()
    previous = await _existing_output(call.item_id, call.node_id, call.key)
    if previous is not None:  # a retry after the output was already made
        return {"output": previous}
    asset = await _asset_for(call.item_id)
    async with session_scope() as session:
        run = await get_run(session, uuid.UUID(call.run_id))
        session.expunge(run)
        item = await session.get(FlowRunItem, uuid.UUID(call.item_id))
        position = (item.position + 1) if item else 1
    spec = NODES_BY_TYPE[call.node_type]
    output: dict[str, Any]
    if call.node_type == "export":
        output = await _export(call, asset, run, position)
        note = f"{output['path']} · {output['size_bytes'] / 1024:,.0f} KB"
    elif call.dry_run and spec.writes_library:
        output = {"kind": "dry_run", "would": call.label}
        note = f"Dry run: would {call.label.lower()}"
    elif call.node_type == "save_to_library":
        output = await _save_to_library(call, asset, run)
        note = f"Added {output['name']}"
    elif call.node_type == "tag":
        tags = list(call.params["tags"])
        async with session_scope() as session:
            row = await get_asset(session, asset.id, for_update=True)
            row.tags = [*(row.tags or []), *(t for t in tags if t not in (row.tags or []))][:30]
            await publish_asset(session, row)
        output = {"kind": "tag", "tags": tags}
        note = ", ".join(tags)
    elif call.node_type == "add_to_album":
        async with session_scope() as session:
            album = await session.get(Album, uuid.UUID(call.params["album"]))
            if album is None or album.kind != AlbumKind.manual:
                raise _fail(
                    "flow.album_missing", "The album this flow adds to is gone.", "Pick another album."
                )
            exists = await session.get(AlbumAsset, (album.id, asset.id))
            if exists is None:
                session.add(AlbumAsset(album_id=album.id, asset_id=asset.id))
            output = {"kind": "album", "album_id": str(album.id), "album": album.name}
            note = album.name
    elif call.node_type == "quarantine":
        async with session_scope() as session:
            row = await get_asset(session, asset.id, for_update=True)
            if row.quarantined_at is None:
                row.quarantined_at = utcnow()
                row.quarantine_reason = str(call.params.get("reason") or "Sorted out by a flow")[:200]
                row.duplicate_group = None
                row.duplicate_rank = None
                await publish_asset(session, row)
        output = {"kind": "quarantine"}
        note = "Moved to quarantine"
    else:
        raise _fail("flow.unknown_step", f"No output called {call.node_type}.")
    output = {"node": call.node_id, "key": call.key, **output}
    await _record(call.item_id, _step(call, started, note), output)
    return {"output": output}


# ------------------------------------------------------------------------ triggers


@activity.defn
async def flow_trigger(asset_ids: list[str]) -> int:
    """Hand newly imported, analysed images to the flows watching their folder."""
    from siqe.flows.start import trigger

    client = activity.client()
    started = 0
    for raw in asset_ids:
        async with session_scope() as session:
            asset = await session.get(Asset, uuid.UUID(raw))
            if asset is None or asset.quarantined_at is not None:
                continue
            started += await trigger(session, client, asset)
    return started
