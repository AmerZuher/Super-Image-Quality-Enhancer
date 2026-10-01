"""Assets with non-destructive edits, and export renditions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ASSET_STATUS = ("processing", "ready", "failed")
RENDITION_STATUS = ("pending", "ready", "failed")


def upgrade() -> None:
    postgresql.ENUM(*ASSET_STATUS, name="asset_status").create(op.get_bind(), checkfirst=True)
    postgresql.ENUM(*RENDITION_STATUS, name="rendition_status").create(op.get_bind(), checkfirst=True)

    op.create_table(
        "assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(16), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("bit_depth", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("has_alpha", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*ASSET_STATUS, name="asset_status", create_type=False),
            nullable=False,
            server_default="processing",
        ),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("exif", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("has_gps", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("preview_width", sa.Integer(), nullable=True),
        sa.Column("preview_height", sa.Integer(), nullable=True),
        sa.Column("edits", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("edits_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
        sa.UniqueConstraint("sha256", name="uq_assets_sha256"),
    )
    op.create_index("ix_assets_created_at", "assets", [sa.text("created_at DESC")])

    op.create_table(
        "renditions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(*RENDITION_STATUS, name="rendition_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("edits", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("quality", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_renditions"),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name="fk_renditions_asset_id_assets", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_renditions_job_id_jobs", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_renditions_asset_id", "renditions", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_renditions_asset_id", table_name="renditions")
    op.drop_table("renditions")
    op.drop_index("ix_assets_created_at", table_name="assets")
    op.drop_table("assets")
    postgresql.ENUM(name="rendition_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="asset_status").drop(op.get_bind(), checkfirst=True)
