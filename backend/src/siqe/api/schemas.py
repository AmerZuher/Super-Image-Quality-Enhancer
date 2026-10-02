"""Response models. These define the OpenAPI schema the frontend client is generated from."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

JobStateName = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class JobOut(BaseModel):
    id: str
    kind: str
    title: str
    state: JobStateName
    progress: float = Field(ge=0, le=1)
    message: str
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class WorkerOut(BaseModel):
    id: str
    kind: Literal["cpu", "gpu"]
    hostname: str
    version: str
    online: bool
    last_seen: datetime
    started_at: datetime
    info: dict[str, Any]


class ServicesOut(BaseModel):
    database: bool
    temporal: bool
    events: bool


class SystemOut(BaseModel):
    version: str
    environment: str
    services: ServicesOut
    api: dict[str, Any]
    workers: list[WorkerOut]


class ReleaseOut(BaseModel):
    tag: str
    version: str
    name: str
    notes: str = Field(description="Release notes in GitHub-flavoured Markdown.")
    url: str
    published_at: datetime | None
    prerelease: bool


class UpdateStatusOut(BaseModel):
    current_version: str
    latest_version: str | None
    update_available: bool
    newer: list[ReleaseOut] = Field(description="Releases newer than the running version, newest first.")
    current: ReleaseOut | None = Field(description="Release notes for the running version, if published.")
    checked_at: datetime | None
    error: str | None
    repo_url: str
    releases_url: str


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, bool] = {}


AssetStatusName = Literal["processing", "ready", "failed"]


class AssetOut(BaseModel):
    id: str
    original_name: str
    format: str
    width: int = Field(description="Width after EXIF orientation.")
    height: int
    bit_depth: int
    has_alpha: bool
    size_bytes: int
    status: AssetStatusName
    error: dict[str, Any] | None
    exif: dict[str, Any]
    has_gps: bool
    preview_width: int | None
    preview_height: int | None
    edits: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None
    thumb_url: str | None
    preview_url: str | None
    dzi_url: str | None
    original_url: str
    parent_id: str | None = Field(default=None, description="The image this one was made from by an AI run.")
    derivation: dict[str, Any] | None = Field(default=None, description="How an AI result was made.")


class UploadOut(BaseModel):
    asset: AssetOut
    duplicate: bool = Field(description="True when this exact file was already in the library.")
    job: JobOut | None


class CropIn(BaseModel):
    x: float
    y: float
    w: float
    h: float


class GeometryIn(BaseModel):
    rotate: Literal[0, 90, 180, 270] = 0
    flip_h: bool = False
    flip_v: bool = False
    crop: CropIn | None = None


class OpEntryIn(BaseModel):
    id: str
    enabled: bool = True
    params: dict[str, float] = Field(default_factory=dict)


class EditDocumentIn(BaseModel):
    """Validated against the operation catalog on save; see GET /api/ops."""

    version: Literal[1] = 1
    geometry: GeometryIn = Field(default_factory=GeometryIn)
    ops: list[OpEntryIn] = Field(default_factory=list)


class OpParamOut(BaseModel):
    name: str
    label: str
    min: float
    max: float
    step: float
    default: float
    unit: str


class OpOut(BaseModel):
    id: str
    label: str
    group: Literal["light", "color", "detail", "effects"]
    description: str
    params: list[OpParamOut]


class OutputFormatOut(BaseModel):
    id: Literal["jpeg", "png", "webp", "avif", "tiff"]
    label: str
    extension: str
    max_side: int
    lossy: bool
    alpha: bool
    sixteen_bit: bool


class CatalogOut(BaseModel):
    ops: list[OpOut]
    formats: list[OutputFormatOut]
    max_input_megapixels: int
    max_upload_mb: int
    accepted_extensions: str


class ExportIn(BaseModel):
    format: Literal["jpeg", "png", "webp", "avif", "tiff"] = "jpeg"
    quality: int = Field(default=90, ge=1, le=100)
    max_side: int | None = Field(default=None, ge=16, le=200_000)
    target_kb: int | None = Field(default=None, ge=10, le=2_000_000)
    strip_metadata: bool = True


RenditionStatusName = Literal["pending", "ready", "failed"]


class RenditionOut(BaseModel):
    id: str
    asset_id: str
    job_id: str | None
    status: RenditionStatusName
    format: str
    filename: str
    options: dict[str, Any]
    width: int | None
    height: int | None
    size_bytes: int | None
    quality: int | None
    created_at: datetime | None
    download_url: str | None


class ExportStartOut(BaseModel):
    job: JobOut
    rendition: RenditionOut


ModelStatusName = Literal["available", "downloading", "installed", "failed"]
ModelTask = Literal["upscale", "denoise", "background", "face"]


class ModelOut(BaseModel):
    id: str
    name: str
    task: ModelTask
    task_label: str
    arch: str
    scale: int
    summary: str
    license: str
    license_url: str
    homepage: str
    size_bytes: int
    channels: Literal["rgb", "y"]
    speed: Literal["fast", "balanced", "slow"]
    recommended: bool
    tags: list[str]
    status: ModelStatusName
    job_id: str | None
    error: dict[str, Any] | None
    installed_at: str | None
    runs: int
    calibrated: list[str] = Field(description="Devices this model has measured its memory use on.")


class ModelInstallOut(BaseModel):
    model: ModelOut
    job: JobOut | None = Field(description="The download job; null when the model was already installed.")


class AiRunIn(BaseModel):
    asset_id: str
    model_id: str
    device: Literal["auto", "cpu"] = Field(
        default="auto", description="`cpu` forces the CPU even with a GPU."
    )


class AiPlanOut(BaseModel):
    model_id: str
    task: ModelTask
    scale: int
    device: Literal["cuda", "cpu"]
    device_name: str
    input_width: int
    input_height: int
    output_width: int
    output_height: int
    output_megapixels: float
    bit_depth: int
    has_alpha: bool
    tile: int | None
    batch: int | None
    tiles: int
    calibrated: bool = Field(description="True when the tile size comes from memory measured on this GPU.")
    estimated_memory_bytes: float | None
    disk_bytes: int
    warnings: list[str]


class AiRunStartOut(BaseModel):
    job: JobOut
    plan: AiPlanOut
