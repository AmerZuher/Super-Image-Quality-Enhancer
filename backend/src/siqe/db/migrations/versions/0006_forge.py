"""Forge: model projects, datasets, training runs and their metrics; Forge models in AI Lab.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _state() -> sa.Column[Any]:
    return sa.Column("state", postgresql.ENUM(name="job_state", create_type=False), nullable=False)


def _job() -> list[Any]:
    return [sa.Column("job_id", sa.UUID(), nullable=True)]


def upgrade() -> None:
    op.add_column("ai_models", sa.Column("source", sa.String(16), nullable=False, server_default="catalog"))
    op.add_column("ai_models", sa.Column("spec", postgresql.JSONB(), nullable=True))

    op.create_table(
        "forge_projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("graph", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("template", sa.String(64), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_forge_projects"),
    )
    op.create_table(
        "forge_datasets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("degradation", postgresql.JSONB(), nullable=False, server_default="{}"),
        _state(),
        *_job(),
        sa.Column("images", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("train_crops", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("val_crops", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_forge_datasets"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_forge_datasets_job_id_jobs", ondelete="SET NULL"
        ),
    )
    op.create_table(
        "forge_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("project_name", sa.String(120), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=True),
        *_job(),
        sa.Column("graph", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("plan", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("scale", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("color", sa.String(8), nullable=False, server_default="rgb"),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        _state(),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("batch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accumulate", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("device", sa.String(80), nullable=False, server_default=""),
        sa.Column("last_loss", sa.Float(), nullable=True),
        sa.Column("best_psnr", sa.Float(), nullable=True),
        sa.Column("best_ssim", sa.Float(), nullable=True),
        sa.Column("best_step", sa.Integer(), nullable=True),
        sa.Column("bicubic_psnr", sa.Float(), nullable=True),
        sa.Column("notes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_forge_runs"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["forge_projects.id"],
            name="fk_forge_runs_project_id_forge_projects",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["forge_datasets.id"],
            name="fk_forge_runs_dataset_id_forge_datasets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_forge_runs_job_id_jobs", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_forge_runs_project_id", "forge_runs", ["project_id"])
    op.create_table(
        "forge_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("loss", sa.Float(), nullable=True),
        sa.Column("psnr", sa.Float(), nullable=True),
        sa.Column("ssim", sa.Float(), nullable=True),
        sa.Column("lr", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_forge_metrics"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["forge_runs.id"], name="fk_forge_metrics_run_id_forge_runs", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_forge_metrics_run_id", "forge_metrics", ["run_id", "step"])


def downgrade() -> None:
    op.drop_index("ix_forge_metrics_run_id", table_name="forge_metrics")
    op.drop_table("forge_metrics")
    op.drop_index("ix_forge_runs_project_id", table_name="forge_runs")
    op.drop_table("forge_runs")
    op.drop_table("forge_datasets")
    op.drop_table("forge_projects")
    op.drop_column("ai_models", "spec")
    op.drop_column("ai_models", "source")
