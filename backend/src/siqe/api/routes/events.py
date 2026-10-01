import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from siqe.events.bus import EventHub

router = APIRouter(tags=["events"])

PING_SECONDS = 25


@router.websocket("/events")
async def events_socket(ws: WebSocket) -> None:
    """Live events: ``job.updated``, ``worker.heartbeat``, ``events.resync`` and ``ping``."""
    hub: EventHub = ws.app.state.events
    await ws.accept()
    queue = hub.subscribe()
    try:
        await ws.send_json({"type": "events.hello", "data": {"version": ws.app.state.settings.version}})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
            except TimeoutError:
                event = {"type": "ping", "data": {}}
            await ws.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(queue)
