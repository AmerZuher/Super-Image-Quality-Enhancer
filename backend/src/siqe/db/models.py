"""ORM models. Schema changes go through new Alembic migrations in ``siqe/db/migrations``."""

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from siqe.db.base import Base, TimestampMixin, utcnow


class JobState(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def is_final(self) -> bool:
        return self in (JobState.succeeded, JobState.failed, JobState.cancelled)


class Job(TimestampMixin, Base):
    """A unit of user-visible work. Temporal runs it; this row is what the UI shows."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, name="job_state", values_callable=lambda e: [m.value for m in e]),
        default=JobState.queued,
        index=True,
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkerHeartbeat(Base):
    """Last known state of each worker process, refreshed every few seconds."""

    __tablename__ = "worker_heartbeats"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    hostname: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(64))
    info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )


class AppSetting(Base):
    """Small key/value store for settings and caches (for example the release cache)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )


class AssetStatus(enum.StrEnum):
    processing = "processing"
    ready = "ready"
    failed = "failed"


def _enum(cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class Asset(TimestampMixin, Base):
    """An uploaded image. The original file is immutable and stored once per content hash."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(16))
    format: Mapped[str] = mapped_column(String(16))
    width: Mapped[int] = mapped_column(Integer)  # after EXIF orientation
    height: Mapped[int] = mapped_column(Integer)
    bit_depth: Mapped[int] = mapped_column(Integer, default=8)
    has_alpha: Mapped[bool] = mapped_column(Boolean, default=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[AssetStatus] = mapped_column(
        _enum(AssetStatus, "asset_status"), default=AssetStatus.processing
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    exif: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    has_gps: Mapped[bool] = mapped_column(Boolean, default=False)
    preview_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    edits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    edits_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when this image was made from another one by an AI run.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    derivation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Library analysis (siqe.library.analysis); analysis_version 0 means not analysed yet.
    analysis_version: Mapped[int] = mapped_column(Integer, default=0)
    phash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dhash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sharpness: Mapped[float | None] = mapped_column(Float, nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding: Mapped[Any] = mapped_column(Vector(512), nullable=True, deferred=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    auto_tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    # Near-duplicates share a group; rank 0 is the copy worth keeping.
    duplicate_group: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    duplicate_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The user said this image isn't a duplicate of the others it was grouped with.
    duplicate_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    # Quarantined images are hidden everywhere except the Quarantine view, until restored or deleted.
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Faces found by RetinaFace (GPU queue); None until counted.
    faces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Where the file came from, e.g. {"kind": "folder", "path": "Trips/2024/a.jpg"}.
    source: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class RenditionStatus(enum.StrEnum):
    pending = "pending"
    ready = "ready"
    failed = "failed"


class Rendition(Base):
    """An exported file: an asset rendered with a snapshot of its edits and export options."""

    __tablename__ = "renditions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[RenditionStatus] = mapped_column(
        _enum(RenditionStatus, "rendition_status"), default=RenditionStatus.pending
    )
    format: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(255))
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    edits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )


class ModelStatus(enum.StrEnum):
    downloading = "downloading"
    installed = "installed"
    failed = "failed"


class AiModel(TimestampMixin, Base):
    """Install state of a catalog model (siqe.ai.manifest) and what was learned running it."""

    __tablename__ = "ai_models"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[ModelStatus] = mapped_column(_enum(ModelStatus, "model_status"))
    bytes_done: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_total: Mapped[int] = mapped_column(BigInteger, default=0)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Per device ("cuda:<name>" or "cpu"): memory line from siqe.ai.governor.Calibration.
    calibration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Per device: the tile and batch that last worked, after any fallback.
    last_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    # "catalog" for siqe.ai.manifest models; "forge" for models you trained and published.
    source: Mapped[str] = mapped_column(String(16), default="catalog")
    # For Forge models: the ModelSpec fields, the graph's plan and the benchmark.
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class AlbumKind(enum.StrEnum):
    manual = "manual"
    smart = "smart"


class Album(TimestampMixin, Base):
    """A view of the library: hand-picked images, or every image matching rules (no copies)."""

    __tablename__ = "albums"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[AlbumKind] = mapped_column(_enum(AlbumKind, "album_kind"))
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)


class AlbumAsset(Base):
    __tablename__ = "album_assets"

    album_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )


class ImportState(enum.StrEnum):
    waiting = "waiting"  # seen once; imported when its size and time stop changing
    imported = "imported"
    duplicate = "duplicate"
    failed = "failed"


class ImportFile(TimestampMixin, Base):
    """A file seen in the import folder, so each one is imported once and half-copied files wait."""

    __tablename__ = "import_files"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mtime: Mapped[float] = mapped_column(Float)
    state: Mapped[ImportState] = mapped_column(_enum(ImportState, "import_state"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class Flow(TimestampMixin, Base):
    """A saved pipeline: a flow document, and optionally a folder it watches."""

    __tablename__ = "flows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Run on images imported into this subfolder of the import folder ("" means all of it).
    watch_folder: Mapped[str | None] = mapped_column(String(300), nullable=True)
    watch_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    recipe: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RunKind(enum.StrEnum):
    manual = "manual"
    watch = "watch"
    api = "api"


class FlowRun(TimestampMixin, Base):
    """One run of a flow over a set of images. The document is a snapshot taken at the start."""

    __tablename__ = "flow_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    flow_name: Mapped[str] = mapped_column(String(120))
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[RunKind] = mapped_column(_enum(RunKind, "run_kind"))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, name="job_state", values_callable=lambda e: [m.value for m in e], create_type=False),
        default=JobState.queued,
    )
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    output_dir: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ItemState(enum.StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class FlowRunItem(Base):
    """One image in a run: what happened to it at each step, and what it produced."""

    __tablename__ = "flow_run_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[ItemState] = mapped_column(_enum(ItemState, "item_state"), default=ItemState.pending)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    outputs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(Base):
    """A key for scripts and the siqe CLI. Only a SHA-256 of the secret is stored."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


_JOB_STATE = Enum(
    JobState, name="job_state", values_callable=lambda e: [m.value for m in e], create_type=False
)


class ForgeProject(TimestampMixin, Base):
    """A model you are designing: its graph of blocks."""

    __tablename__ = "forge_projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    template: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ForgeDataset(TimestampMixin, Base):
    """High-resolution crops taken from Library images, plus how to damage them for training."""

    __tablename__ = "forge_datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    source: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    degradation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    state: Mapped[JobState] = mapped_column(_JOB_STATE, default=JobState.queued)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    images: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    train_crops: Mapped[int] = mapped_column(Integer, default=0)
    val_crops: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class ForgeRun(TimestampMixin, Base):
    """One training run: a snapshot of the graph, the settings, and where it has got to."""

    __tablename__ = "forge_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forge_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_name: Mapped[str] = mapped_column(String(120))
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forge_datasets.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    scale: Mapped[int] = mapped_column(Integer, default=1)
    color: Mapped[str] = mapped_column(String(8), default="rgb")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    state: Mapped[JobState] = mapped_column(_JOB_STATE, default=JobState.queued)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    step: Mapped[int] = mapped_column(Integer, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    batch: Mapped[int] = mapped_column(Integer, default=0)
    accumulate: Mapped[int] = mapped_column(Integer, default=1)
    device: Mapped[str] = mapped_column(String(80), default="")
    last_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_psnr: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ssim: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bicubic_psnr: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The last ONNX export of the best checkpoint (siqe.forge.onnx_export): step, size, checks.
    onnx_export: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ForgeMetric(Base):
    """A point on a run's charts: training loss, or a validation score."""

    __tablename__ = "forge_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forge_runs.id", ondelete="CASCADE")
    )  # indexed with step: ix_forge_metrics_run_id
    step: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))  # "train" or "val"
    loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    psnr: Mapped[float | None] = mapped_column(Float, nullable=True)
    ssim: Mapped[float | None] = mapped_column(Float, nullable=True)
    lr: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
