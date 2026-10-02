"""AI model registry state, and AI results as images derived from another image.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_STATUS = ("downloading", "installed", "failed")


def upgrade() -> None:
    postgresql.ENUM(*MODEL_STATUS, name="model_status").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "ai_models",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column(
            "status", postgresql.ENUM(*MODEL_STATUS, name="model_status", create_type=False), nullable=False
        ),
        sa.Column("bytes_done", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("bytes_total", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calibration", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ai_models"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_ai_models_job_id_jobs", ondelete="SET NULL"
        ),
    )
    op.add_column("assets", sa.Column("parent_id", sa.UUID(), nullable=True))
    op.add_column("assets", sa.Column("derivation", postgresql.JSONB(), nullable=True))
    op.create_foreign_key(
        "fk_assets_parent_id_assets", "assets", "assets", ["parent_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_assets_parent_id", "assets", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_assets_parent_id", table_name="assets")
    op.drop_constraint("fk_assets_parent_id_assets", "assets", type_="foreignkey")
    op.drop_column("assets", "derivation")
    op.drop_column("assets", "parent_id")
    op.drop_table("ai_models")
    postgresql.ENUM(name="model_status").drop(op.get_bind(), checkfirst=True)
