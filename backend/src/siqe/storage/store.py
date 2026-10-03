"""Files on the data volume, laid out by content hash.

Uploads are streamed to ``tmp/`` while being hashed, never held in memory, then moved into
place with an atomic rename. Paths come from hashes and ids, never from user file names, so
a crafted name can't escape the data directory.
"""

import asyncio
import hashlib
import shutil
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from siqe.core.config import Settings, get_settings
from siqe.core.errors import AppError
from siqe.system.resources import disk_info, disk_reserve

FLUSH_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class StagedUpload:
    path: Path
    sha256: str
    size_bytes: int


class MediaStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.media = root / "media"
        self.tmp = root / "tmp"

    # ------------------------------------------------------------------- locations

    def original(self, sha256: str, extension: str) -> Path:
        return self.media / "originals" / sha256[:2] / sha256[2:4] / f"{sha256}{extension}"

    def previews(self, asset_id: uuid.UUID) -> Path:
        return self.media / "previews" / str(asset_id)

    def renditions(self, asset_id: uuid.UUID) -> Path:
        return self.media / "renditions" / str(asset_id)

    def rendition(self, asset_id: uuid.UUID, rendition_id: uuid.UUID, extension: str) -> Path:
        return self.renditions(asset_id) / f"{rendition_id}{extension}"

    def inside(self, base: Path, relative: str) -> Path:
        """Resolve ``relative`` under ``base``, refusing anything that escapes it."""
        target = (base / relative).resolve()
        if base.resolve() not in target.parents and target != base.resolve():
            raise AppError("media.not_found", "No such file.", status=404, title="Not found")
        return target

    # ---------------------------------------------------------------------- uploads

    def ensure_space(self, settings: Settings, needed_bytes: int = 0) -> None:
        info = disk_info(self.root)
        reserve = disk_reserve(info.total_bytes, settings.min_free_disk_ratio)
        if info.free_bytes - needed_bytes < reserve:
            raise AppError(
                "disk.insufficient_space",
                f"Only {info.free_bytes / 1e9:.1f} GB of disk is free and {reserve / 1e9:.1f} GB is kept "
                "free, so new files are paused.",
                status=507,
                title="Not enough disk space",
                fix="Delete images or exports you no longer need, or free space on the data volume.",
            )

    async def receive(self, chunks: AsyncIterator[bytes], max_bytes: int) -> StagedUpload:
        self.tmp.mkdir(parents=True, exist_ok=True)
        path = self.tmp / f"upload-{uuid.uuid4()}"
        digest = hashlib.sha256()
        size = 0
        pending = bytearray()
        handle = await asyncio.to_thread(path.open, "wb")
        try:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise AppError(
                        "upload.too_large",
                        f"The file is larger than the {max_bytes // (1024 * 1024):,} MB upload limit.",
                        status=413,
                        title="File too large",
                        fix="Raise SIQE_MAX_UPLOAD_MB in .env, or upload a smaller file.",
                    )
                digest.update(chunk)
                pending.extend(chunk)
                if len(pending) >= FLUSH_BYTES:
                    await asyncio.to_thread(handle.write, bytes(pending))
                    pending.clear()
            if pending:
                await asyncio.to_thread(handle.write, bytes(pending))
        except BaseException:
            handle.close()
            path.unlink(missing_ok=True)
            raise
        handle.close()
        if size == 0:
            path.unlink(missing_ok=True)
            raise AppError("upload.empty", "The upload contained no data.", status=400, title="Empty upload")
        return StagedUpload(path=path, sha256=digest.hexdigest(), size_bytes=size)

    def commit(self, staged: StagedUpload, extension: str) -> Path:
        target = self.original(staged.sha256, extension)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            staged.path.unlink(missing_ok=True)
        else:
            staged.path.replace(target)
        return target

    # --------------------------------------------------------------------- removal

    def remove_asset(self, asset_id: uuid.UUID, sha256: str, extension: str) -> None:
        self.original(sha256, extension).unlink(missing_ok=True)
        shutil.rmtree(self.previews(asset_id), ignore_errors=True)
        shutil.rmtree(self.renditions(asset_id), ignore_errors=True)

    def clean_tmp(self, older_than_seconds: float = 6 * 3600) -> int:
        """Delete abandoned temporary files (crashed uploads or exports). Returns the count."""
        import time

        if not self.tmp.exists():
            return 0
        cutoff = time.time() - older_than_seconds
        removed = 0
        for entry in self.tmp.iterdir():
            try:
                if entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
                    removed += 1
            except OSError:
                continue
        return removed


def get_store() -> MediaStore:
    return MediaStore(get_settings().data_dir)
