"""Forge: design a model, build a dataset, train it, and publish it to AI Lab."""

import asyncio
import shutil
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.api.deps import SessionDep, TemporalDep
from siqe.api.schemas import (
    ForgeBlockTypeOut,
    ForgeCheckIn,
    ForgeCodeOut,
    ForgeDatasetIn,
    ForgeDatasetOut,
    ForgeDegradationIn,
    ForgeExportOut,
    ForgeMetricOut,
    ForgeProjectIn,
    ForgeProjectOut,
    ForgeProjectUpdateIn,
    ForgePublishIn,
    ForgePublishOut,
    ForgeRunDetailOut,
    ForgeRunIn,
    ForgeRunOut,
    ForgeTemplateOut,
    JobOut,
)
from siqe.core.errors import AppError, NotFoundError
from siqe.db.base import utcnow
from siqe.db.models import ForgeDataset, ForgeMetric, ForgeProject, ForgeRun, JobState
from siqe.events.bus import publish
from siqe.forge import datasets
from siqe.forge.catalog import catalog
from siqe.forge.codegen import class_name, generate
from siqe.forge.degrade import Degradation
from siqe.forge.graph import ForgeAnalysis, ForgeGraph, analyze
from siqe.forge.records import (
    DATASET_EVENT,
    RUN_EVENT,
    dataset_to_dict,
    get_dataset,
    get_project,
    get_run,
    publish_dataset,
    publish_project,
    publish_run,
    run_to_dict,
)
from siqe.forge.templates import EMPTY, TEMPLATES, TEMPLATES_BY_ID
from siqe.forge.training import TrainSettings, best_weights, onnx_path, run_dir, sample_path
from siqe.jobs.records import job_to_dict
from siqe.jobs.start import create_job, start_workflow
from siqe.orchestration.client import TemporalGateway
from siqe.workflows.forge import (
    ForgeDatasetWorkflow,
    ForgeExportWorkflow,
    ForgePublishWorkflow,
    ForgeTrainWorkflow,
)

router = APIRouter(prefix="/forge", tags=["forge"])

TRAIN_TIMEOUT = timedelta(days=30)


# ------------------------------------------------------------------------------ design


@router.get("/catalog", response_model=list[ForgeBlockTypeOut], summary="Every block a model can use")
async def forge_catalog() -> list[ForgeBlockTypeOut]:
    return [ForgeBlockTypeOut.model_validate(b) for b in catalog()]


@router.get("/templates", response_model=list[ForgeTemplateOut], summary="Ready-made models to start from")
async def forge_templates() -> list[ForgeTemplateOut]:
    out = []
    for t in TEMPLATES:
        stats = analyze(ForgeGraph.model_validate(t.graph)).stats
        out.append(
            ForgeTemplateOut(
                id=t.id,
                name=t.name,
                summary=t.summary,
                graph=ForgeGraph.model_validate(t.graph),
                params=stats.params,
                scale=stats.scale,
            )
        )
    return out


@router.post("/check", response_model=ForgeAnalysis, summary="Shapes, problems and costs of a graph")
async def check_graph(body: ForgeCheckIn) -> ForgeAnalysis:
    return analyze(body.graph)


async def _project_out(session: AsyncSession, project: ForgeProject) -> ForgeProjectOut:
    analysis = analyze(ForgeGraph.model_validate(project.graph or EMPTY))
    runs, best = (
        await session.execute(
            select(func.count(), func.max(ForgeRun.best_psnr)).where(ForgeRun.project_id == project.id)
        )
    ).one()
    return ForgeProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        template=project.template,
        graph=analysis.graph,
        analysis=analysis,
        runs=int(runs),
        best_psnr=best,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("/projects", response_model=list[ForgeProjectOut], summary="Your model designs")
async def list_projects(session: SessionDep) -> list[ForgeProjectOut]:
    rows = (await session.execute(select(ForgeProject).order_by(ForgeProject.updated_at.desc()))).scalars()
    return [await _project_out(session, p) for p in rows]


@router.post(
    "/projects", response_model=ForgeProjectOut, status_code=status.HTTP_201_CREATED, summary="New model"
)
async def create_project(body: ForgeProjectIn, session: SessionDep) -> ForgeProjectOut:
    if body.template:
        template = TEMPLATES_BY_ID.get(body.template)
        if template is None:
            raise NotFoundError("forge.template_not_found", f"No template called '{body.template}'.")
        graph = template.graph
    elif body.graph is not None:
        graph = analyze(body.graph).graph.model_dump()
    else:
        graph = EMPTY
    project = ForgeProject(
        name=body.name.strip(), description=body.description, graph=graph, template=body.template
    )
    session.add(project)
    await session.flush()
    await publish_project(session, project.id)
    return await _project_out(session, project)


