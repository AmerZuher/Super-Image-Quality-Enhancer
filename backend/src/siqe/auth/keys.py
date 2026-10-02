"""API keys: made once, shown once, stored only as a SHA-256 hash.

A key looks like ``siqe_<43 url-safe characters>`` (256 bits). The first 12 characters are kept
as a prefix so people can tell keys apart in the list. Checking a key costs one indexed lookup;
results are cached for a short while so a busy page doesn't hit the database for every request.
"""

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.db.base import utcnow
from siqe.db.models import ApiKey

KEY_PREFIX = "siqe_"
SHOWN_PREFIX = 12
CACHE_SECONDS = 30.0
# How stale "last used" may get before it is written again.
TOUCH_EVERY = timedelta(minutes=5)


@dataclass(frozen=True)
class KeyCheck:
    key_id: uuid.UUID
    name: str


_cache: dict[str, tuple[float, KeyCheck | None]] = {}


def new_secret() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def looks_like_key(value: str) -> bool:
    return value.startswith(KEY_PREFIX) and 20 <= len(value) <= 100


async def create_key(session: AsyncSession, name: str) -> tuple[ApiKey, str]:
    secret = new_secret()
    key = ApiKey(name=name.strip()[:80] or "Key", prefix=secret[:SHOWN_PREFIX], hash=digest(secret))
    session.add(key)
    await session.flush()
    return key, secret


def forget(hash_: str | None = None) -> None:
    """Drop cached results (one key's, or all), e.g. after a key is revoked."""
    if hash_ is None:
        _cache.clear()
    else:
        _cache.pop(hash_, None)


async def check(session: AsyncSession, secret: str) -> KeyCheck | None:
    """The key's identity if ``secret`` is a live key, else None."""
    if not looks_like_key(secret):
        return None
    h = digest(secret)
    now = time.monotonic()
    cached = _cache.get(h)
    if cached is not None and cached[0] > now:
        return cached[1]
    key = (
        await session.execute(select(ApiKey).where(ApiKey.hash == h, ApiKey.revoked_at.is_(None)))
    ).scalar_one_or_none()
    result = KeyCheck(key.id, key.name) if key is not None else None
    if key is not None and (key.last_used_at is None or utcnow() - key.last_used_at > TOUCH_EVERY):
        key.last_used_at = utcnow()
        await session.commit()
    if len(_cache) > 1000:
        _cache.clear()
    _cache[h] = (now + CACHE_SECONDS, result)
    return result
