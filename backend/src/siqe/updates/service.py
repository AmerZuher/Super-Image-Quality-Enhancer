"""Update center: compares the running version with GitHub releases.

Releases are cached in ``app_settings`` and refreshed at most every
``SIQE_UPDATE_CHECK_HOURS`` (6 h by default) using ETags, so normal use costs at most a few
GitHub API calls a day and works offline with the last known list.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.core.config import Settings
from siqe.core.logging import get_logger
from siqe.db.base import utcnow
from siqe.db.models import AppSetting

log = get_logger(__name__)

CACHE_KEY = "updates.cache"
GITHUB_API = "https://api.github.com"
MAX_NOTES_CHARS = 20_000


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    name: str
    notes: str
    url: str
    published_at: str | None
    prerelease: bool


@dataclass(frozen=True)
class Evaluation:
    newer: list[Release]
    latest: Release | None
    current: Release | None


def parse_version(raw: str) -> Version | None:
    try:
        return Version(raw.strip().removeprefix("v").removeprefix("V"))
    except InvalidVersion:
        return None


def parse_releases(payload: list[dict[str, Any]]) -> list[Release]:
    releases = []
    for item in payload:
        if item.get("draft"):
            continue
        tag = str(item.get("tag_name") or "")
        version = parse_version(tag)
        if version is None:
            continue
        releases.append(
            Release(
                tag=tag,
                version=str(version),
                name=str(item.get("name") or tag),
                notes=str(item.get("body") or "")[:MAX_NOTES_CHARS],
                url=str(item.get("html_url") or ""),
                published_at=item.get("published_at"),
                prerelease=bool(item.get("prerelease")) or version.is_prerelease,
            )
        )
    return sorted(releases, key=lambda r: Version(r.version), reverse=True)


def evaluate(current_version: str, releases: list[Release], include_prereleases: bool) -> Evaluation:
    current = parse_version(current_version) or Version("0")
    visible = [
        r for r in releases if include_prereleases or not r.prerelease or Version(r.version) == current
    ]
    newer = [r for r in visible if Version(r.version) > current]
    this = next((r for r in releases if Version(r.version) == current), None)
    return Evaluation(newer=newer, latest=visible[0] if visible else None, current=this)


async def _fetch(settings: Settings, etag: str | None) -> tuple[int, list[dict[str, Any]] | None, str | None]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if etag:
        headers["If-None-Match"] = etag
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token.get_secret_value()}"
    url = f"{GITHUB_API}/repos/{settings.update_repo}/releases"
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(url, headers=headers, params={"per_page": 30})
    if response.status_code == 304:
        return 304, None, etag
    response.raise_for_status()
    return 200, response.json(), response.headers.get("ETag")


async def check(session: AsyncSession, settings: Settings, *, force: bool = False) -> dict[str, Any]:
    row = await session.get(AppSetting, CACHE_KEY)
    cache: dict[str, Any] = dict(row.value) if row else {}
    fetched_at = datetime.fromisoformat(cache["fetched_at"]) if cache.get("fetched_at") else None
    stale = fetched_at is None or utcnow() - fetched_at > timedelta(hours=settings.update_check_hours)

    error: str | None = cache.get("error")
    if force or stale:
        try:
            status, payload, etag = await _fetch(settings, cache.get("etag"))
            if status == 200 and payload is not None:
                cache["releases"] = [asdict(r) for r in parse_releases(payload)]
            cache["etag"] = etag
            error = None
        except httpx.HTTPStatusError as exc:
            error = (
                f"GitHub repository {settings.update_repo} was not found."
                if exc.response.status_code == 404
                else f"GitHub answered {exc.response.status_code}."
            )
        except httpx.HTTPError as exc:
            error = f"Couldn't reach GitHub ({type(exc).__name__}). Showing the last known releases."
        cache["fetched_at"] = utcnow().isoformat()
        cache["error"] = error
        if error:
            log.info("updates.check_failed", error=error)
        if row is None:
            session.add(AppSetting(key=CACHE_KEY, value=cache))
        else:
            row.value = cache

    releases = [Release(**r) for r in cache.get("releases", [])]
    result = evaluate(settings.version, releases, settings.update_include_prereleases)
    repo_url = f"https://github.com/{settings.update_repo}"
    return {
        "current_version": settings.version,
        "latest_version": result.latest.version if result.latest else None,
        "update_available": bool(result.newer),
        "newer": [asdict(r) for r in result.newer],
        "current": asdict(result.current) if result.current else None,
        "checked_at": cache.get("fetched_at"),
        "error": error,
        "repo_url": repo_url,
        "releases_url": f"{repo_url}/releases",
    }
