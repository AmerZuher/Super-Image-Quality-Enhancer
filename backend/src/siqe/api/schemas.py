"""Response models. These define the OpenAPI schema the frontend client is generated from."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from siqe.library.rules import RuleSet

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
    tags: list[str] = Field(description="Tags you added.")
    auto_tags: list[str] = Field(description="Tags CLIP chose (Library search).")
    analysed: bool
    sharpness: float | None = Field(default=None, description="0 (blurred) to 1 (crisp).")
    faces: int | None = Field(
        default=None, description="Faces found; null until counted, -1 if the image couldn't be checked."
    )
    color: str | None = Field(default=None, description="Main colour family, or 'neutral'.")
    color_hex: str | None = None
    taken_at: datetime | None = Field(default=None, description="When the photo was taken (EXIF).")
    gps: list[float] | None = Field(default=None, description="Latitude and longitude, if recorded.")
    duplicate_group: str | None = Field(default=None, description="Near-duplicates share a group.")
    duplicate_rank: int | None = Field(default=None, description="0 is the copy worth keeping.")
    quarantined_at: datetime | None = None
    quarantine_reason: str | None = None
    source: dict[str, Any] | None = Field(default=None, description="Where the file came from.")
    score: float | None = Field(default=None, description="Search or similarity score, when searching.")


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
ModelTask = Literal["upscale", "denoise", "background", "face", "embed"]


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
    restore_faces: bool = Field(
        default=False, description="After upscaling, restore faces with GFPGAN (it must be installed)."
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
    restore_faces: bool
    warnings: list[str]


class AiRunStartOut(BaseModel):
    job: JobOut
    plan: AiPlanOut


# ------------------------------------------------------------------------------ library


class LibraryPageOut(BaseModel):
    items: list[AssetOut]
    total: int
    offset: int
    limit: int
    mode: Literal["browse", "text", "name", "similar"] = Field(
        description="How the list was made: browsing, search by description, by name only, or similar."
    )


class AlbumOut(BaseModel):
    id: str
    name: str
    kind: Literal["manual", "smart"]
    rules: RuleSet
    count: int
    position: int


class AlbumIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["manual", "smart"] = "smart"
    rules: RuleSet = Field(default_factory=RuleSet)


class AlbumPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    rules: RuleSet | None = None
    position: int | None = None


class AssetIdsIn(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=1000)


class QuarantineIn(AssetIdsIn):
    reason: str | None = Field(default=None, max_length=200)


class TagsIn(AssetIdsIn):
    add: list[str] = Field(default_factory=list, max_length=30)
    remove: list[str] = Field(default_factory=list, max_length=30)


class AlbumMembersIn(AssetIdsIn):
    action: Literal["add", "remove"] = "add"


class DuplicatesResolveIn(BaseModel):
    groups: list[str] | None = Field(
        default=None, description="Groups to resolve; leave out to resolve every group."
    )


class ChangedOut(BaseModel):
    changed: int


class TagCountOut(BaseModel):
    tag: str
    count: int


class LibraryCountsOut(BaseModel):
    all: int
    duplicates: int
    duplicate_groups: int
    quarantine: int


class LibraryStatusOut(BaseModel):
    counts: LibraryCountsOut
    pending: int = Field(description="Images waiting to be analysed.")
    search_model: ModelStatusName = Field(description="Install state of the CLIP model behind search.")
    search_model_id: str
    faces_ready: bool = Field(
        description="Whether the face detector (part of the face restoration model) is installed."
    )
    faces_pending: int = Field(description="Images whose faces haven't been counted yet.")
    faces_model_id: str
    indexing: bool
    tags: list[TagCountOut]


class ImportFailureOut(BaseModel):
    path: str
    code: str
    message: str


class ImportStatusOut(BaseModel):
    enabled: bool = Field(description="Whether the folder is checked on a schedule.")
    available: bool | None = Field(description="Whether the folder was found at the last check.")
    folder: str = Field(description="The folder on your computer (SIQE_IMPORT_PATH).")
    every_seconds: int
    last_scan: datetime | None
    files: int | None = Field(description="Image files found at the last check.")
    imported: int
    duplicates: int
    waiting: int
    failed: int
    failures: list[ImportFailureOut]


# -------------------------------------------------------------------------------- flows


class FlowChoiceOut(BaseModel):
    value: str
    label: str


class FlowParamOut(BaseModel):
    name: str
    label: str
    kind: Literal[
        "number",
        "integer",
        "choice",
        "text",
        "boolean",
        "model",
        "album",
        "rules",
        "adjustments",
        "color",
        "tags",
    ]
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    choices: list[FlowChoiceOut] = Field(default_factory=list)
    help: str = ""
    optional: bool = False
    task: str | None = None


class FlowNodeTypeOut(BaseModel):
    type: str
    label: str
    category: Literal["input", "condition", "edit", "ai", "output"]
    category_label: str
    summary: str
    inputs: int
    outputs: list[str]
    queue: Literal["none", "cpu", "gpu"]
    ai: bool
    transforms: bool
    writes_library: bool
    params: list[FlowParamOut]


class FlowPositionIO(BaseModel):
    x: float = 0
    y: float = 0


class FlowNodeIO(BaseModel):
    id: str
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    position: FlowPositionIO = Field(default_factory=FlowPositionIO)
    label: str | None = None


class FlowEdgeIO(BaseModel):
    source: str
    target: str
    port: str = "out"


class FlowDocumentIO(BaseModel):
    version: Literal[1] = 1
    nodes: list[FlowNodeIO] = Field(default_factory=list)
    edges: list[FlowEdgeIO] = Field(default_factory=list)


class FlowProblemOut(BaseModel):
    node: str | None = None
    message: str


class RecipeOut(BaseModel):
    id: str
    name: str
    summary: str
    ai: bool
    document: FlowDocumentIO


class FlowRunSummaryOut(BaseModel):
    id: str
    state: JobStateName
    done: int
    failed: int
    total: int
    created_at: datetime | None


class FlowOut(BaseModel):
    id: str
    name: str
    description: str
    document: FlowDocumentIO
    watch_folder: str | None
    watch_enabled: bool
    recipe: str | None
    created_at: datetime | None
    updated_at: datetime | None
    problems: list[FlowProblemOut]
    ai: bool = Field(description="Whether any block runs an AI model.")
    last_run: FlowRunSummaryOut | None = None


class FlowIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    recipe: str | None = Field(default=None, description="Start from a recipe's document.")
    document: FlowDocumentIO | None = None


class FlowUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    document: FlowDocumentIO | None = None
    watch_folder: str | None = Field(default=None, max_length=300)
    watch_enabled: bool | None = None


class FlowFileIO(BaseModel):
    """A flow saved as a file (`.flow.json`), for sharing and for `siqe run`."""

    format: Literal["siqe-flow"] = "siqe-flow"
    version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    document: FlowDocumentIO


class FlowSourceIn(BaseModel):
    kind: Literal["assets", "album", "rules", "all"] = "assets"
    asset_ids: list[str] = Field(default_factory=list, max_length=20_000)
    album_id: str | None = None
    rules: RuleSet | None = None


class FlowRunIn(BaseModel):
    source: FlowSourceIn
    dry_run: bool = Field(
        default=False, description="Try it on the first images without changing the Library."
    )
    limit: int | None = Field(default=None, ge=1, le=20_000)


class FlowRunOut(BaseModel):
    id: str
    flow_id: str | None
    flow_name: str
    job_id: str | None
    kind: Literal["manual", "watch", "api"]
    dry_run: bool
    source: dict[str, Any] = Field(default_factory=dict)
    state: JobStateName
    total: int
    done: int
    failed: int
    skipped: int
    output_dir: str
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    download_url: str | None


class FlowRunItemOut(BaseModel):
    id: str
    position: int
    asset_id: str | None
    name: str
    state: Literal["pending", "running", "done", "failed", "skipped"]
    steps: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    error: dict[str, Any] | None
    thumb_url: str | None
    started_at: datetime | None
    finished_at: datetime | None


class FlowRunDetailOut(BaseModel):
    run: FlowRunOut
    items: list[FlowRunItemOut]
    output_folder: str = Field(description="Where this run's files are on your computer.")


# ------------------------------------------------------------------------------ access


class AuthStatusOut(BaseModel):
    mode: Literal["off", "keys"]
    signed_in: bool = Field(description="True when this request carries a valid key, or keys are off.")
    key_name: str | None = None


class SignInIn(BaseModel):
    key: str = Field(min_length=1, max_length=200)


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str = Field(description="The first characters of the key, to tell keys apart.")
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ApiKeyCreatedOut(ApiKeyOut):
    secret: str = Field(description="The key itself. It is shown only this once.")
