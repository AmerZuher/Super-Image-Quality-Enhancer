import uuid
from typing import Any

from fastapi import APIRouter, status

from siqe.activities.ai import AiRunRequest
from siqe.ai.governor import Calibration
from siqe.ai.manifest import FACE_MODEL_ID, TASK_LABELS
from siqe.ai.plan import current_device, plan_run
from siqe.ai.registry import get_spec, require_installed
from siqe.api.deps import SessionDep, SettingsDep, TemporalDep
from siqe.api.schemas import AiPlanOut, AiRunIn, AiRunStartOut, JobOut
from siqe.assets.records import get_asset
from siqe.core.config import Settings
from siqe.core.errors import AppError
from siqe.db.models import AssetStatus
from siqe.jobs.records import job_to_dict
from siqe.jobs.start import create_job, start_workflow
from siqe.storage.store import get_store
from siqe.workflows.ai import AiRunWorkflow

router = APIRouter(prefix="/ai", tags=["ai"])


async def _plan(body: AiRunIn, session: SessionDep, settings: Settings) -> tuple[dict[str, Any], Any, Any]:
    try:
        asset_id = uuid.UUID(body.asset_id)
    except ValueError as exc:
        raise AppError(
            "asset.not_found", "No image with that id.", status=404, title="Image not found"
        ) from exc
    spec = get_spec(body.model_id)
    if spec.task == "embed":
        raise AppError(
            "model.not_runnable",
            f"{spec.name} powers Library search and doesn't make images.",
            status=422,
            title="Not an image model",
            fix="Pick an upscale, denoise, background or face model.",
        )
    asset = await get_asset(session, asset_id)
    if asset.status != AssetStatus.ready:
        raise AppError(
            "asset.not_ready",
            "This image is still being prepared."
            if asset.status == AssetStatus.processing
            else "This image failed to load.",
            status=409,
            title="Image not ready",
            fix="Wait for the preview to appear, or upload the file again.",
        )
    row = await require_installed(session, spec)
    faces = body.restore_faces and spec.task == "upscale"
    if faces:
        await require_installed(session, get_spec(FACE_MODEL_ID))
    device = await current_device(session, body.device, settings.worker_heartbeat_seconds)
    plan = plan_run(
        spec,
        width=asset.width,
        height=asset.height,
        bit_depth=asset.bit_depth,
        has_alpha=asset.has_alpha,
        device=device,
        calibration=Calibration.from_dict((row.calibration or {}).get(device.key)),
        reserve_mb=settings.gpu_vram_reserve_mb,
        restore_faces=faces,
    )
    if plan["output_megapixels"] > settings.max_output_megapixels:
        raise AppError(
            "ai.output_too_large",
            f"The result would be {plan['output_megapixels']:,.0f} megapixels; the limit is "
            f"{settings.max_output_megapixels:,}.",
            status=422,
            title="Result too large",
            fix="Use a ×2 model, crop and export a smaller copy first, or raise SIQE_MAX_OUTPUT_MEGAPIXELS.",
        )
    return plan, spec, asset


@router.post("/plan", response_model=AiPlanOut, summary="What a run would produce, and how it would run")
async def plan(body: AiRunIn, session: SessionDep, settings: SettingsDep) -> AiPlanOut:
    result, _, _ = await _plan(body, session, settings)
    return AiPlanOut.model_validate(result)


@router.post(
    "/runs",
    response_model=AiRunStartOut,
    status_code=status.HTTP_201_CREATED,
    summary="Run a model on an image; the result becomes a new image",
)
async def start_run(
    body: AiRunIn, session: SessionDep, settings: SettingsDep, temporal: TemporalDep
) -> AiRunStartOut:
    result, spec, asset = await _plan(body, session, settings)
    get_store().ensure_space(settings, int(result["disk_bytes"]))
    title = f"{TASK_LABELS[spec.task]} {asset.original_name}"
    if spec.task == "upscale":
        title += f" ×{spec.scale} with {spec.name}"
        if result["restore_faces"]:
            title += " and face restoration"
    job = await create_job(
        session,
        kind="ai.run",
        title=title,
        params={
            "asset_id": str(asset.id),
            "model_id": spec.id,
            "device": body.device,
            "restore_faces": bool(result["restore_faces"]),
        },
    )
    request = AiRunRequest(
        asset_id=str(asset.id),
        model_id=spec.id,
        device=body.device,
        restore_faces=bool(result["restore_faces"]) and spec.task == "upscale",
    )
    await start_workflow(session, temporal, job, AiRunWorkflow.run, [str(job.id), request])
    return AiRunStartOut(job=JobOut.model_validate(job_to_dict(job)), plan=AiPlanOut.model_validate(result))
