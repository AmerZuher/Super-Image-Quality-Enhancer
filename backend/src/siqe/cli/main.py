"""The ``siqe`` command. Container entrypoints are thin wrappers around these commands."""

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import typer

from siqe.core.config import get_settings
from siqe.core.logging import configure_logging, get_logger

if TYPE_CHECKING:
    from siqe.cli.client import Client

app = typer.Typer(help="SIQE Studio command-line tools.", no_args_is_help=True, add_completion=False)
keys_app = typer.Typer(
    help="Manage API keys (run where the app runs: `docker compose exec api siqe keys ...`)."
)
flows_app = typer.Typer(help="Flows in a running SIQE Studio.")
app.add_typer(keys_app, name="keys", no_args_is_help=True)
app.add_typer(flows_app, name="flows", no_args_is_help=True)
log = get_logger("siqe.cli")

UrlOption = Annotated[str, typer.Option(envvar="SIQE_URL", help="Address of SIQE Studio.", show_default=True)]
KeyOption = Annotated[
    str | None,
    typer.Option(envvar="SIQE_API_KEY", help="API key, when the app asks for one.", show_default=False),
]


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


# --------------------------------------------------------------------------- API keys


@keys_app.command("create")
def keys_create(name: Annotated[str, typer.Argument(help="What the key is for, e.g. 'laptop'.")]) -> None:
    """Create a key and print it. It is shown only once."""
    from siqe.auth.keys import create_key
    from siqe.db.session import dispose_engine, session_scope

    async def _create() -> str:
        try:
            async with session_scope() as session:
                _, secret = await create_key(session, name)
                await session.commit()
                return secret
        finally:
            await dispose_engine()

    secret = asyncio.run(_create())
    typer.echo(secret)
    typer.echo("Keep this key somewhere safe: it won't be shown again.", err=True)


@keys_app.command("list")
def keys_list() -> None:
    """List keys (never the keys themselves)."""
    from sqlalchemy import select

    from siqe.db.models import ApiKey
    from siqe.db.session import dispose_engine, session_scope

    async def _list() -> list[ApiKey]:
        try:
            async with session_scope() as session:
                return list((await session.execute(select(ApiKey).order_by(ApiKey.created_at))).scalars())
        finally:
            await dispose_engine()

    for key in asyncio.run(_list()):
        state = "revoked" if key.revoked_at else "active"
        used = key.last_used_at.strftime("%Y-%m-%d %H:%M") if key.last_used_at else "never used"
        typer.echo(f"{key.prefix}…  {state:<8} {used:<16}  {key.name}")


@keys_app.command("revoke")
def keys_revoke(
    prefix: Annotated[str, typer.Argument(help="The start of the key, as `siqe keys list` shows it.")],
) -> None:
    """Revoke a key; anything using it stops working within a minute."""
    from sqlalchemy import select

    from siqe.db.base import utcnow
    from siqe.db.models import ApiKey
    from siqe.db.session import dispose_engine, session_scope

    async def _revoke() -> int:
        try:
            async with session_scope() as session:
                keys = list(
                    (
                        await session.execute(
                            select(ApiKey).where(
                                ApiKey.prefix.startswith(prefix), ApiKey.revoked_at.is_(None)
                            )
                        )
                    ).scalars()
                )
                if len(keys) == 1:
                    keys[0].revoked_at = utcnow()
                    await session.commit()
                return len(keys)
        finally:
            await dispose_engine()

    count = asyncio.run(_revoke())
    if count != 1:
        _fail(
            "No active key starts with that." if count == 0 else "More than one key starts with that.",
            "Use more of the key's start, as `siqe keys list` shows it.",
        )
    typer.echo("Revoked.")


# ----------------------------------------------------------- talking to a running app


def _fail(message: str, fix: str | None = None, code: int = 1) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    if fix:
        typer.echo(fix, err=True)
    raise typer.Exit(code)


@contextmanager
def _client(url: str, key: str | None) -> Iterator["Client"]:
    from siqe.cli.client import Client, ClientError

    client = Client(url, key)
    try:
        yield client
    except ClientError as exc:
        _fail(exc.message, exc.fix)
    finally:
        client.close()


