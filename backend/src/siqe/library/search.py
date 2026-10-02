"""Library listing: views, filters, sorting, search by description and "find similar".

Vector queries rank by inner product (embeddings are unit length, so for two images it is the
cosine similarity). Text queries use a bias-corrected vector (``embedder.query_vector``) and
keep results within ``TEXT_WINDOW`` of the best match, so a query returns the images that fit
rather than the whole library in some order.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from sqlalchemy import ColumnElement, Select, and_, any_, case, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.db.models import Album, AlbumAsset, AlbumKind, Asset
from siqe.library.rules import RuleSet, compile_rules, parse

View = Literal["all", "duplicates", "quarantine", "album"]
Sort = Literal["added", "taken", "name", "size", "resolution", "sharpness"]

# Bias-corrected scores: nonsense queries top out near 0.08 on the samples, clear matches 0.09+.
TEXT_FLOOR = 0.08
TEXT_WINDOW = 0.08
TAG_BONUS = 0.1
SIMILAR_FLOOR = 0.5


@dataclass
class Query:
    view: View = "all"
    album: Album | None = None
    rules: RuleSet = field(default_factory=RuleSet)
    q: str | None = None
    similar_to: Asset | None = None
    sort: Sort = "added"
    descending: bool = True
    offset: int = 0
    limit: int = 100


@dataclass
class Page:
    items: list[tuple[Asset, float | None]]
    total: int
    mode: Literal["browse", "text", "name", "similar"]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def view_clause(query: Query) -> ColumnElement[bool]:
    parts: list[ColumnElement[bool]] = []
    if query.view == "quarantine":
        parts.append(Asset.quarantined_at.is_not(None))
    else:
        parts.append(Asset.quarantined_at.is_(None))
    if query.view == "duplicates":
        parts.append(Asset.duplicate_group.is_not(None))
    if query.view == "album" and query.album is not None:
        parts.append(album_clause(query.album))
    if query.rules.rules:
        parts.append(compile_rules(query.rules))
    return and_(*parts)


def album_clause(album: Album) -> ColumnElement[bool]:
    if album.kind == AlbumKind.smart:
        return compile_rules(parse(album.rules))
    members = select(AlbumAsset.asset_id).where(AlbumAsset.album_id == album.id)
    return Asset.id.in_(members)


def _text_match(q: str) -> ColumnElement[bool]:
    tag = q.strip().lower()
    return or_(
        Asset.original_name.ilike(f"%{_escape(q.strip())}%", escape="\\"),
        literal(tag) == any_(Asset.tags),
        literal(tag) == any_(Asset.auto_tags),
    )


def _order(query: Query) -> list[Any]:
    column: Any = {
        "added": Asset.created_at,
        "taken": func.coalesce(Asset.taken_at, Asset.created_at),
        "name": func.lower(Asset.original_name),
        "size": Asset.size_bytes,
        "resolution": Asset.width * Asset.height,
        "sharpness": func.coalesce(Asset.sharpness, 0),
    }[query.sort]
    first = column.desc() if query.descending else column.asc()
    return [first, Asset.id]


async def _vector_settings(session: AsyncSession) -> None:
    # Let the HNSW index return enough candidates for filtered, paged queries.
    await session.execute(text("SET LOCAL hnsw.ef_search = 1000"))


async def _page(
    session: AsyncSession, stmt: Select[Any, Any], where: ColumnElement[bool], query: Query
) -> tuple[list[Any], int]:
    total = int((await session.execute(select(func.count()).select_from(Asset).where(where))).scalar_one())
    rows = (await session.execute(stmt.where(where).offset(query.offset).limit(query.limit))).all()
    return list(rows), total


async def run(session: AsyncSession, query: Query, text_vector: np.ndarray | None = None) -> Page:
    base = view_clause(query)

    if query.similar_to is not None:
        target = query.similar_to.embedding
        if target is None:
            return Page([], 0, "similar")
        await _vector_settings(session)
        score = (Asset.embedding.max_inner_product(target) * -1).label("score")
        where = and_(
            base,
            Asset.id != query.similar_to.id,
            Asset.embedding.is_not(None),
            Asset.embedding.max_inner_product(target) <= -SIMILAR_FLOOR,
        )
        stmt = select(Asset, score).order_by(Asset.embedding.max_inner_product(target), Asset.id)
        rows, total = await _page(session, stmt, where, query)
        return Page([(r[0], float(r[1])) for r in rows], total, "similar")

    if query.q and query.q.strip():
        match = _text_match(query.q)
        if text_vector is None:
            stmt = select(Asset, literal(None).label("score")).order_by(*_order(query))
            rows, total = await _page(session, stmt, and_(base, match), query)
            return Page([(r[0], None) for r in rows], total, "name")
        await _vector_settings(session)
        vector = text_vector.tolist()
        inner = Asset.embedding.max_inner_product(vector) * -1
        best = (
            await session.execute(select(func.max(inner)).where(base, Asset.embedding.is_not(None)))
        ).scalar_one_or_none()
        floor = max(TEXT_FLOOR, float(best or 0) - TEXT_WINDOW)
        bonus = func.coalesce(inner, 0) + case((match, TAG_BONUS), else_=0.0)
        score = bonus.label("score")
        where = and_(base, or_(match, and_(Asset.embedding.is_not(None), inner >= floor)))
        stmt = select(Asset, score).order_by(bonus.desc(), Asset.id)
        rows, total = await _page(session, stmt, where, query)
        return Page([(r[0], float(r[1])) for r in rows], total, "text")

    order = _order(query)
    if query.view == "duplicates":
        order = [Asset.duplicate_group, Asset.duplicate_rank, *order]
    stmt = select(Asset, literal(None).label("score")).order_by(*order)
    rows, total = await _page(session, stmt, base, query)
    return Page([(r[0], None) for r in rows], total, "browse")


async def album_count(session: AsyncSession, album: Album) -> int:
    where = and_(Asset.quarantined_at.is_(None), album_clause(album))
    return int((await session.execute(select(func.count()).select_from(Asset).where(where))).scalar_one())


async def counts(session: AsyncSession) -> dict[str, int]:
    row = (
        await session.execute(
            select(
                func.count().filter(Asset.quarantined_at.is_(None)),
                func.count().filter(Asset.quarantined_at.is_(None), Asset.duplicate_group.is_not(None)),
                func.count(func.distinct(Asset.duplicate_group)).filter(Asset.quarantined_at.is_(None)),
                func.count().filter(Asset.quarantined_at.is_not(None)),
            ).select_from(Asset)
        )
    ).one()
    return {"all": row[0], "duplicates": row[1], "duplicate_groups": row[2], "quarantine": row[3]}


async def tag_counts(session: AsyncSession, limit: int = 40) -> list[tuple[str, int]]:
    tag = func.unnest(func.array_cat(Asset.tags, Asset.auto_tags)).label("tag")
    sub = select(Asset.id, tag).where(Asset.quarantined_at.is_(None)).subquery()
    rows = await session.execute(
        select(sub.c.tag, func.count(func.distinct(sub.c.id)).label("n"))
        .group_by(sub.c.tag)
        .order_by(text("n DESC"), sub.c.tag)
        .limit(limit)
    )
    return [(r[0], int(r[1])) for r in rows]


def parse_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
