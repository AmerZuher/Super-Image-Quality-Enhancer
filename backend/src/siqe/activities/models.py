"""Activities for the model registry: downloading, verifying and installing weights."""

from dataclasses import dataclass
from typing import Any

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from siqe.activities.threaded import ThreadProgress, run_threaded
from siqe.ai.registry import get_row, get_spec, install_files, publish_model
from siqe.core.errors import AppError
from siqe.db.base import utcnow
from siqe.db.models import ModelStatus
from siqe.db.session import session_scope
from siqe.jobs.progress import ProgressReporter

# Network hiccups are retried (and resume from the partial file); anything else is final.
RETRYABLE = frozenset({"model.download_failed"})


@activity.defn
async def install_model(job_id: str, model_id: str) -> dict[str, Any]:
    spec = get_spec(model_id)
    reporter = ProgressReporter(job_id)

    def work(state: ThreadProgress) -> str:
        timeout = httpx.Timeout(30.0, read=120.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            path = install_files(
                spec,
                client,
                on_progress=lambda done, total: state.update(
                    done / total, f"{done / 1e6:,.0f} of {total / 1e6:,.0f} MB"
                ),
                should_stop=state.cancelled.is_set,
            )
        return str(path)

    try:
        path = await run_threaded(work, reporter)
    except AppError as exc:
        raise ApplicationError(
            exc.detail,
            {"code": exc.code, "fix": exc.fix},
            type=exc.code,
            non_retryable=exc.code not in RETRYABLE,
        ) from exc

    async with session_scope() as session:
        row = await get_row(session, model_id, for_update=True)
        if row is not None:
            row.status = ModelStatus.installed
            row.bytes_done = spec.size_bytes
            row.installed_at = utcnow()
            row.error = None
            await publish_model(session, spec, row)
    return {"path": path, "size_bytes": spec.size_bytes}


@dataclass
class ModelFailure:
    model_id: str
    code: str
    message: str


@activity.defn
async def mark_model_failed(failure: ModelFailure) -> None:
    spec = get_spec(failure.model_id)
    async with session_scope() as session:
        row = await get_row(session, failure.model_id, for_update=True)
        if row is None:
            return
        if failure.code == "cancelled":
            # A cancelled download leaves the model as if it had never been requested.
            await session.delete(row)
            await publish_model(session, spec, None)
            return
        row.status = ModelStatus.failed
        row.error = {"code": failure.code, "message": failure.message}
        await publish_model(session, spec, row)
