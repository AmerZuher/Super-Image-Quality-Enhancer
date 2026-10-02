"""Flows, their runs and per-image results, API keys, and face counts on assets.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_KIND = ("manual", "watch", "api")
ITEM_STATE = ("pending", "running", "done", "failed", "skipped")


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("assets", sa.Column("faces", sa.Integer(), nullable=True))

    op.create_table(
        "flows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("document", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("watch_folder", sa.String(300), nullable=True),
        sa.Column("watch_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("recipe", sa.String(64), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_flows"),
    )

    postgresql.ENUM(*RUN_KIND, name="run_kind").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "flow_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("flow_id", sa.UUID(), nullable=True),
        sa.Column("flow_name", sa.String(120), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("kind", postgresql.ENUM(*RUN_KIND, name="run_kind", create_type=False), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("document", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("state", postgresql.ENUM(name="job_state", create_type=False), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_dir", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_flow_runs"),
        sa.ForeignKeyConstraint(
            ["flow_id"], ["flows.id"], name="fk_flow_runs_flow_id_flows", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_flow_runs_job_id_jobs", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_flow_runs_flow_id", "flow_runs", ["flow_id"])

    postgresql.ENUM(*ITEM_STATE, name="item_state").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "flow_run_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "state", postgresql.ENUM(*ITEM_STATE, name="item_state", create_type=False), nullable=False
        ),
        sa.Column("steps", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("outputs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_flow_run_items"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["flow_runs.id"], name="fk_flow_run_items_run_id_flow_runs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name="fk_flow_run_items_asset_id_assets", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_flow_run_items_run_id", "flow_run_items", ["run_id"])
    op.create_index("ix_flow_run_items_run_state", "flow_run_items", ["run_id", "state", "position"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("hash", name="uq_api_keys_hash"),
    )
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_prefix", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ix_flow_run_items_run_state", table_name="flow_run_items")
    op.drop_index("ix_flow_run_items_run_id", table_name="flow_run_items")
    op.drop_table("flow_run_items")
    postgresql.ENUM(name="item_state").drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_flow_runs_flow_id", table_name="flow_runs")
    op.drop_table("flow_runs")
    postgresql.ENUM(name="run_kind").drop(op.get_bind(), checkfirst=True)
    op.drop_table("flows")
    op.drop_column("assets", "faces")
