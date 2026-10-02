"""Library: browse, search, find similar, duplicates, quarantine, albums and tags."""

import asyncio
import json
import uuid
from datetime import timedelta
from functools import lru_cache
from typing import Annotated, Literal

import numpy as np
from fastapi import APIRouter, Query, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.common import WorkflowIDConflictPolicy

from siqe.activities.library import IMPORT_STATUS_KEY
from siqe.ai.manifest import CLIP_MODEL_ID
from siqe.ai.registry import get_row, get_spec, status_of
from siqe.api.deps import SessionDep, SettingsDep, TemporalDep
from siqe.api.schemas import (
    AlbumIn,
    AlbumMembersIn,
    AlbumOut,
    AlbumPatchIn,
    AssetIdsIn,
    AssetOut,
    ChangedOut,
    DuplicatesResolveIn,
    ImportStatusOut,
    JobOut,
    LibraryPageOut,
    LibraryStatusOut,
    QuarantineIn,
    TagsIn,
)
from siqe.assets.records import ASSET_DELETED_EVENT, asset_to_dict, get_asset, publish_deleted
from siqe.core.config import CPU_TASK_QUEUE
from siqe.core.errors import AppError, NotFoundError, validation_message
from siqe.core.logging import get_logger
from siqe.db.base import utcnow
from siqe.db.models import Album, AlbumAsset, AlbumKind, AppSetting, Asset, ImportFile, ImportState
from siqe.events.bus import publish
from siqe.jobs.records import job_to_dict
from siqe.jobs.start import create_job, start_workflow
from siqe.library import embedder, search
from siqe.library.index import count_pending
from siqe.library.rules import RuleSet
from siqe.library.trigger import index_running, request_index
from siqe.orchestration.client import TemporalGateway
from siqe.storage.store import get_store
from siqe.workflows.library import IMPORT_WORKFLOW_ID, ImportFolderWorkflow, RemoveLocationWorkflow

router = APIRouter(prefix="/library", tags=["library"])
log = get_logger(__name__)

LIBRARY_EVENT = "library.updated"
MAX_TAG_LENGTH = 40


# ------------------------------------------------------------------------- helpers


