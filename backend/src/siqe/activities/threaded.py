"""Run blocking image work in a thread while the activity keeps reporting and stays cancellable.

libvips reports evaluation progress through a callback in the worker thread. The callback
records the latest fraction; the async side forwards it to ``ProgressReporter`` (which also
heartbeats). When Temporal cancels the activity, the callback asks libvips to stop the
evaluation, so the thread ends promptly instead of finishing a doomed render.
"""

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from siqe.jobs.progress import ProgressReporter


class ThreadProgress:
    def __init__(self) -> None:
        self.fraction = 0.0
        self.message: str | None = None
        self.details: dict[str, Any] | None = None
        self.cancelled = threading.Event()

    def update(
        self, fraction: float, message: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        if self.cancelled.is_set():
            raise InterruptedError("cancelled")
        self.fraction = max(self.fraction, min(1.0, fraction))
        if message is not None:
            self.message = message
        if details is not None:
            self.details = details


def consume(task: "asyncio.Task[Any]") -> None:
    """Mark a cancelled thread task's outcome as seen, now or when it ends.

    A thread stopped by cancellation ends with InterruptedError; nobody awaits it any more, so
    without this asyncio logs "Task exception was never retrieved" for every cancelled job.
    """

    def seen(t: "asyncio.Task[Any]") -> None:
        if not t.cancelled():
            t.exception()

    if task.done():
        seen(task)
    else:
        task.add_done_callback(seen)


async def run_threaded[T](
    work: Callable[[ThreadProgress], T], reporter: ProgressReporter, *, interval: float = 0.5
) -> T:
    state = ThreadProgress()
    task = asyncio.create_task(asyncio.to_thread(work, state))
    try:
        while not task.done():
            await reporter.report(state.fraction, state.message, details=state.details)
            await asyncio.wait({task}, timeout=interval)
        return task.result()
    except asyncio.CancelledError:
        state.cancelled.set()
        # Let the thread notice and unwind before the activity reports cancellation.
        await asyncio.wait({task}, timeout=30)
        consume(task)
        raise