@router.get("/projects/{project_id}", response_model=ForgeProjectOut, summary="One model design")
async def one_project(project_id: uuid.UUID, session: SessionDep) -> ForgeProjectOut:
    return await _project_out(session, await get_project(session, project_id))


@router.put("/projects/{project_id}", response_model=ForgeProjectOut, summary="Change a model design")
async def update_project(
    project_id: uuid.UUID, body: ForgeProjectUpdateIn, session: SessionDep
) -> ForgeProjectOut:
    project = await get_project(session, project_id)
    if body.name is not None:
        project.name = body.name.strip()
    if body.description is not None:
        project.description = body.description
    if body.graph is not None:
        # Kept as drawn, with settings normalised; problems are reported, not refused.
        project.graph = analyze(body.graph).graph.model_dump()
    project.updated_at = utcnow()
    await publish_project(session, project.id)
    return await _project_out(session, project)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a model design (its training runs stay)",
)
async def delete_project(project_id: uuid.UUID, session: SessionDep) -> Response:
    project = await get_project(session, project_id)
    await session.delete(project)
    await publish_project(session, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/duplicate",
    response_model=ForgeProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="Copy a model design",
)
async def duplicate_project(project_id: uuid.UUID, session: SessionDep) -> ForgeProjectOut:
    project = await get_project(session, project_id)
    copy = ForgeProject(
        name=f"{project.name} (copy)"[:120],
        description=project.description,
        graph=project.graph,
        template=project.template,
    )
    session.add(copy)
    await session.flush()
    await publish_project(session, copy.id)
    return await _project_out(session, copy)


@router.get("/projects/{project_id}/code", response_model=ForgeCodeOut, summary="The design as PyTorch code")
async def project_code(project_id: uuid.UUID, session: SessionDep) -> ForgeCodeOut:
    project = await get_project(session, project_id)
    analysis = analyze(ForgeGraph.model_validate(project.graph or EMPTY))
    name = class_name(project.name)
    return ForgeCodeOut(filename=f"{name.lower()}.py", code=generate(project.name, analysis))


# ---------------------------------------------------------------------------- datasets


@router.get("/datasets", response_model=list[ForgeDatasetOut], summary="Training datasets")
async def list_datasets(session: SessionDep) -> list[ForgeDatasetOut]:
    rows = (await session.execute(select(ForgeDataset).order_by(ForgeDataset.created_at.desc()))).scalars()
    return [ForgeDatasetOut.model_validate(dataset_to_dict(d)) for d in rows]


async def _start_build(session: AsyncSession, temporal: TemporalGateway, dataset: ForgeDataset) -> None:
    job = await create_job(
        session,
        kind="forge.dataset",
        title=f"Build dataset {dataset.name}",
        params={"dataset_id": str(dataset.id)},
    )
    dataset.job_id = job.id
    dataset.state = JobState.queued
    dataset.error = None
    await publish_dataset(session, dataset)
    await start_workflow(
        session,
        temporal,
        job,
        ForgeDatasetWorkflow.run,
        [str(job.id), str(dataset.id)],
        run_timeout=timedelta(hours=6),
    )


@router.post(
    "/datasets",
    response_model=ForgeDatasetOut,
    status_code=status.HTTP_201_CREATED,
    summary="Build a dataset from Library images",
)
async def create_dataset(body: ForgeDatasetIn, session: SessionDep, temporal: TemporalDep) -> ForgeDatasetOut:
    if body.source.kind == "rules" and (body.source.rules is None or not body.source.rules.rules):
        raise AppError("forge.no_images", "Add some filters to choose images.", status=422)
    dataset = ForgeDataset(
        name=body.name.strip(),
        source=body.source.model_dump(),
        settings=body.settings.model_dump(),
        degradation=body.degradation.model_dump(),
        state=JobState.queued,
    )
    session.add(dataset)
    await session.flush()
    await _start_build(session, temporal, dataset)
    return ForgeDatasetOut.model_validate(dataset_to_dict(dataset))


