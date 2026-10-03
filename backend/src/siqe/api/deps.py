from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.core.config import Settings
from siqe.db.session import get_session
from siqe.events.bus import EventHub
from siqe.orchestration.client import TemporalGateway


def settings_dep(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def temporal_dep(request: Request) -> TemporalGateway:
    return request.app.state.temporal  # type: ignore[no-any-return]


def events_dep(request: Request) -> EventHub:
    return request.app.state.events  # type: ignore[no-any-return]


# scope="function": commit before the response is sent, so a client that writes and then reads
# always sees its change, and a failed commit is an error response instead of a lost write.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
TemporalDep = Annotated[TemporalGateway, Depends(temporal_dep)]
EventsDep = Annotated[EventHub, Depends(events_dep)]
