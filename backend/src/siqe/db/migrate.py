"""Run Alembic migrations programmatically (used by ``siqe init``)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from siqe.core.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    return cfg


def upgrade_to_head(database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), "head")
