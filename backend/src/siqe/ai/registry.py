"""Installed models: where their files live, their state, and downloading them.

Downloads stream to ``tmp/`` while being hashed, resume from a partial file after a dropped
connection (HTTP Range), and only move into ``models/<id>/`` once size and SHA-256 match the
manifest. Nothing is ever loaded from an unverified file.
"""

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from siqe.ai.convert import convert
from siqe.ai.manifest import MODELS, MODELS_BY_ID, TASK_LABELS, ModelFile, ModelSpec
from siqe.core.config import get_settings
from siqe.core.errors import AppError, NotFoundError
from siqe.db.models import AiModel, ModelStatus
from siqe.events.bus import publish

MODEL_EVENT = "model.updated"
CHUNK = 1024 * 1024


def get_spec(model_id: str) -> ModelSpec:
    spec = MODELS_BY_ID.get(model_id) or forge_spec(model_id)
    if spec is None:
        raise NotFoundError("model.not_found", f"No model called '{model_id}'.", title="Model not found")
    return spec


# ------------------------------------------------------------------- models from Forge

FORGE_FILE = "forge.json"
FORGE_WEIGHTS = "model.safetensors"
_forge_cache: dict[str, tuple[float, ModelSpec, dict[str, Any]]] = {}


def _read_forge(model_id: str) -> tuple[ModelSpec, dict[str, Any]] | None:
    """A published Forge model, from the descriptor next to its weights on the data volume.

    The descriptor lives with the files, so the API and both workers see a model as soon as it
    is published, and removing the folder removes the model.
    """
    if not model_id.startswith("forge-") or "/" in model_id or ".." in model_id:
        return None
    path = models_root() / model_id / FORGE_FILE
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _forge_cache.pop(model_id, None)
        return None
    cached = _forge_cache.get(model_id)
    if cached and cached[0] == mtime:
        return cached[1], cached[2]
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        spec = ModelSpec(
            id=model_id,
            name=str(info["name"]),
            task="upscale" if int(info["scale"]) > 1 else "denoise",
            arch="forge",
            scale=int(info["scale"]),
            summary=str(info.get("summary", "Trained in Forge.")),
            license="Your own",
            license_url="",
            homepage="",
            files=(ModelFile(FORGE_WEIGHTS, "", str(info["sha256"]), int(info["size"])),),
            context=int(info.get("context", 24)),
            channels="y" if info.get("color") == "y" else "rgb",
            speed="fast",
            tags=("forge",),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    _forge_cache[model_id] = (mtime, spec, info)
    return spec, info


def forge_spec(model_id: str) -> ModelSpec | None:
    found = _read_forge(model_id)
    return found[0] if found else None


def forge_info(model_id: str) -> dict[str, Any]:
    found = _read_forge(model_id)
    return found[1] if found else {}


def forge_specs() -> list[ModelSpec]:
    root = models_root()
    if not root.is_dir():
        return []
    found = [_read_forge(p.parent.name) for p in sorted(root.glob(f"forge-*/{FORGE_FILE}"))]
    return [f[0] for f in found if f]


def models_root() -> Path:
    return get_settings().data_dir / "models"


def model_dir(spec: ModelSpec) -> Path:
    return models_root() / spec.id


def weights_path(spec: ModelSpec) -> Path:
    return model_dir(spec) / spec.weights.stored_name


def file_path(spec: ModelSpec, index: int) -> Path:
    return model_dir(spec) / spec.files[index].stored_name


def files_present(spec: ModelSpec) -> bool:
    return all((model_dir(spec) / f.stored_name).is_file() for f in spec.files)


def status_of(spec: ModelSpec, row: AiModel | None) -> str:
    if row is None:
        return "available"
    if row.status == ModelStatus.installed and not files_present(spec):
        return "available"  # files were removed from the data volume
    return row.status.value


def model_to_dict(spec: ModelSpec, row: AiModel | None) -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "task": spec.task,
        "task_label": TASK_LABELS[spec.task],
        "arch": spec.arch,
        "scale": spec.scale,
        "summary": spec.summary,
        "license": spec.license,
        "license_url": spec.license_url,
        "homepage": spec.homepage,
        "size_bytes": spec.size_bytes,
        "channels": spec.channels,
        "speed": spec.speed,
        "recommended": spec.recommended,
        "tags": list(spec.tags),
        "status": status_of(spec, row),
        "job_id": str(row.job_id) if row and row.job_id else None,
        "error": row.error if row else None,
        "installed_at": row.installed_at.isoformat() if row and row.installed_at else None,
        "runs": row.runs if row else 0,
        "calibrated": sorted((row.calibration or {}).keys()) if row else [],
        "source": "forge" if spec.arch == "forge" else "catalog",
        "benchmark": forge_info(spec.id).get("benchmark") if spec.arch == "forge" else None,
    }