def _ids(values: list[str]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for value in values:
        try:
            out.append(uuid.UUID(value))
        except ValueError as exc:
            raise AppError(
                "asset.not_found", f"'{value}' isn't an image id.", status=404, title="Image not found"
            ) from exc
    return out


async def _changed(session: AsyncSession, reason: str, count: int) -> ChangedOut:
    await publish(session, LIBRARY_EVENT, {"reason": reason, "changed": count})
    return ChangedOut(changed=count)


async def _wake(temporal: TemporalGateway) -> None:
    """Regroup duplicates and index new images. A stopped job engine only delays this."""
    try:
        await request_index(await temporal.client())
    except Exception as exc:
        log.warning("library.index_not_started", error=str(exc))


def _out(asset: Asset, score: float | None = None) -> AssetOut:
    return AssetOut.model_validate({**asset_to_dict(asset), "score": score})


async def _album(session: AsyncSession, album_id: uuid.UUID) -> Album:
    album = await session.get(Album, album_id)
    if album is None:
        raise NotFoundError("album.not_found", "That album doesn't exist.", title="Album not found")
    return album


async def _album_out(session: AsyncSession, album: Album) -> AlbumOut:
    return AlbumOut(
        id=str(album.id),
        name=album.name,
        kind=album.kind.value,
        rules=RuleSet.model_validate(album.rules or {}),
        count=await search.album_count(session, album),
        position=album.position,
    )


@lru_cache(maxsize=256)
def _query_vector(text: str, model_key: float) -> np.ndarray:
    return embedder.query_vector(text)


def _parse_rules(raw: str | None) -> RuleSet:
    if not raw:
        return RuleSet()
    try:
        return RuleSet.model_validate(json.loads(raw))
    except (ValueError, TypeError) as exc:
        raise AppError(
            "library.invalid_rules",
            f"These filters can't be used: {validation_message(exc)}.",
            status=422,
            title="Invalid filters",
            fix="Remove the last filter you added and try again.",
        ) from exc


# ------------------------------------------------------------------------ browsing


@router.get("/assets", response_model=LibraryPageOut, summary="Browse, filter and search the library")
async def library_assets(
    session: SessionDep,
    view: Literal["all", "duplicates", "quarantine", "album"] = "all",
    album_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Search by description or name.")] = None,
    similar_to: Annotated[uuid.UUID | None, Query(description="Images that look like this one.")] = None,
    rules: Annotated[str | None, Query(description="Filter rule set as JSON.")] = None,
    sort: Literal["added", "taken", "name", "size", "resolution", "sharpness"] = "added",
    order: Literal["asc", "desc"] = "desc",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> LibraryPageOut:
    query = search.Query(
        view=view,
        rules=_parse_rules(rules),
        q=q,
        sort=sort,
        descending=order == "desc",
        offset=offset,
        limit=limit,
    )
    if view == "album":
        if album_id is None:
            raise AppError("album.not_found", "Choose an album.", status=422, title="Album missing")
        query.album = await _album(session, album_id)
    if similar_to is not None:
        target = await get_asset(session, similar_to)
        await session.refresh(target, ["embedding"])
        if target.embedding is None:
            raise AppError(
                "library.not_indexed",
                "This image hasn't been analysed for similarity yet.",
                status=409,
                title="Not indexed yet",
                fix="Download CLIP search in the Library, or wait for indexing to finish.",
            )
        query.similar_to = target
    vector = None
    if q and q.strip() and similar_to is None and embedder.installed():
        try:
            vector = await asyncio.to_thread(_query_vector, q.strip()[:200], embedder.model_key())
        except Exception as exc:  # fall back to name and tag search
            log.warning("library.text_search_failed", error=str(exc))
    page = await search.run(session, query, vector)
    return LibraryPageOut(
        items=[_out(a, s) for a, s in page.items],
        total=page.total,
        offset=offset,
        limit=limit,
        mode=page.mode,
    )


@router.get("/status", response_model=LibraryStatusOut, summary="Counts, indexing state and top tags")
async def library_status(session: SessionDep, temporal: TemporalDep) -> LibraryStatusOut:
    spec = get_spec(CLIP_MODEL_ID)
    model = status_of(spec, await get_row(session, CLIP_MODEL_ID))
    pending = await count_pending(session, model == "installed")
    running = False
    if pending:
        try:
            running = await index_running(await temporal.client())
        except Exception:
            running = False
    return LibraryStatusOut.model_validate(
        {
            "counts": await search.counts(session),
            "pending": pending,
            "search_model": model,
            "search_model_id": CLIP_MODEL_ID,
            "indexing": running,
            "tags": [{"tag": t, "count": n} for t, n in await search.tag_counts(session)],
        }
    )


@router.post(
    "/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    summary="Analyse new images and regroup duplicates now",
)
async def reindex(temporal: TemporalDep) -> Response:
    await request_index(await temporal.client())
    return Response(status_code=status.HTTP_202_ACCEPTED)


# ---------------------------------------------------------------------- quarantine


@router.post("/quarantine", response_model=ChangedOut, summary="Hide images in quarantine (undoable)")
async def quarantine(body: QuarantineIn, session: SessionDep, temporal: TemporalDep) -> ChangedOut:
    ids = _ids(body.asset_ids)
    result = await session.execute(
        update(Asset)
        .where(Asset.id.in_(ids), Asset.quarantined_at.is_(None))
        .values(
            quarantined_at=utcnow(),
            quarantine_reason=body.reason or "Moved to quarantine",
            duplicate_group=None,
            duplicate_rank=None,
        )
    )
    out = await _changed(session, "quarantine", result.rowcount)  # type: ignore[attr-defined]
    await session.commit()
    await _wake(temporal)
    return out


@router.post("/restore", response_model=ChangedOut, summary="Bring images back from quarantine")
async def restore(body: AssetIdsIn, session: SessionDep, temporal: TemporalDep) -> ChangedOut:
    ids = _ids(body.asset_ids)
    result = await session.execute(
        update(Asset)
        .where(Asset.id.in_(ids), Asset.quarantined_at.is_not(None))
        .values(quarantined_at=None, quarantine_reason=None)
    )
    out = await _changed(session, "restore", result.rowcount)  # type: ignore[attr-defined]
    await session.commit()
    await _wake(temporal)
    return out


@router.post(
    "/delete",
    response_model=ChangedOut,
    summary="Permanently delete quarantined images and their files",
    description="Only images already in quarantine are deleted; others are left alone.",
)
async def delete_quarantined(body: AssetIdsIn, session: SessionDep) -> ChangedOut:
    ids = _ids(body.asset_ids)
    rows = (
        await session.execute(select(Asset).where(Asset.id.in_(ids), Asset.quarantined_at.is_not(None)))
    ).scalars()
    doomed = [(a.id, a.sha256, a.extension) for a in rows]
    for asset_id, _, _ in doomed:
        await session.execute(delete(Asset).where(Asset.id == asset_id))
        await publish_deleted(session, ASSET_DELETED_EVENT, asset_id)
    out = await _changed(session, "delete", len(doomed))
    await session.commit()
    store = get_store()
    for asset_id, sha, ext in doomed:
        await asyncio.to_thread(store.remove_asset, asset_id, sha, ext)
    return out


@router.post(
    "/remove-location",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
    summary="Replace images with copies that have no GPS location",
    description=(
        "Pixels and other camera data are kept byte for byte. Each original moves to quarantine, "
        "so the change can be undone by restoring it."
    ),
)
async def start_remove_location(body: AssetIdsIn, session: SessionDep, temporal: TemporalDep) -> JobOut:
    ids = _ids(body.asset_ids)
    targets = list(
        (
            await session.execute(
                select(Asset.id).where(
                    Asset.id.in_(ids), Asset.has_gps.is_(True), Asset.quarantined_at.is_(None)
                )
            )
        ).scalars()
    )
    if not targets:
        raise AppError(
            "library.no_location",
            "None of these images has a recorded location.",
            status=422,
            title="Nothing to remove",
            fix="Use the Has location album to find images with GPS data.",
        )
    count = len(targets)
    job = await create_job(
        session,
        kind="library.remove_location",
        title=f"Remove location from {count} image{'s' if count != 1 else ''}",
        params={"asset_ids": [str(t) for t in targets]},
    )
    await start_workflow(
        session, temporal, job, RemoveLocationWorkflow.run, [str(job.id), [str(t) for t in targets]]
    )
    return JobOut.model_validate(job_to_dict(job))


# ---------------------------------------------------------------------- duplicates


@router.post(
    "/duplicates/resolve",
    response_model=ChangedOut,
    summary="Keep the best copy of each duplicate group and quarantine the rest",
)
async def resolve_duplicates(
    body: DuplicatesResolveIn, session: SessionDep, temporal: TemporalDep
) -> ChangedOut:
    stmt = select(Asset).where(Asset.duplicate_group.is_not(None), Asset.quarantined_at.is_(None))
    if body.groups is not None:
        stmt = stmt.where(Asset.duplicate_group.in_(_ids(body.groups)))
    members = list((await session.execute(stmt)).scalars())
    keepers = {a.duplicate_group: a for a in members if a.duplicate_rank == 0}
    now = utcnow()
    changed = 0
    for asset in members:
        keep = keepers.get(asset.duplicate_group)
        if keep is None or asset.id == keep.id:
            continue
        asset.quarantined_at = now
        asset.quarantine_reason = f"Duplicate of {keep.original_name}"[:200]
        asset.duplicate_group = None
        asset.duplicate_rank = None
        changed += 1
    for keep in keepers.values():
        keep.duplicate_group = None
        keep.duplicate_rank = None
    out = await _changed(session, "duplicates", changed)
    await session.commit()
    await _wake(temporal)
    return out


@router.post(
    "/duplicates/{group_id}/keep-all",
    response_model=ChangedOut,
    summary="These aren't duplicates: keep every image and stop grouping them",
)
async def keep_all(group_id: uuid.UUID, session: SessionDep) -> ChangedOut:
    result = await session.execute(
        update(Asset)
        .where(Asset.duplicate_group == group_id)
        .values(duplicate_ok=True, duplicate_group=None, duplicate_rank=None)
    )
    out = await _changed(session, "duplicates", result.rowcount)  # type: ignore[attr-defined]
    return out


# --------------------------------------------------------------------------- tags


def _clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for tag in tags:
        t = " ".join(tag.strip().lower().split())[:MAX_TAG_LENGTH]
        if t and t not in out:
            out.append(t)
    return out


@router.post("/tags", response_model=ChangedOut, summary="Add or remove your own tags on images")
async def edit_tags(body: TagsIn, session: SessionDep) -> ChangedOut:
    add, remove = _clean_tags(body.add), set(_clean_tags(body.remove))
    rows = (await session.execute(select(Asset).where(Asset.id.in_(_ids(body.asset_ids))))).scalars()
    changed = 0
    for asset in rows:
        current = list(asset.tags or [])
        tags = [t for t in current if t not in remove] + [t for t in add if t not in current]
        # Removing a tag CLIP chose hides it too.
        auto = [t for t in (asset.auto_tags or []) if t not in remove]
        if tags != current or auto != list(asset.auto_tags or []):
            asset.tags = tags[:30]
            asset.auto_tags = auto
            changed += 1
    return await _changed(session, "tags", changed)


# -------------------------------------------------------------------------- albums


@router.get("/albums", response_model=list[AlbumOut], summary="Albums with their image counts")
async def list_albums(session: SessionDep) -> list[AlbumOut]:
    albums = (await session.execute(select(Album).order_by(Album.position, Album.created_at))).scalars()
    return [await _album_out(session, a) for a in albums]


@router.post("/albums", response_model=AlbumOut, status_code=status.HTTP_201_CREATED, summary="New album")
async def create_album(body: AlbumIn, session: SessionDep) -> AlbumOut:
    position = (await session.execute(select(func.coalesce(func.max(Album.position), -1)))).scalar_one()
    album = Album(
        name=body.name.strip(),
        kind=AlbumKind(body.kind),
        rules=body.rules.model_dump() if body.kind == "smart" else {},
        position=int(position) + 1,
    )
    session.add(album)
    await session.flush()
    await _changed(session, "albums", 1)
    return await _album_out(session, album)


@router.patch("/albums/{album_id}", response_model=AlbumOut, summary="Rename an album or change its rules")
async def update_album(album_id: uuid.UUID, body: AlbumPatchIn, session: SessionDep) -> AlbumOut:
    album = await _album(session, album_id)
    if body.name is not None:
        album.name = body.name.strip()
    if body.rules is not None:
        if album.kind != AlbumKind.smart:
            raise AppError(
                "album.not_smart",
                "Only smart albums have rules.",
                status=422,
                title="Not a smart album",
                fix="Add or remove images from this album instead.",
            )
        album.rules = body.rules.model_dump()
    if body.position is not None:
        album.position = body.position
    album.updated_at = utcnow()
    await session.flush()
    await _changed(session, "albums", 1)
    return await _album_out(session, album)


@router.delete(
    "/albums/{album_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an album (its images stay in the library)",
)
async def delete_album(album_id: uuid.UUID, session: SessionDep) -> Response:
    album = await _album(session, album_id)
    await session.delete(album)
    await _changed(session, "albums", 1)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/albums/{album_id}/assets",
    response_model=ChangedOut,
    summary="Add images to or remove them from an album",
)
async def album_members(album_id: uuid.UUID, body: AlbumMembersIn, session: SessionDep) -> ChangedOut:
    album = await _album(session, album_id)
    if album.kind != AlbumKind.manual:
        raise AppError(
            "album.not_manual",
            "Smart albums fill themselves from their rules.",
            status=422,
            title="Smart album",
            fix="Edit the album's rules, or add the images to a regular album.",
        )
    ids = _ids(body.asset_ids)
    if body.action == "remove":
        result = await session.execute(
            delete(AlbumAsset).where(AlbumAsset.album_id == album.id, AlbumAsset.asset_id.in_(ids))
        )
        return await _changed(session, "albums", result.rowcount)  # type: ignore[attr-defined]
    existing = set((await session.execute(select(Asset.id).where(Asset.id.in_(ids)))).scalars()) - set(
        (
            await session.execute(
                select(AlbumAsset.asset_id).where(
                    AlbumAsset.album_id == album.id, AlbumAsset.asset_id.in_(ids)
                )
            )
        ).scalars()
    )
    for asset_id in existing:
        session.add(AlbumAsset(album_id=album.id, asset_id=asset_id))
    await session.flush()
    return await _changed(session, "albums", len(existing))


@router.get(
    "/assets/{asset_id}/albums",
    response_model=list[str],
    summary="Ids of the hand-picked albums an image is in",
)
async def asset_albums(asset_id: uuid.UUID, session: SessionDep) -> list[str]:
    await get_asset(session, asset_id)
    rows = (
        await session.execute(select(AlbumAsset.album_id).where(AlbumAsset.asset_id == asset_id))
    ).scalars()
    return [str(r) for r in rows]


# -------------------------------------------------------------------- import folder


@router.get("/import", response_model=ImportStatusOut, summary="The import folder and what it has imported")
async def import_status(session: SessionDep, settings: SettingsDep) -> ImportStatusOut:
    row = await session.get(AppSetting, IMPORT_STATUS_KEY)
    info = row.value if row else {}
    rows = await session.execute(select(ImportFile.state, func.count()).group_by(ImportFile.state))
    counts = {state: int(n) for state, n in rows.tuples()}
    failures = (
        await session.execute(
            select(ImportFile)
            .where(ImportFile.state == ImportState.failed)
            .order_by(ImportFile.updated_at.desc())
            .limit(10)
        )
    ).scalars()
    return ImportStatusOut.model_validate(
        {
            "enabled": settings.import_scan_seconds > 0,
            "available": info.get("available"),
            "folder": settings.import_host_path,
            "every_seconds": settings.import_scan_seconds,
            "last_scan": info.get("last_scan"),
            "files": info.get("files"),
            "imported": counts.get(ImportState.imported, 0),
            "duplicates": counts.get(ImportState.duplicate, 0),
            "waiting": counts.get(ImportState.waiting, 0),
            "failed": counts.get(ImportState.failed, 0),
            "failures": [
                {
                    "path": f.path,
                    "code": (f.error or {}).get("code", "import.failed"),
                    "message": (f.error or {}).get("message", ""),
                }
                for f in failures
            ],
        }
    )


@router.post(
    "/import/scan",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    summary="Check the import folder now",
)
async def scan_now(temporal: TemporalDep) -> Response:
    client = await temporal.client()
    await client.start_workflow(
        ImportFolderWorkflow.run,
        id=f"{IMPORT_WORKFLOW_ID}-now",
        task_queue=CPU_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        execution_timeout=timedelta(hours=6),
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)
