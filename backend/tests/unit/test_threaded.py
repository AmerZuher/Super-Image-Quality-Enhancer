"""Cancelling threaded work: the thread stops, and its InterruptedError is never left unread."""

import asyncio
import threading
import time
from typing import Any

import pytest

from siqe.activities.threaded import ThreadProgress, run_threaded


class _Reporter:
    def __init__(self) -> None:
        self.reports: list[float] = []

    async def report(self, fraction: float, message: str | None = None, **_: Any) -> None:
        self.reports.append(fraction)


async def test_cancelling_stops_the_thread_without_unread_errors() -> None:
    loop = asyncio.get_running_loop()
    unread: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: unread.append(context))
    started = threading.Event()

    def work(state: ThreadProgress) -> None:
        started.set()
        while True:  # a long render that checks in regularly
            state.update(0.5, "working")
            time.sleep(0.01)

    task = asyncio.create_task(run_threaded(work, _Reporter(), interval=0.02))  # type: ignore[arg-type]
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Give asyncio a chance to collect the finished thread task and report anything unread.
    import gc

    for _ in range(3):
        await asyncio.sleep(0.05)
        gc.collect()
    assert not [c for c in unread if "never retrieved" in str(c.get("message", ""))]


async def test_results_and_errors_still_come_back() -> None:
    assert await run_threaded(lambda state: 42, _Reporter()) == 42  # type: ignore[arg-type]

    def fail(state: ThreadProgress) -> None:
        raise ValueError("bad file")

    with pytest.raises(ValueError, match="bad file"):
        await run_threaded(fail, _Reporter())  # type: ignore[arg-type]
