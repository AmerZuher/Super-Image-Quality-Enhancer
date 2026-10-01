from fastapi import APIRouter, Query

from siqe.api.deps import SessionDep, SettingsDep
from siqe.api.schemas import UpdateStatusOut
from siqe.updates import service

router = APIRouter(prefix="/updates", tags=["updates"])


@router.get("", response_model=UpdateStatusOut, summary="Running version, newer releases and their notes")
async def update_status(
    session: SessionDep,
    settings: SettingsDep,
    refresh: bool = Query(False, description="Ask GitHub now instead of using the cached list."),
) -> UpdateStatusOut:
    return UpdateStatusOut.model_validate(await service.check(session, settings, force=refresh))
