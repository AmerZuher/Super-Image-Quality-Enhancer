"""Choosing images from the Library: picked ones, an album, a set of rules, or all of them.

Shared by flow runs and Forge datasets. Quarantined and unfinished images are always left out.
"""

import uuid
from typing import Any, Literal

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.core.errors import AppError, NotFoundError
from siqe.db.models import Album, Asset, AssetStatus
from siqe.library.rules import RuleSet, compile_rules
from siqe.library.search import album_clause

Kind = Literal["assets", "album", "rules", "all"]


def _uuid(value: str | None, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise NotFoundError(f"{what}.not_found", f"No {what} with id {value}.", title="Not found") from exc


async def select_images(
    session: AsyncSession,
    kind: Kind,
    *,
    asset_ids: list[str] | None = None,
    album_id: str | None = None,
    rules: RuleSet | None = None,
    empty_code: str = "library.no_images",
) -> tuple[list[uuid.UUID], dict[str, Any]]:
    """Image ids (newest first, or in the order given) and a short description of the choice."""
    base: ColumnElement[bool] = and_(Asset.status == AssetStatus.ready, Asset.quarantined_at.is_(None))
    if kind == "assets":
        ids = [_uuid(a, "image") for a in asset_ids or []]
        found = set((await session.execute(select(Asset.id).where(Asset.id.in_(ids), base))).scalars())
        return [i for i in ids if i in found], {"kind": "assets", "count": len(ids)}
    described: dict[str, Any]
    if kind == "album":
        album = await session.get(Album, _uuid(album_id, "album"))
        if album is None:
            raise NotFoundError("album.not_found", "That album doesn't exist.", title="Album not found")
        where, described = and_(base, album_clause(album)), {"kind": "album", "album": album.name}
    elif kind == "rules":
        if rules is None or not rules.rules:
            raise AppError(empty_code, "Add some filters to choose images.", status=422)
        where, described = and_(base, compile_rules(rules)), {"kind": "rules", "rules": rules.model_dump()}
    else:
        where, described = base, {"kind": "all"}
    ids = list(
        (await session.execute(select(Asset.id).where(where).order_by(Asset.created_at.desc()))).scalars()
    )
    return ids, described
