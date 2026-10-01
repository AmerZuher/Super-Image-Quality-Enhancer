import asyncio
import re
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from siqe.api.deps import SessionDep, SettingsDep, TemporalDep
from siqe.api.schemas import (
    AssetOut,
    CatalogOut,
    EditDocumentIn,
    ExportIn,
    ExportStartOut,
    JobOut,
    RenditionOut,
    UploadOut,
)
from siqe.assets.records import (
    ASSET_DELETED_EVENT,
    RENDITION_DELETED_EVENT,
    asset_to_dict,
    get_asset,
    get_rendition,
    publish_asset,
    publish_deleted,
    publish_rendition,
    rendition_to_dict,
)
from siqe.core.errors import AppError, validation_message
from siqe.db.base import utcnow
from siqe.db.models import Asset, AssetStatus, Rendition, RenditionStatus
from siqe.imaging import edits as edit_model
from siqe.imaging.export import ExportOptions, check_dimensions, check_disk, planned_size
from siqe.imaging.formats import INPUT_EXTENSIONS, OUTPUT_FORMATS
from siqe.imaging.io import inspect
from siqe.imaging.pipeline import output_size
from siqe.jobs.records import job_to_dict
from siqe.jobs.start import create_job, start_workflow
from siqe.storage.store import get_store
from siqe.workflows.assets import ExportWorkflow, IngestAssetWorkflow

router = APIRouter(tags=["assets"])

IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
_SAFE_NAME = re.compile(r"[^\w.\- ()]+")
_EXTENSIONS = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "heif": ".heic", "tiff": ".tif", "gif": ".gif"}


def _asset_out(asset: Asset) -> AssetOut:
    return AssetOut.model_validate(asset_to_dict(asset))


def _clean_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    return (_SAFE_NAME.sub("_", name).strip(" .") or "image")[:200]


# ----------------------------------------------------------------------------- catalog


@router.get("/ops", response_model=CatalogOut, summary="Edit operations, export formats and upload limits")
async def ops_catalog(settings: SettingsDep) -> CatalogOut:
    return CatalogOut.model_validate(
        {
            "ops": edit_model.catalog(),
            "formats": [
                {
                    "id": f.name,
                    "label": f.label,
                    "extension": f.extension,
                    "max_side": f.max_side,
                    "lossy": f.lossy,
                    "alpha": f.alpha,
                    "sixteen_bit": f.sixteen_bit,
                }
                for f in OUTPUT_FORMATS.values()
            ],
            "max_input_megapixels": settings.max_input_megapixels,
            "max_upload_mb": settings.max_upload_mb,
            "accepted_extensions": INPUT_EXTENSIONS,
        }
    )


# ------------------------------------------------------------------------------ upload


@router.post(
    "/assets",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image (raw request body)",
    description=(
        "Send the file bytes as the request body and its name in `filename`. The body is streamed to "
        "disk and hashed, never held in memory. Uploading a file that is already in the library returns "
        "the existing image with `duplicate: true` and status 200."
    ),
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/octet-stream": {"schema": {}}}}
    },
    responses={200: {"model": UploadOut, "description": "Already in the library"}},
)
async def upload_asset(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    temporal: TemporalDep,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
) -> UploadOut:
    store = get_store()
    store.ensure_space(settings)
    staged = await store.receive(request.stream(), settings.max_upload_mb * 1024 * 1024)
    try:
        existing = (
            await session.execute(select(Asset).where(Asset.sha256 == staged.sha256))
        ).scalar_one_or_none()
        if existing is not None:
            staged.path.unlink(missing_ok=True)
            response.status_code = status.HTTP_200_OK
            return UploadOut(asset=_asset_out(existing), duplicate=True, job=None)
        info = await asyncio.to_thread(inspect, staged.path)
    except BaseException:
        staged.path.unlink(missing_ok=True)
        raise

    extension = _EXTENSIONS.get(info.format, ".img")
    await asyncio.to_thread(store.commit, staged, extension)
    width, height = info.oriented_size
    name = _clean_name(filename)
    asset = Asset(
        sha256=staged.sha256,
        original_name=name,
        extension=extension,
        format=info.format,
        width=width,
        height=height,
        bit_depth=16 if info.bit_depth == 16 else 8,
        has_alpha=info.has_alpha,
        size_bytes=staged.size_bytes,
        status=AssetStatus.processing,
        exif=info.exif,
        has_gps=info.has_gps,
        edits={},
    )
    session.add(asset)
    try:
        await session.flush()
    except IntegrityError:
        # The same file finished uploading in another request a moment ago.
        await session.rollback()
        existing = (await session.execute(select(Asset).where(Asset.sha256 == staged.sha256))).scalar_one()
        response.status_code = status.HTTP_200_OK
        return UploadOut(asset=_asset_out(existing), duplicate=True, job=None)
    await publish_asset(session, asset)
    job = await create_job(
        session, kind="asset.ingest", title=f"Prepare {name}", params={"asset_id": str(asset.id)}
    )
    await start_workflow(session, temporal, job, IngestAssetWorkflow.run, [str(job.id), str(asset.id)])
    return UploadOut(asset=_asset_out(asset), duplicate=False, job=JobOut.model_validate(job_to_dict(job)))


