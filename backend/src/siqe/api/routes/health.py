from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from siqe.api.deps import EventsDep, SessionDep, TemporalDep
from siqe.api.schemas import HealthOut

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthOut, summary="The API process is running")
async def live() -> HealthOut:
    return HealthOut(status="ok")


@router.get(
    "/ready",
    response_model=HealthOut,
    summary="Database and job engine are reachable",
    responses={503: {"model": HealthOut}},
)
async def ready(session: SessionDep, temporal: TemporalDep, events: EventsDep) -> HealthOut | JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
        database = True
    except Exception:
        database = False
    checks = {"database": database, "temporal": await temporal.healthy(), "events": events.connected}
    body = HealthOut(status="ok" if all(checks.values()) else "degraded", checks=checks)
    if not database:
        return JSONResponse(body.model_dump(), status_code=503)
    return body
