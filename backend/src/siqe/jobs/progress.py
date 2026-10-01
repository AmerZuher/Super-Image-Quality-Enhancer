"""Progress reporting from inside activities.

Writes are throttled so a fast loop (one call per tile) can't flood the database, and every
report doubles as a Temporal heartbeat so a stuck activity is detected and retried.
"""

import time
import uuid
from typing import Any

from temporalio import activity

from siqe.db.models import JobState
from siqe.db.session import session_scope
from siqe.jobs.records import apply_update


class ProgressReporter:
    def __init__(self, job_id: str, *, start: float = 0.0, span: float = 1.0, min_interval: float = 0.25):
        self.job_id = uuid.UUID(job_id)
        self.start = start
        self.span = span
        self.min_interval = min_interval
        self._last_write = 0.0

    def _heartbeat(self, details: Any) -> None:
        if activity.in_activity():
            activity.heartbeat(details)

    async def report(self, fraction: float, message: str | None = None, *, force: bool = False) -> None:
        overall = self.start + self.span * max(0.0, min(1.0, fraction))
        self._heartbeat({"progress": overall, "message": message})
        now = time.monotonic()
        if not force and now - self._last_write < self.min_interval:
            return
        self._last_write = now
        async with session_scope() as session:
            await apply_update(session, self.job_id, progress=overall, message=message)

    async def state(self, state: JobState, message: str | None = None) -> None:
        async with session_scope() as session:
            await apply_update(session, self.job_id, state=state, message=message)