@router.put(
    "/datasets/{dataset_id}/degradation",
    response_model=ForgeDatasetOut,
    summary="Change how training inputs are damaged (no rebuild needed)",
)
async def set_degradation(
    dataset_id: uuid.UUID, body: ForgeDegradationIn, session: SessionDep
) -> ForgeDatasetOut:
    dataset = await get_dataset(session, dataset_id)
    dataset.degradation = body.degradation.model_dump()
    dataset.updated_at = utcnow()
    await publish_dataset(session, dataset)
    return ForgeDatasetOut.model_validate(dataset_to_dict(dataset))


@router.post("/datasets/{dataset_id}/rebuild", response_model=ForgeDatasetOut, summary="Cut the crops again")
async def rebuild_dataset(
    dataset_id: uuid.UUID, session: SessionDep, temporal: TemporalDep
) -> ForgeDatasetOut:
    dataset = await get_dataset(session, dataset_id)
    if dataset.state in (JobState.queued, JobState.running):
        raise AppError("forge.dataset_busy", "This dataset is being built right now.", status=409)
    await _in_use(session, dataset.id)
    await _start_build(session, temporal, dataset)
    return ForgeDatasetOut.model_validate(dataset_to_dict(dataset))


async def _in_use(session: AsyncSession, dataset_id: uuid.UUID) -> None:
    busy = (
        await session.execute(
            select(func.count()).where(
                ForgeRun.dataset_id == dataset_id, ForgeRun.state.in_([JobState.queued, JobState.running])
            )
        )
    ).scalar_one()
    if busy:
        raise AppError(
            "forge.dataset_in_use",
            "A training run is using this dataset.",
            status=409,
            title="Dataset in use",
            fix="Stop the run first, or make a new dataset.",
        )


