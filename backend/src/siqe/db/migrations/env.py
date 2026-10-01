import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from siqe.core.config import get_settings
from siqe.db import models  # noqa: F401  (registers tables on the metadata)
from siqe.db.base import Base

target_metadata = Base.metadata


def _url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        # Serialise concurrent `siqe init` runs (two containers starting at once).
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(7363213)")
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
