"""The ``siqe`` command. Container entrypoints are thin wrappers around these commands."""

import asyncio
import json
from typing import Annotated, Literal

import typer

from siqe.core.config import get_settings
from siqe.core.logging import configure_logging, get_logger

app = typer.Typer(help="SIQE Studio command-line tools.", no_args_is_help=True, add_completion=False)
log = get_logger("siqe.cli")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(get_settings().version)


@app.command()
def init() -> None:
    """Apply database migrations and register the Temporal namespace. Safe to run repeatedly."""
    from siqe.db.migrate import upgrade_to_head
    from siqe.orchestration.client import connect, ensure_namespace

    settings = get_settings()
    configure_logging(settings)
    for sub in ("media", "models", "checkpoints", "tmp"):
        (settings.data_dir / sub).mkdir(parents=True, exist_ok=True)

    log.info("init.migrating")
    upgrade_to_head()

    async def _namespace() -> None:
        client = await connect(settings, attempts=60, namespace="default")
        await ensure_namespace(client, settings.temporal_namespace, settings.temporal_retention_days)

    log.info("init.temporal_namespace", namespace=settings.temporal_namespace)
    asyncio.run(_namespace())
    log.info("init.done")


@app.command()
def api(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "0.0.0.0",  # noqa: S104
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Reload on code changes (development).")] = False,
) -> None:
    """Run the HTTP API."""
    import uvicorn

    uvicorn.run(
        "siqe.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=None,
    )


@app.command()
def worker(kind: Annotated[str, typer.Argument(help="cpu or gpu")]) -> None:
    """Run a Temporal worker for the CPU or GPU task queue."""
    from siqe.workers.runner import run_worker

    if kind not in ("cpu", "gpu"):
        raise typer.BadParameter("kind must be 'cpu' or 'gpu'")
    selected: Literal["cpu", "gpu"] = "cpu" if kind == "cpu" else "gpu"
    asyncio.run(run_worker(selected))


@app.command()
def openapi() -> None:
    """Print the OpenAPI schema as JSON."""
    from siqe.api.app import create_app

    typer.echo(json.dumps(create_app().openapi(), indent=2))


if __name__ == "__main__":
    app()
