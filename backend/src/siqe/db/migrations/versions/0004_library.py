"""Library: per-image analysis, embeddings, tags, quarantine, albums and the import folder.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALBUM_KIND = ("manual", "smart")
IMPORT_STATE = ("waiting", "imported", "duplicate", "failed")

# Starter smart albums (a copy of siqe.library.rules.DEFAULT_ALBUMS as of this revision).
STARTER_ALBUMS = [
    (
        "Desktop wallpapers",
        [
            {"field": "orientation", "op": "is", "value": "landscape"},
            {"field": "width", "op": "gte", "value": 1920},
        ],
        "all",
    ),
    (
        "Phone wallpapers",
        [
            {"field": "orientation", "op": "is", "value": "portrait"},
            {"field": "aspect", "op": "lte", "value": 0.6},
            {"field": "height", "op": "gte", "value": 1600},
        ],
        "all",
    ),
    (
        "Needs enhancing",
        [{"field": "width", "op": "lte", "value": 1000}, {"field": "sharpness", "op": "lte", "value": 0.3}],
        "any",
    ),
    ("Has location", [{"field": "has_gps", "op": "is", "value": True}], "all"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    add = op.add_column
    add("assets", sa.Column("analysis_version", sa.Integer(), nullable=False, server_default="0"))
    add("assets", sa.Column("phash", sa.BigInteger(), nullable=True))
    add("assets", sa.Column("dhash", sa.BigInteger(), nullable=True))
    add("assets", sa.Column("sharpness", sa.Float(), nullable=True))
    add("assets", sa.Column("color", sa.String(16), nullable=True))
    add("assets", sa.Column("color_hex", sa.String(7), nullable=True))
    add("assets", sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True))
    add("assets", sa.Column("gps_lat", sa.Float(), nullable=True))
    add("assets", sa.Column("gps_lon", sa.Float(), nullable=True))
    add("assets", sa.Column("embedding", Vector(512), nullable=True))
    add("assets", sa.Column("embedding_model", sa.String(64), nullable=True))
    add(
        "assets",
        sa.Column("tags", postgresql.ARRAY(sa.String(64)), nullable=False, server_default="{}"),
    )
    add(
        "assets",
        sa.Column("auto_tags", postgresql.ARRAY(sa.String(64)), nullable=False, server_default="{}"),
    )
    add("assets", sa.Column("duplicate_group", sa.UUID(), nullable=True))
    add("assets", sa.Column("duplicate_rank", sa.Integer(), nullable=True))
    add("assets", sa.Column("duplicate_ok", sa.Boolean(), nullable=False, server_default="false"))
    add("assets", sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True))
    add("assets", sa.Column("quarantine_reason", sa.String(200), nullable=True))
    add("assets", sa.Column("source", postgresql.JSONB(), nullable=True))
    op.create_index("ix_assets_taken_at", "assets", ["taken_at"])
    op.create_index("ix_assets_duplicate_group", "assets", ["duplicate_group"])
    op.create_index("ix_assets_quarantined_at", "assets", ["quarantined_at"])
    op.create_index("ix_assets_tags", "assets", ["tags"], postgresql_using="gin")
    op.create_index("ix_assets_auto_tags", "assets", ["auto_tags"], postgresql_using="gin")
    op.create_index(
        "ix_assets_embedding",
        "assets",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_ip_ops"},
    )

    postgresql.ENUM(*ALBUM_KIND, name="album_kind").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "albums",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", postgresql.ENUM(*ALBUM_KIND, name="album_kind", create_type=False), nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_albums"),
    )
    op.create_table(
        "album_assets",
        sa.Column("album_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("album_id", "asset_id", name="pk_album_assets"),
        sa.ForeignKeyConstraint(
            ["album_id"], ["albums.id"], name="fk_album_assets_album_id_albums", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name="fk_album_assets_asset_id_assets", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_album_assets_asset_id", "album_assets", ["asset_id"])
    albums = sa.table(
        "albums",
        sa.column("id", sa.UUID()),
        sa.column("name", sa.String()),
        sa.column("kind", postgresql.ENUM(*ALBUM_KIND, name="album_kind", create_type=False)),
        sa.column("rules", postgresql.JSONB()),
        sa.column("position", sa.Integer()),
    )
    op.bulk_insert(
        albums,
        [
            {
                "id": uuid.uuid4(),
                "name": name,
                "kind": "smart",
                "rules": {"match": match, "rules": rules},
                "position": i,
            }
            for i, (name, rules, match) in enumerate(STARTER_ALBUMS)
        ],
    )

    postgresql.ENUM(*IMPORT_STATE, name="import_state").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "import_files",
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mtime", sa.Float(), nullable=False),
        sa.Column(
            "state", postgresql.ENUM(*IMPORT_STATE, name="import_state", create_type=False), nullable=False
        ),
        sa.Column("asset_id", sa.UUID(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("path", name="pk_import_files"),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name="fk_import_files_asset_id_assets", ondelete="SET NULL"
        ),
    )


def downgrade() -> None:
    op.drop_table("import_files")
    postgresql.ENUM(name="import_state").drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_album_assets_asset_id", table_name="album_assets")
    op.drop_table("album_assets")
    op.drop_table("albums")
    postgresql.ENUM(name="album_kind").drop(op.get_bind(), checkfirst=True)
    for index in (
        "ix_assets_embedding",
        "ix_assets_auto_tags",
        "ix_assets_tags",
        "ix_assets_quarantined_at",
        "ix_assets_duplicate_group",
        "ix_assets_taken_at",
    ):
        op.drop_index(index, table_name="assets")
    for column in (
        "source",
        "quarantine_reason",
        "quarantined_at",
        "duplicate_ok",
        "duplicate_rank",
        "duplicate_group",
        "auto_tags",
        "tags",
        "embedding_model",
        "embedding",
        "gps_lon",
        "gps_lat",
        "taken_at",
        "color_hex",
        "color",
        "sharpness",
        "dhash",
        "phash",
        "analysis_version",
    ):
        op.drop_column("assets", column)
