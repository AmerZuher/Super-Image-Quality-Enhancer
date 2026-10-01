import asyncio
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import select, text

from siqe.api.deps import EventsDep, SessionDep, SettingsDep, TemporalDep
from siqe.api.schemas import ServicesOut, SystemOut, WorkerOut
from siqe.db.base import utcnow
from siqe.db.models import WorkerHeartbeat
from siqe.system.resources import snapshot

router = APIRouter(prefix="/system", tags=["system"])


@router.get("", response_model=SystemOut, summary="Version, services, workers and hardware")
async def system_status(
    session: SessionDep, settings: SettingsDep, temporal: TemporalDep, events: EventsDep
) -> SystemOut:
    await session.execute(text("SELECT 1"))
    rows = (await session.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.kind))).scalars()
    cutoff = utcnow() - timedelta(seconds=settings.worker_heartbeat_seconds * 3)
    workers = [
        WorkerOut(
            id=w.id,
            kind=w.kind,
            hostname=w.hostname,
            version=w.version,
            online=w.last_seen >= cutoff,
            last_seen=w.last_seen,
            started_at=w.started_at,
            info=w.info,
        )
        for w in rows
    ]
    # Containers get new hostnames on every restart; hide stale entries after a day.
    workers = [w for w in workers if w.online or utcnow() - w.last_seen < timedelta(days=1)]
    return SystemOut(
        version=settings.version,
        environment=settings.environment,
        services=ServicesOut(database=True, temporal=await temporal.healthy(), events=events.connected),
        api=await asyncio.to_thread(snapshot, settings.data_dir),
        workers=workers,
    )
