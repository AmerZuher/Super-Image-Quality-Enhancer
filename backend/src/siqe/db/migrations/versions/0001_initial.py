"""Initial schema: jobs, worker heartbeats, app settings; pgvector extension.

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_STATES = ("queued", "running", "succeeded", "failed", "cancelled")


def upgrade() -> None:
    # Used from Phase 3 (similar-image search); enabling it now keeps later migrations simple.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    job_state = postgresql.ENUM(*JOB_STATES, name="job_state")
    job_state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(*JOB_STATES, name="job_state", create_type=False),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("workflow_id", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.UniqueConstraint("workflow_id", name="uq_jobs_workflow_id"),
    )
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_state", "jobs", ["state"])
    op.create_index("ix_jobs_created_at", "jobs", [sa.text("created_at DESC")])

    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("info", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_worker_heartbeats"),
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_app_settings"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("worker_heartbeats")
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_state", table_name="jobs")
    op.drop_index("ix_jobs_kind", table_name="jobs")
    op.drop_table("jobs")
    postgresql.ENUM(name="job_state").drop(op.get_bind(), checkfirst=True)
