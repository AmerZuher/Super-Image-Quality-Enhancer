"""Live events over PostgreSQL LISTEN/NOTIFY.

Workers publish inside the same transaction as the row change, so an event is only ever
delivered for data that was actually committed. The API holds one listening connection and
fans events out to WebSocket clients through bounded queues: a slow browser drops old
events instead of growing memory without limit.
"""

import asyncio
import contextlib
import json
from collections.abc import Callable
from typing import Any

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.core.logging import get_logger

log = get_logger(__name__)

CHANNEL = "siqe_events"
# PostgreSQL rejects NOTIFY payloads of 8000 bytes or more.
MAX_PAYLOAD_BYTES = 7900
SUBSCRIBER_QUEUE_SIZE = 500


def encode_event(event_type: str, data: dict[str, Any]) -> str:
    payload = json.dumps({"type": event_type, "data": data}, default=str, separators=(",", ":"))
    if len(payload.encode()) > MAX_PAYLOAD_BYTES:
        # Too big to carry: send a pointer so clients refetch the resource instead.
        slim = {k: data[k] for k in ("id", "kind", "state", "progress") if k in data}
        payload = json.dumps({"type": event_type, "data": {**slim, "truncated": True}}, default=str)
    return payload


async def publish(session: AsyncSession, event_type: str, data: dict[str, Any]) -> None:
    """Queue an event; PostgreSQL delivers it when the session's transaction commits."""
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": encode_event(event_type, data)},
    )


class EventHub:
    """One LISTEN connection per API process, fanned out to any number of subscribers."""

    def __init__(self, dsn: str, *, connect: Callable[[str], Any] = asyncpg.connect) -> None:
        self._dsn = dsn
        self._connect = connect
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self.connected = False

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def dispatch(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        try:
            event = json.loads(payload)
        except ValueError:
            log.warning("events.bad_payload", payload=payload[:200])
            return
        self.dispatch(event)

    async def start(self) -> None:
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="event-hub")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        delay = 1.0
        while not self._stopping.is_set():
            conn = None
            try:
                conn = await self._connect(self._dsn)
                await conn.add_listener(CHANNEL, self._on_notify)
                self.connected = True
                delay = 1.0
                log.info("events.listening", channel=CHANNEL)
                # Tell clients to refetch anything they may have missed while disconnected.
                self.dispatch({"type": "events.resync", "data": {}})
                while not self._stopping.is_set() and not conn.is_closed():
                    await asyncio.sleep(15)
                    await conn.execute("SELECT 1")  # keepalive; raises if the link is dead
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("events.connection_lost", error=str(exc), retry_in=delay)
            finally:
                self.connected = False
                if conn is not None and not conn.is_closed():
                    await conn.close()
            if not self._stopping.is_set():
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