@flows_app.command("list")
def flows_list(url: UrlOption = "http://localhost:8080", key: KeyOption = None) -> None:
    """List flows: name, whether it can run, and its id."""
    with _client(url, key) as client:
        for flow in client.flows():
            ready = "ready" if not flow["problems"] else "needs fixing"
            watch = f"  watches '{flow['watch_folder'] or '/'}'" if flow["watch_enabled"] else ""
            typer.echo(f"{flow['name']:<32} {ready:<13} {flow['id']}{watch}")


@app.command()
def upload(
    paths: Annotated[list[Path], typer.Argument(help="Images, or folders of images.")],
    url: UrlOption = "http://localhost:8080",
    key: KeyOption = None,
) -> None:
    """Add images to the Library."""
    from siqe.cli.client import image_files

    with _client(url, key) as client:
        files = image_files(paths)
        if not files:
            _fail("No images found there.")

        def _shown(path: Path, body: dict[str, object]) -> None:
            typer.echo(f"{'already there' if body['duplicate'] else 'added':<14} {path}")

        client.upload(files, _shown)


@app.command()
def run(
    flow: Annotated[str, typer.Argument(help="A flow's name or id, or a .flow.json file.")],
    paths: Annotated[
        list[Path] | None, typer.Argument(help="Images or folders to upload and run on.")
    ] = None,
    album: Annotated[str | None, typer.Option(help="Run on an album (name or id) instead of files.")] = None,
    all_images: Annotated[bool, typer.Option("--all", help="Run on every image in the Library.")] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Try it on 10 images without changing the Library.")
    ] = False,
    limit: Annotated[int | None, typer.Option(help="Use at most this many images.")] = None,
    wait: Annotated[bool, typer.Option(help="Wait for the run to finish and show what happened.")] = True,
    download: Annotated[Path | None, typer.Option(help="Save the exported files to this folder.")] = None,
    url: UrlOption = "http://localhost:8080",
    key: KeyOption = None,
) -> None:
    """Run a flow on images: files you name (uploaded first), an album, or the whole Library."""
    from siqe.cli.client import image_files

    chosen = sum(bool(x) for x in (paths, album, all_images))
    if chosen != 1:
        _fail("Choose what to run on: some files, --album NAME, or --all.")
    with _client(url, key) as client:
        target = client.resolve_flow(flow)
        source: dict[str, object]
        if paths:
            files = image_files(paths)
            if not files:
                _fail("No images found there.")
            typer.echo(f"Uploading {len(files)} image{'s' if len(files) != 1 else ''}…", err=True)
            ids = client.upload(files)
            ready, failed = client.wait_ready(ids)
            if failed:
                typer.secho(
                    f"{len(failed)} file(s) couldn't be read and are left out.",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
            source = {"kind": "assets", "asset_ids": list(dict.fromkeys(ready))}
        elif album:
            source = {"kind": "album", "album_id": client.resolve_album(album)}
        else:
            source = {"kind": "all"}
        started = client.start_run(target["id"], source, dry_run=dry_run, limit=limit)
        typer.echo(
            f"Started {'a dry run of ' if dry_run else ''}{target['name']} on {started['total']} image(s).",
            err=True,
        )
        if not wait:
            typer.echo(started["id"])
            return
        last = ""
        result = None
        for result in client.follow(started["id"]):
            r = result.run
            line = f"{r['done'] + r['failed'] + r['skipped']}/{r['total']} finished"
            if r["failed"]:
                line += f", {r['failed']} failed"
            if line != last:
                typer.echo(line, err=True)
                last = line
        assert result is not None
        for item in result.items:
            if item["state"] == "failed" and item.get("error"):
                typer.secho(
                    f"  {item['name']}: {item['error'].get('message')}", fg=typer.colors.RED, err=True
                )
        r = result.run
        typer.echo(
            f"{r['state'].capitalize()}: {r['done']} done, {r['skipped']} skipped, {r['failed']} failed."
        )
        if download and r["done"]:
            saved = client.download(started["id"], download)
            typer.echo(f"Saved {len(saved)} file(s) to {download}.")
        if r["state"] != "succeeded" or r["failed"]:
            raise typer.Exit(2)


if __name__ == "__main__":
    app()