async def get_row(session: AsyncSession, model_id: str, *, for_update: bool = False) -> AiModel | None:
    stmt = select(AiModel).where(AiModel.id == model_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def all_rows(session: AsyncSession) -> dict[str, AiModel]:
    rows = (await session.execute(select(AiModel))).scalars()
    return {r.id: r for r in rows}


async def publish_model(session: AsyncSession, spec: ModelSpec, row: AiModel | None) -> None:
    await session.flush()
    await publish(session, MODEL_EVENT, model_to_dict(spec, row))


async def require_installed(session: AsyncSession, spec: ModelSpec) -> AiModel:
    row = await get_row(session, spec.id)
    if row is None or status_of(spec, row) != "installed":
        raise AppError(
            "model.not_installed",
            f"{spec.name} isn't downloaded yet.",
            status=409,
            title="Model not installed",
            fix="Download it in AI Lab, then run again.",
        )
    return row


def catalog() -> tuple[ModelSpec, ...]:
    return (*MODELS, *forge_specs())


# ------------------------------------------------------------------------- download


class DownloadError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            "model.download_failed",
            detail,
            status=502,
            title="Download failed",
            fix="Check the internet connection and that github.com is reachable, then try again.",
        )


def _hash_file(path: Path) -> tuple[Any, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest, size


def _verified(path: Path, f: ModelFile) -> bool:
    if not path.is_file() or path.stat().st_size != f.size:
        return False
    digest, _ = _hash_file(path)
    return bool(digest.hexdigest() == f.sha256)


def download_file(
    client: httpx.Client,
    f: ModelFile,
    dest: Path,
    tmp_dir: Path,
    *,
    on_bytes: Callable[[int], None] = lambda n: None,
    should_stop: Callable[[], bool] = lambda: False,
) -> Path:
    """Download ``f`` to ``dest`` (verified), resuming from ``tmp_dir`` if a partial file exists."""
    if _verified(dest, f):
        on_bytes(f.size)
        return dest
    tmp_dir.mkdir(parents=True, exist_ok=True)
    partial = tmp_dir / f"model-{f.sha256[:16]}.partial"
    digest, done = _hash_file(partial) if partial.exists() else (hashlib.sha256(), 0)
    if done > f.size:
        partial.unlink()
        digest, done = hashlib.sha256(), 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    try:
        with client.stream("GET", f.url, headers=headers) as response:
            if response.status_code == 200 and done:
                digest, done = hashlib.sha256(), 0  # server ignored Range: start over
                partial.unlink(missing_ok=True)
            elif response.status_code not in (200, 206):
                raise DownloadError(f"The server answered {response.status_code} for {f.name}.")
            with partial.open("ab") as handle:
                for chunk in response.iter_bytes():  # as received, so a drop keeps every byte
                    if should_stop():
                        raise InterruptedError("cancelled")
                    handle.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    on_bytes(done)
    except httpx.HTTPError as exc:
        # Keep the partial file: the activity's retry resumes from it.
        raise DownloadError(f"The download of {f.name} was interrupted ({type(exc).__name__}).") from exc
    if done != f.size or digest.hexdigest() != f.sha256:
        partial.unlink(missing_ok=True)
        raise AppError(
            "model.checksum_mismatch",
            f"{f.name} didn't match its published checksum, so it was deleted.",
            status=502,
            title="Download corrupted",
            fix="Try again. If it keeps happening, the file on the server has changed.",
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(partial), dest)
    return dest


def install_files(
    spec: ModelSpec,
    client: httpx.Client,
    *,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    should_stop: Callable[[], bool] = lambda: False,
) -> Path:
    """Download (and convert) every file of ``spec``. Returns the weights path."""
    settings = get_settings()
    target = model_dir(spec)
    total = spec.size_bytes
    finished = 0
    for f in spec.files:
        final = target / f.stored_name
        if f.convert_to and final.is_file():
            finished += f.size
            on_progress(finished, total)
            continue
        base = finished

        def on_bytes(n: int, base: int = base) -> None:
            on_progress(base + n, total)

        raw = download_file(
            client, f, target / f.name, settings.data_dir / "tmp", on_bytes=on_bytes, should_stop=should_stop
        )
        if f.convert_to:
            staging = final.with_name(final.name + ".partial")
            convert(spec.arch, raw, staging)
            staging.chmod(0o644)  # safetensors writes 0600; the GPU worker may be another user
            staging.replace(final)
            raw.unlink()
        finished += f.size
    on_progress(total, total)
    return weights_path(spec)


def remove_files(spec: ModelSpec) -> None:
    shutil.rmtree(model_dir(spec), ignore_errors=True)
