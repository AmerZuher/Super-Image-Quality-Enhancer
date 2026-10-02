"""The import folder: a host folder mounted read-only, checked on a schedule.

Each file is imported once. A file is only taken when its size and modification time have
stopped changing for ``import_settle_seconds``, so a photo still being copied in waits for the
next check instead of arriving half-written. Source files are never moved or deleted.
"""

import hashlib
import os
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from siqe.imaging.formats import INPUT_EXTENSIONS
from siqe.storage.store import StagedUpload

EXTENSIONS = frozenset(INPUT_EXTENSIONS.split())
CHUNK = 4 * 1024 * 1024


@dataclass(frozen=True)
class Seen:
    path: str  # relative to the import folder, with forward slashes
    size: int
    mtime: float


@dataclass(frozen=True)
class Known:
    size: int
    mtime: float
    state: str


def walk(root: Path) -> Iterator[Seen]:
    """Image files under ``root``; hidden files and folders are skipped, links aren't followed."""
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith(".") or Path(name).suffix.lower() not in EXTENSIONS:
                continue
            full = Path(folder) / name
            try:
                st = full.lstat()
            except OSError:
                continue
            if not full.is_file() or full.is_symlink():
                continue
            yield Seen(full.relative_to(root).as_posix(), st.st_size, st.st_mtime)


def decide(seen: Seen, known: Known | None, *, now: float, settle: float) -> str:
    """``record`` (remember it, wait), ``import``, or ``skip``."""
    stable = now - seen.mtime >= settle
    changed = known is None or known.size != seen.size or abs(known.mtime - seen.mtime) > 1e-6
    if known is None:
        return "import" if stable else "record"
    if changed:
        return "import" if stable else "record"
    if known.state == "waiting":
        return "import" if stable else "skip"
    return "skip"  # imported, duplicate or failed, and unchanged since


def stage(root: Path, relative: str, tmp_dir: Path, max_bytes: int) -> StagedUpload:
    """Copy one file into ``tmp/`` while hashing it."""
    src = (root / relative).resolve()
    if root.resolve() not in src.parents:
        raise ValueError("outside the import folder")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / f"import-{uuid.uuid4()}"
    digest = hashlib.sha256()
    size = 0
    try:
        with src.open("rb") as fin, dest.open("wb") as fout:
            while chunk := fin.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise OverflowError("larger than the upload limit")
                digest.update(chunk)
                fout.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return StagedUpload(path=dest, sha256=digest.hexdigest(), size_bytes=size)


def now() -> float:
    return time.time()
