import asyncio
from datetime import timedelta

from fastapi import APIRouter, Response, status

from siqe.ai.registry import (
    all_rows,
    catalog,
    get_row,
    get_spec,
    model_to_dict,
    publish_model,
    remove_files,
    status_of,
)
from siqe.api.deps import SessionDep, SettingsDep, TemporalDep
from siqe.api.schemas import JobOut, ModelInstallOut, ModelOut
from siqe.core.errors import AppError
from siqe.db.models import AiModel, Job, ModelStatus
from siqe.jobs.records import job_to_dict
from siqe.jobs.start import create_job, start_workflow
from siqe.storage.store import get_store
from siqe.workflows.models import ModelInstallWorkflow

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