# --------------------------------------------------------------------------- browsing


@router.get("/assets", response_model=list[AssetOut], summary="Images in the library, newest first")
async def list_assets(session: SessionDep, limit: int = Query(200, ge=1, le=1000)) -> list[AssetOut]:
    rows = (await session.execute(select(Asset).order_by(Asset.created_at.desc()).limit(limit))).scalars()
    return [_asset_out(a) for a in rows]


@router.get("/assets/{asset_id}", response_model=AssetOut, summary="One image")
async def one_asset(asset_id: uuid.UUID, session: SessionDep) -> AssetOut:
    return _asset_out(await get_asset(session, asset_id))


@router.delete(
    "/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an image and its files"
)
async def delete_asset(asset_id: uuid.UUID, session: SessionDep) -> Response:
    asset = await get_asset(session, asset_id)
    sha, ext = asset.sha256, asset.extension
    await session.delete(asset)
    await publish_deleted(session, ASSET_DELETED_EVENT, asset_id)
    await session.flush()
    await asyncio.to_thread(get_store().remove_asset, asset_id, sha, ext)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _ready(asset: Asset) -> None:
    if asset.status != AssetStatus.ready:
        raise AppError(
            "asset.not_ready",
            "This image is still being prepared."
            if asset.status == AssetStatus.processing
            else "This image failed to load.",
            status=409,
            title="Image not ready",
            fix="Wait for the preview to appear, or upload the file again.",
        )


async def _preview_file(asset_id: uuid.UUID, session: SessionDep, name: str) -> FileResponse:
    asset = await get_asset(session, asset_id)
    _ready(asset)
    path = get_store().previews(asset.id) / name
    if not path.exists():
        raise AppError(
            "media.not_found", "The preview file is missing.", status=404, fix="Upload the image again."
        )
    return FileResponse(path, media_type="image/webp", headers=IMMUTABLE)


@router.get("/assets/{asset_id}/thumb", response_class=FileResponse, summary="320 px thumbnail (WebP)")
async def asset_thumb(asset_id: uuid.UUID, session: SessionDep) -> FileResponse:
    return await _preview_file(asset_id, session, "thumb.webp")


@router.get("/assets/{asset_id}/preview", response_class=FileResponse, summary="2048 px preview (WebP)")
async def asset_preview(asset_id: uuid.UUID, session: SessionDep) -> FileResponse:
    return await _preview_file(asset_id, session, "preview.webp")


@router.get(
    "/assets/{asset_id}/dz/{path:path}", response_class=FileResponse, summary="Deep-zoom pyramid files"
)
async def asset_deep_zoom(asset_id: uuid.UUID, path: str, session: SessionDep) -> FileResponse:
    asset = await get_asset(session, asset_id)
    _ready(asset)
    base = get_store().previews(asset.id)
    target = get_store().inside(base, path)
    if not target.is_file():
        raise AppError("media.not_found", "No such tile.", status=404, title="Not found")
    media = "application/xml" if target.suffix == ".dzi" else "image/webp"
    return FileResponse(target, media_type=media, headers=IMMUTABLE)


@router.get("/assets/{asset_id}/original", response_class=FileResponse, summary="Download the original file")
async def asset_original(asset_id: uuid.UUID, session: SessionDep) -> FileResponse:
    asset = await get_asset(session, asset_id)
    path = get_store().original(asset.sha256, asset.extension)
    if not path.exists():
        raise AppError("media.not_found", "The original file is missing.", status=404, title="Not found")
    return FileResponse(path, filename=asset.original_name, headers=IMMUTABLE)


# ------------------------------------------------------------------------------ edits


@router.get("/assets/{asset_id}/edits", response_model=EditDocumentIn, summary="The image's edit document")
async def get_edits(asset_id: uuid.UUID, session: SessionDep) -> EditDocumentIn:
    asset = await get_asset(session, asset_id)
    return EditDocumentIn.model_validate(edit_model.parse_document(asset.edits).model_dump())