@router.delete(
    "/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a dataset and its crops",
)
async def delete_dataset(dataset_id: uuid.UUID, session: SessionDep) -> Response:
    dataset = await get_dataset(session, dataset_id)
    await _in_use(session, dataset.id)
    await session.delete(dataset)
    await session.flush()
    await publish(session, DATASET_EVENT, {"id": str(dataset_id), "deleted": True})
    await asyncio.to_thread(shutil.rmtree, datasets.root(dataset_id), True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/datasets/{dataset_id}/preview",
    response_class=Response,
    summary="Damaged inputs beside their clean crops (PNG)",
    responses={200: {"content": {"image/png": {}}}},
)
async def preview_dataset(
    dataset_id: uuid.UUID,
    session: SessionDep,
    scale: Annotated[int, Query(ge=1, le=8)] = 2,
    seed: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> Response:
    dataset = await get_dataset(session, dataset_id)
    degradation = Degradation.model_validate(dataset.degradation or {})
    try:
        png = await asyncio.to_thread(datasets.preview, dataset.id, scale, degradation, count=3, seed=seed)
    except FileNotFoundError as exc:
        raise AppError(
            "forge.dataset_not_ready",
            "This dataset has no crops yet.",
            status=409,
            fix="Wait for it to finish.",
        ) from exc
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


# -------------------------------------------------------------------------------- runs


def _run_out(run: ForgeRun) -> ForgeRunOut:
    return ForgeRunOut.model_validate(run_to_dict(run))


@router.post(
    "/projects/{project_id}/runs",
    response_model=ForgeRunOut,
    status_code=status.HTTP_201_CREATED,
    summary="Train a model design on a dataset",
)
async def start_run(
    project_id: uuid.UUID, body: ForgeRunIn, session: SessionDep, temporal: TemporalDep
) -> ForgeRunOut:
    project = await get_project(session, project_id)
    analysis = analyze(ForgeGraph.model_validate(project.graph or EMPTY))
    if analysis.problems or analysis.stats.scale is None:
        raise AppError(
            "forge.invalid",
            "This model can't train yet: "
            f"{analysis.problems[0].message if analysis.problems else 'it is empty'}.",
            status=422,
            title="Model not ready",
            fix="Fix the blocks marked in red, then train again.",
        )
    dataset = await get_dataset(session, body.dataset_id)
    if dataset.state != JobState.succeeded or dataset.train_crops == 0:
        raise AppError(
            "forge.dataset_not_ready",
            "The dataset isn't ready yet."
            if dataset.state != JobState.failed
            else "The dataset failed to build.",
            status=409,
            fix="Wait for it to finish building, or build it again.",
        )
    settings: TrainSettings = body.settings
    scale, multiple = analysis.stats.scale, analysis.stats.patch_multiple
    if settings.patch % multiple:
        raise AppError(
            "forge.patch_multiple",
            f"This model halves the image {multiple.bit_length() - 1} time(s), so patches must be a multiple "
            f"of {multiple}.",
            status=422,
            fix=f"Use a patch of {settings.patch - settings.patch % multiple or multiple} px.",
        )
    crop = int((dataset.settings or {}).get("crop", 256))
    if settings.patch * scale > crop:
        raise AppError(
            "forge.patch_too_big",
            f"A {settings.patch} px patch at ×{scale} needs {settings.patch * scale} px crops; "
            f"this dataset has {crop}.",
            status=422,
            fix=f"Use a patch of at most {crop // scale} px, or build a dataset with bigger crops.",
        )
    run = ForgeRun(
        project_id=project.id,
        project_name=project.name,
        dataset_id=dataset.id,
        graph=analysis.graph.model_dump(),
        plan=analysis.plan,
        scale=scale,
        color=analysis.stats.color,
        settings=settings.model_dump(),
        state=JobState.queued,
        total_steps=settings.steps,
        batch=settings.batch,
    )
    session.add(run)
    await session.flush()
    job = await create_job(
        session,
        kind="forge.train",
        title=f"Train {project.name} for {settings.steps:,} steps",
        params={"run_id": str(run.id), "project_id": str(project.id)},
    )
    run.job_id = job.id
    await publish_run(session, run)
    await start_workflow(
        session, temporal, job, ForgeTrainWorkflow.run, [str(run.id)], run_timeout=TRAIN_TIMEOUT
    )
    return _run_out(run)


@router.get("/runs", response_model=list[ForgeRunOut], summary="Training runs, newest first")
async def list_runs(
    session: SessionDep,
    project_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ForgeRunOut]:
    stmt = select(ForgeRun).order_by(ForgeRun.created_at.desc()).limit(limit)
    if project_id is not None:
        stmt = stmt.where(ForgeRun.project_id == project_id)
    return [_run_out(r) for r in (await session.execute(stmt)).scalars()]


@router.get("/runs/{run_id}", response_model=ForgeRunDetailOut, summary="A run and its charts")
async def one_run(run_id: uuid.UUID, session: SessionDep) -> ForgeRunDetailOut:
    run = await get_run(session, run_id)
    metrics = (
        await session.execute(
            select(ForgeMetric).where(ForgeMetric.run_id == run.id).order_by(ForgeMetric.step, ForgeMetric.id)
        )
    ).scalars()
    return ForgeRunDetailOut(
        run=_run_out(run),
        metrics=[
            ForgeMetricOut(step=m.step, kind=m.kind, loss=m.loss, psnr=m.psnr, ssim=m.ssim, lr=m.lr)
            for m in metrics
        ],
    )


async def _signal(
    session: AsyncSession, temporal: TemporalGateway, run_id: uuid.UUID, signal: str
) -> ForgeRunOut:
    run = await get_run(session, run_id, for_update=True)
    if run.state not in (JobState.queued, JobState.running) or run.job_id is None:
        raise AppError("forge.not_running", "This run has already finished.", status=409)
    if signal in ("pause", "resume"):
        run.paused = signal == "pause"
    await publish_run(session, run)
    await session.commit()
    client = await temporal.client()
    try:
        await client.get_workflow_handle(f"job-{run.job_id}").signal(signal)
    except Exception as exc:
        raise AppError("temporal.unavailable", "The job engine didn't take the request.", status=503) from exc
    return _run_out(run)


@router.post(
    "/runs/{run_id}/pause", response_model=ForgeRunOut, summary="Pause training (saves a checkpoint)"
)
async def pause_run(run_id: uuid.UUID, session: SessionDep, temporal: TemporalDep) -> ForgeRunOut:
    return await _signal(session, temporal, run_id, "pause")


@router.post("/runs/{run_id}/resume", response_model=ForgeRunOut, summary="Carry on training")
async def resume_run(run_id: uuid.UUID, session: SessionDep, temporal: TemporalDep) -> ForgeRunOut:
    return await _signal(session, temporal, run_id, "resume")


@router.post(
    "/runs/{run_id}/stop",
    response_model=ForgeRunOut,
    summary="Finish now, keeping the best checkpoint so far",
)
async def stop_run(run_id: uuid.UUID, session: SessionDep, temporal: TemporalDep) -> ForgeRunOut:
    return await _signal(session, temporal, run_id, "stop")


@router.get(
    "/runs/{run_id}/sample",
    response_class=FileResponse,
    summary="Bicubic, the model and the original, side by side (PNG)",
)
async def run_sample(run_id: uuid.UUID, session: SessionDep) -> FileResponse:
    run = await get_run(session, run_id)
    path = sample_path(run.id)
    if not path.exists():
        raise NotFoundError("forge.no_sample", "No validation has run yet.", title="Not yet")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get(
    "/runs/{run_id}/weights",
    response_class=FileResponse,
    summary="The best checkpoint's weights (safetensors), for the generated code",
)
async def run_weights(run_id: uuid.UUID, session: SessionDep) -> FileResponse:
    run = await get_run(session, run_id)
    path = best_weights(run.id)
    if not path.exists():
        raise NotFoundError("forge.nothing_to_publish", "This run hasn't saved a validated checkpoint yet.")
    name = f"{class_name(run.project_name).lower()}-step{run.best_step or 0}.safetensors"
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post(
    "/runs/{run_id}/onnx",
    response_model=ForgeExportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Export the best checkpoint to ONNX, checked against PyTorch",
    description=(
        "Runs on the AI worker. The file takes one N×C×H×W input named `input` (values 0 to 1, any batch, "
        "height and width in steps of the model's patch multiple) and returns `output`. Download it from "
        "`GET /runs/{run_id}/onnx` once the job succeeds."
    ),
)
async def export_run_onnx(run_id: uuid.UUID, session: SessionDep, temporal: TemporalDep) -> ForgeExportOut:
    run = await get_run(session, run_id)
    if not best_weights(run.id).exists():
        raise AppError(
            "forge.nothing_to_publish",
            "This run hasn't saved a validated checkpoint yet.",
            status=409,
            fix="Let it train past its first validation, then export.",
        )
    job = await create_job(
        session,
        kind="forge.export",
        title=f"Export {run.project_name} to ONNX",
        params={"run_id": str(run.id)},
    )
    await start_workflow(session, temporal, job, ForgeExportWorkflow.run, [str(job.id), str(run.id)])
    return ForgeExportOut(job=JobOut.model_validate(job_to_dict(job)))


@router.get(
    "/runs/{run_id}/onnx",
    response_class=FileResponse,
    summary="The exported ONNX file",
)
async def run_onnx(run_id: uuid.UUID, session: SessionDep) -> FileResponse:
    run = await get_run(session, run_id)
    path = onnx_path(run.id)
    if not run.onnx_export or not path.exists():
        raise NotFoundError(
            "forge.no_onnx", "This run hasn't been exported to ONNX yet.", title="Not exported"
        )
    step = run.onnx_export.get("step", run.best_step or 0)
    name = f"{class_name(run.project_name).lower()}-step{step}.onnx"
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post(
    "/runs/{run_id}/publish",
    response_model=ForgePublishOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Score the best checkpoint and add it to AI Lab",
)
async def publish_to_lab(
    run_id: uuid.UUID, body: ForgePublishIn, session: SessionDep, temporal: TemporalDep
) -> ForgePublishOut:
    run = await get_run(session, run_id)
    if not best_weights(run.id).exists():
        raise AppError(
            "forge.nothing_to_publish",
            "This run hasn't saved a validated checkpoint yet.",
            status=409,
            fix="Let it train past its first validation, then publish.",
        )
    job = await create_job(
        session,
        kind="forge.publish",
        title=f"Publish {body.name} to AI Lab",
        params={"run_id": str(run.id)},
    )
    await start_workflow(
        session,
        temporal,
        job,
        ForgePublishWorkflow.run,
        [str(job.id), str(run.id), body.name.strip(), body.summary],
        run_timeout=timedelta(hours=13),
    )
    return ForgePublishOut(job=JobOut.model_validate(job_to_dict(job)))


@router.delete(
    "/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a finished run and its checkpoints (published models stay)",
)
async def delete_run(run_id: uuid.UUID, session: SessionDep) -> Response:
    run = await get_run(session, run_id)
    if run.state in (JobState.queued, JobState.running):
        raise AppError("forge.run_busy", "This run is still training.", status=409, fix="Stop it first.")
    await session.delete(run)
    await session.flush()
    await publish(session, RUN_EVENT, {"id": str(run_id), "deleted": True})
    await asyncio.to_thread(shutil.rmtree, run_dir(run_id), True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
