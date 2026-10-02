import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from siqe.api.routes import access, ai, assets, events, flows, health, jobs, library, models, system, updates
from siqe.auth.middleware import ApiKeyAuth
from siqe.core.config import get_settings
from siqe.core.errors import register_error_handlers
from siqe.core.logging import configure_logging, get_logger
from siqe.db.session import dispose_engine
from siqe.events.bus import EventHub
from siqe.library import embedder
from siqe.orchestration.client import TemporalGateway

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    hub: EventHub = app.state.events
    await hub.start()
    warm = asyncio.create_task(_warm_search())
    log.info("api.started", version=settings.version, environment=settings.environment)
    try:
        yield
    finally:
        warm.cancel()
        await hub.stop()
        await dispose_engine()


async def _warm_search() -> None:
    """Load the search model's text half in the background, so the first search is quick."""
    try:
        if embedder.installed():
            await asyncio.to_thread(embedder.query_vector, "a photo")
            log.info("library.search_ready")
    except Exception as exc:
        log.warning("library.search_warmup_failed", error=str(exc))


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(
        title="SIQE Studio API",
        version=settings.version,
        description="Enhance, edit, organise and automate images, and train the models that do it.",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.temporal = TemporalGateway(settings)
    app.state.events = EventHub(settings.sync_database_dsn)
    register_error_handlers(app)

    api = APIRouter(prefix="/api")
    for module in (health, access, system, jobs, assets, library, flows, models, ai, updates, events):
        api.include_router(module.router)
    app.include_router(api)
    app.add_middleware(ApiKeyAuth, enabled=settings.api_auth == "keys")
    return app