@router.put(
    "/assets/{asset_id}/edits", response_model=EditDocumentIn, summary="Replace the image's edit document"
)
async def put_edits(asset_id: uuid.UUID, body: EditDocumentIn, session: SessionDep) -> EditDocumentIn:
    doc = edit_model.parse_document(body.model_dump())
    asset = await get_asset(session, asset_id, for_update=True)
    asset.edits = doc.model_dump()
    asset.edits_updated_at = utcnow()
    await publish_asset(session, asset)
    return EditDocumentIn.model_validate(asset.edits)


# ----------------------------------------------------------------------------- export


@router.post(
    "/assets/{asset_id}/exports",
    response_model=ExportStartOut,
    status_code=status.HTTP_201_CREATED,
    summary="Render the current edits at full resolution and encode them",
)
async def start_export(
    asset_id: uuid.UUID, body: ExportIn, session: SessionDep, settings: SettingsDep, temporal: TemporalDep
) -> ExportStartOut:
    try:
        options = ExportOptions.model_validate(body.model_dump())
    except ValueError as exc:
        raise AppError(
            "export.invalid", f"These export settings can't be used: {validation_message(exc)}.", status=422
        ) from exc
    asset = await get_asset(session, asset_id)
    _ready(asset)
    doc = edit_model.parse_document(asset.edits)
    width, height = planned_size(*output_size(asset.width, asset.height, doc.geometry), options.max_side)
    check_dimensions(width, height, options)
    check_disk(settings.data_dir, width, height, 4, asset.bit_depth, settings.min_free_disk_ratio)

    spec = OUTPUT_FORMATS[options.format]
    stem = Path(asset.original_name).stem or "image"
    rendition = Rendition(
        asset_id=asset.id,
        status=RenditionStatus.pending,
        format=options.format,
        filename=f"{stem}-edited{spec.extension}",
        options=options.model_dump(),
        edits=doc.model_dump(),
        width=width,
        height=height,
    )
    session.add(rendition)
    job = await create_job(
        session,
        kind="asset.export",
        title=f"Export {stem} as {spec.label}",
        params={"asset_id": str(asset.id), **options.model_dump()},
    )
    rendition.job_id = job.id
    await publish_rendition(session, rendition)
    await start_workflow(session, temporal, job, ExportWorkflow.run, [str(job.id), str(rendition.id)])
    return ExportStartOut(
        job=JobOut.model_validate(job_to_dict(job)),
        rendition=RenditionOut.model_validate(rendition_to_dict(rendition)),
    )


@router.get(
    "/assets/{asset_id}/renditions", response_model=list[RenditionOut], summary="Exports of this image"
)
async def list_renditions(asset_id: uuid.UUID, session: SessionDep) -> list[RenditionOut]:
    await get_asset(session, asset_id)
    rows = (
        await session.execute(
            select(Rendition)
            .where(Rendition.asset_id == asset_id)
            .order_by(Rendition.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return [RenditionOut.model_validate(rendition_to_dict(r)) for r in rows]


@router.get("/renditions/{rendition_id}/download", response_class=FileResponse, summary="Download an export")
async def download_rendition(rendition_id: uuid.UUID, session: SessionDep) -> FileResponse:
    rendition = await get_rendition(session, rendition_id)
    if rendition.status != RenditionStatus.ready:
        raise AppError(
            "rendition.not_ready", "This export hasn't finished.", status=409, title="Export not ready"
        )
    path = get_store().rendition(rendition.asset_id, rendition.id, Path(rendition.filename).suffix)
    if not path.exists():
        raise AppError(
            "media.not_found", "The exported file is missing.", status=404, fix="Export the image again."
        )
    spec = OUTPUT_FORMATS.get(rendition.format)  # type: ignore[call-overload]
    return FileResponse(path, filename=rendition.filename, media_type=spec.media_type if spec else None)


@router.delete(
    "/renditions/{rendition_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an export"
)
async def delete_rendition(rendition_id: uuid.UUID, session: SessionDep) -> Response:
    rendition = await get_rendition(session, rendition_id)
    path = get_store().rendition(rendition.asset_id, rendition.id, Path(rendition.filename).suffix)
    await session.delete(rendition)
    await publish_deleted(session, RENDITION_DELETED_EVENT, rendition_id, asset_id=str(rendition.asset_id))
    await session.flush()
    path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
