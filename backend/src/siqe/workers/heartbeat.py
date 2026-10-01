"""Workers report who they are and what hardware they see, every few seconds."""

import asyncio
import contextlib
import socket
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.dialects.postgresql import insert

from siqe.ai.devices import nvml_devices, torch_runtime
from siqe.core.config import Settings
from siqe.core.logging import get_logger
from siqe.db.base import utcnow
from siqe.db.models import WorkerHeartbeat
from siqe.db.session import session_scope
from siqe.events.bus import publish
from siqe.system.resources import snapshot

log = get_logger(__name__)

WorkerKind = Literal["cpu", "gpu"]


def collect_info(kind: WorkerKind, settings: Settings) -> dict[str, Any]:
    info: dict[str, Any] = {"system": snapshot(settings.data_dir)}
    if kind == "gpu":
        info["gpus"] = nvml_devices()
        info["torch"] = torch_runtime()
    return info


class HeartbeatLoop:
    def __init__(self, kind: WorkerKind, settings: Settings) -> None:
        self.kind = kind
        self.settings = settings
        self.hostname = socket.gethostname()
        self.worker_id = f"{kind}@{self.hostname}"
        self.started_at: datetime = utcnow()
        self._task: asyncio.Task[None] | None = None

    async def beat(self) -> None:
        info = await asyncio.to_thread(collect_info, self.kind, self.settings)
        now = utcnow()
        values = {
            "id": self.worker_id,
            "kind": self.kind,
            "hostname": self.hostname,
            "version": self.settings.version,
            "info": info,
            "started_at": self.started_at,
            "last_seen": now,
        }
        stmt = insert(WorkerHeartbeat).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[WorkerHeartbeat.id],
            set_={k: stmt.excluded[k] for k in ("kind", "version", "info", "started_at", "last_seen")},
        )
        async with session_scope() as session:
            await session.execute(stmt)
            await publish(session, "worker.heartbeat", {**values, "last_seen": now.isoformat()})

    async def _run(self) -> None:
        while True:
            try:
                await self.beat()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a missed heartbeat must never kill the worker
                log.warning("worker.heartbeat_failed", error=str(exc))
            await asyncio.sleep(self.settings.worker_heartbeat_seconds)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="worker-heartbeat")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
