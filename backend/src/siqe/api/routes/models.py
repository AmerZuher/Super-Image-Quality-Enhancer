import asyncio
import re
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response, status

from siqe.activities.models import OnnxImport
from siqe.ai.registry import (
    MAX_ONNX_MB,
    USER_PREFIX,
    all_rows,
    catalog,
    files_present,
    get_row,
    get_spec,
    model_to_dict,
    models_root,
    publish_model,
    remove_files,
    source_of,
    status_of,
    user_staging,
)
from siqe.api.deps import SessionDep, SettingsDep, TemporalDep
from siqe.api.schemas import JobOut, ModelImportOut, ModelInstallOut, ModelOut
from siqe.core.errors import AppError
from siqe.db.base import utcnow
from siqe.db.models import AiModel, Job, ModelStatus
from siqe.jobs.records import job_to_dict
from siqe.jobs.start import create_job, start_workflow
from siqe.storage.store import get_store
from siqe.workflows.models import ModelImportWorkflow, ModelInstallWorkflow

router = APIRouter(tags=["models"])


@router.get("/models", response_model=list[ModelOut], summary="The model catalog and what is installed")
async def list_models(session: SessionDep) -> list[ModelOut]:
    rows = await all_rows(session)
    return [ModelOut.model_validate(model_to_dict(spec, rows.get(spec.id))) for spec in catalog()]


@router.post(
    "/models/{model_id}/install",
    response_model=ModelInstallOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Download, verify and install a model",
    description=(
        "Idempotent: an installed model returns with `job: null`; a download in progress returns its job."
    ),
)
async def install_model(
    model_id: str, session: SessionDep, settings: SettingsDep, temporal: TemporalDep
) -> ModelInstallOut:
    spec = get_spec(model_id)
    row = await get_row(session, model_id, for_update=True)
    current = status_of(spec, row)
    if current == "installed":
        return ModelInstallOut(model=ModelOut.model_validate(model_to_dict(spec, row)), job=None)
    if source_of(spec) != "catalog":
        # Trained or added here, not downloaded: register the files if they're still on the data volume.
        if not files_present(spec):
            raise AppError(
                "forge.model_files_missing",
                f"{spec.name}'s weights are no longer on the data volume.",
                status=409,
                title="Files missing",
                fix="Publish the training run from Forge again."
                if spec.arch == "forge"
                else "Add the ONNX file again.",
            )
        if row is None:
            row = AiModel(id=spec.id, source=source_of(spec))
            session.add(row)
        row.status = ModelStatus.installed
        row.installed_at = utcnow()
        await publish_model(session, spec, row)
        return ModelInstallOut(model=ModelOut.model_validate(model_to_dict(spec, row)), job=None)
    if current == "downloading" and row is not None and row.job_id:
        job = await session.get(Job, row.job_id)
        if job is not None and not job.state.is_final:
            return ModelInstallOut(
                model=ModelOut.model_validate(model_to_dict(spec, row)),
                job=JobOut.model_validate(job_to_dict(job)),
            )
    get_store().ensure_space(settings, spec.size_bytes)
    if row is None:
        row = AiModel(id=spec.id, status=ModelStatus.downloading)
        session.add(row)
    row.status = ModelStatus.downloading
    row.bytes_total = spec.size_bytes
    row.bytes_done = 0
    row.error = None
    job = await create_job(
        session, kind="model.install", title=f"Download {spec.name}", params={"model_id": spec.id}
    )
    row.job_id = job.id
    await publish_model(session, spec, row)
    await start_workflow(
        session,
        temporal,
        job,
        ModelInstallWorkflow.run,
        [str(job.id), spec.id],
        run_timeout=timedelta(hours=6),
    )
    return ModelInstallOut(
        model=ModelOut.model_validate(model_to_dict(spec, row)), job=JobOut.model_validate(job_to_dict(job))
    )


@router.delete(
    "/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a model's downloaded files"
)
async def remove_model(model_id: str, session: SessionDep) -> Response:
    spec = get_spec(model_id)
    row = await get_row(session, model_id, for_update=True)
    if row is not None and row.status == ModelStatus.downloading:
        raise AppError(
            "model.busy",
            f"{spec.name} is still downloading.",
            status=409,
            title="Model busy",
            fix="Wait for the download to finish, or cancel it on the Jobs page.",
        )
    await asyncio.to_thread(remove_files, spec)
    if row is not None:
        await session.delete(row)
    await publish_model(session, spec, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "model"


def _reserve_id(name: str) -> str:
    """A free ``user-<name>`` id, reserved by creating its staging folder (so two imports of the
    same name can't collide)."""
    root = models_root()
    root.mkdir(parents=True, exist_ok=True)
    base = f"{USER_PREFIX}{_slug(name)}"
    candidate, n = base, 2
    while True:
        if not (root / candidate).exists():
            try:
                user_staging(candidate).mkdir()
                return candidate
            except FileExistsError:
                pass
        candidate, n = f"{base}-{n}", n + 1


@router.post(
    "/models/onnx",
    response_model=ModelImportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Add your own ONNX model (raw request body)",
    description=(
        "Send the .onnx file as the request body. A job runs the model on test images to find its "
        "scale, size step, output range and speed, then adds it to AI Lab and Flows. Same-size models "
        "are listed under `task` (denoise by default); models that enlarge are always upscalers. "
        f"At most {MAX_ONNX_MB} MB, one file (no external data)."
    ),
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/octet-stream": {"schema": {}}}}
    },
)
async def import_onnx_model(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    temporal: TemporalDep,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    name: Annotated[str | None, Query(max_length=60)] = None,
    task: Annotated[Literal["denoise", "deblur"] | None, Query()] = None,
) -> ModelImportOut:
    if not filename.lower().endswith(".onnx"):
        raise AppError(
            "onnx.wrong_type",
            f"'{filename}' isn't an .onnx file.",
            status=415,
            title="Not an ONNX model",
            fix="Export the model to ONNX (for example with torch.onnx.export) and add the .onnx file.",
        )
    store = get_store()
    store.ensure_space(settings)
    staged = await store.receive(
        request.stream(),
        MAX_ONNX_MB * 1024 * 1024,
        too_large_fix=f"Models up to {MAX_ONNX_MB:,} MB can be added; use a smaller or float16 export.",
    )
    label = (name or "").strip() or filename[: -len(".onnx")].replace("_", " ").strip() or "My model"
    model_id = await asyncio.to_thread(_reserve_id, label)
    job = await create_job(
        session,
        kind="model.import",
        title=f"Add {label}",
        params={"model_id": model_id, "filename": filename, "size_bytes": staged.size_bytes},
    )
    req = OnnxImport(
        job_id=str(job.id),
        staged=str(staged.path),
        model_id=model_id,
        name=label,
        task=task,
        sha256=staged.sha256,
        size=staged.size_bytes,
    )
    await start_workflow(session, temporal, job, ModelImportWorkflow.run, [req])
    return ModelImportOut(model_id=model_id, job=JobOut.model_validate(job_to_dict(job)))
