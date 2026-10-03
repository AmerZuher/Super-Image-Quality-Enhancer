"""Activities for AI runs.

``run_model`` executes on the GPU worker (``siqe-gpu`` queue, one at a time) and imports
torch lazily, so the CPU worker can import this module without it. ``run_background`` and
the bookkeeping activities run on the CPU worker.
"""

import asyncio
import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from siqe.activities.threaded import ThreadProgress, run_threaded
from siqe.ai.governor import Calibration, choose_settings, cpu_settings
from siqe.ai.manifest import FACE_MODEL_ID, ModelSpec
from siqe.ai.oom import InsufficientMemoryError
from siqe.ai.plan import device_key
from siqe.ai.registry import file_path, forge_info, get_row, get_spec, require_installed, weights_path
from siqe.ai.tiling import Rect, TileSettings
from siqe.assets.records import get_asset, megapixel_limit, publish_asset
from siqe.core.config import get_settings
from siqe.core.errors import AppError
from siqe.core.logging import get_logger
from siqe.db.models import Asset, AssetStatus
from siqe.db.session import session_scope
from siqe.jobs.progress import ProgressReporter
from siqe.storage.store import StagedUpload, get_store

log = get_logger(__name__)

TORCH_ARCHS = frozenset({"spandrel", "siqe_classic", "gfpgan", "forge", "siggraph_color"})
_SAFE_NAME = re.compile(r"[^\w.\- ()×]+")


@dataclass
class AiRunRequest:
    asset_id: str
    model_id: str
    device: str = "auto"
    restore_faces: bool = False
    # Brush strokes for the eraser (siqe.ai.inpaint.Mask as a dict).
    mask: dict[str, Any] | None = None


def _paths(job_id: str) -> tuple[Path, Path]:
    tmp = get_settings().data_dir / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp / f"ai-{job_id}.raw", tmp / f"ai-{job_id}.png"


def _non_retryable(code: str, message: str, fix: str | None = None) -> ApplicationError:
    return ApplicationError(message, {"code": code, "fix": fix}, type=code, non_retryable=True)


async def _source(request: AiRunRequest) -> tuple[ModelSpec, Path, int | None, int, int, dict[str, Any]]:
    spec = get_spec(request.model_id)
    async with session_scope() as session:
        asset = await get_asset(session, uuid.UUID(request.asset_id))
        row = await require_installed(session, spec)
        src = get_store().original(asset.sha256, asset.extension)
        return spec, src, megapixel_limit(asset), asset.width, asset.height, dict(row.calibration or {})


# --------------------------------------------------------------------- GPU worker

_loaded: dict[str, Any] = {}


def _backend(spec: ModelSpec, device: str) -> Any:
    """Load (or reuse) the model. Only one stays loaded, so models never compete for VRAM."""
    from siqe.ai import runtime

    key = f"{spec.id}:{device}"
    cached = _loaded.get(key)
    if cached is not None and cached.device == device:
        return cached
    for old in list(_loaded):
        _loaded.pop(old).release()
    path = weights_path(spec)
    if spec.arch == "forge":
        model = runtime.load_forge(path, forge_info(spec.id))
    elif spec.arch == "siqe_classic":
        model = runtime.load_siqe_classic(path)
    else:
        model = runtime.load_spandrel(path)
    if model.scale != spec.scale:
        raise AppError("model.unexpected", f"{spec.name} has scale ×{model.scale}, expected ×{spec.scale}.")
    backend = runtime.TorchBackend(model, device)  # type: ignore[arg-type]
    _loaded[key] = backend
    return backend


_faces: dict[str, Any] = {}


def _face_restorer(device: str) -> Any:
    from siqe.ai import runtime

    cached = _faces.get(device)
    if cached is None:
        _faces.clear()
        spec = get_spec(FACE_MODEL_ID)
        cached = runtime.FaceRestorer(file_path(spec, 0), file_path(spec, 1), device)  # type: ignore[arg-type]
        _faces[device] = cached
    return cached


def _face_post(device: str, state: ThreadProgress, start: float, span: float) -> Any:
    from siqe.ai.faces import restore_faces

    restorer = _face_restorer(device)

    def post(rgb: Any) -> Any:
        state.update(start, "Looking for faces")
        out, _count = restore_faces(
            rgb,
            restorer.detect,
            restorer.restore,
            on_face=lambda i, n: state.update(start + span * i / n, f"Restoring face {i + 1} of {n}"),
        )
        return out

    return post


async def _faces_installed() -> None:
    async with session_scope() as session:
        await require_installed(session, get_spec(FACE_MODEL_ID))


def _resume_details() -> dict[str, Any] | None:
    details = activity.info().heartbeat_details if activity.in_activity() else ()
    last = details[-1] if details else None
    return last if isinstance(last, dict) and last.get("done") else None


async def _save_model_stats(
    spec: ModelSpec, key: str, *, calibration: Calibration | None, used: TileSettings
) -> None:
    async with session_scope() as session:
        row = await get_row(session, spec.id, for_update=True)
        if row is None:
            return
        if calibration is not None:
            row.calibration = {**(row.calibration or {}), key: calibration.to_dict()}
        row.last_settings = {**(row.last_settings or {}), key: {"tile": used.tile, "batch": used.batch}}
        row.runs = (row.runs or 0) + 1


@activity.defn
async def run_model(job_id: str, request: AiRunRequest) -> dict[str, Any]:
    spec, src, limit, width, height, calibrations = await _source(request)
    reporter = ProgressReporter(job_id, start=0.0, span=0.85)
    canvas, out_png = _paths(job_id)
    return await run_model_file(
        spec,
        src,
        out_png,
        canvas,
        device_request=request.device,
        restore_faces=request.restore_faces,
        reporter=reporter,
        limit=limit,
        size=(width, height),
        calibrations=calibrations,
    )


async def run_model_file(
    spec: ModelSpec,
    src: Path,
    out_png: Path,
    canvas: Path,
    *,
    device_request: str,
    restore_faces: bool,
    reporter: Any,
    limit: int | None,
    size: tuple[int, int],
    calibrations: dict[str, Any],
) -> dict[str, Any]:
    """Run a GPU-queue model on one file. Shared by AI Lab runs and flow steps."""
    from siqe.ai import runtime
    from siqe.ai.pipeline import run_model_on_file

    settings = get_settings()
    width, height = size
    await reporter.report(0.0, f"Loading {spec.name}", force=True)
    device = runtime.pick_device(device_request)
    if spec.arch == "gfpgan":
        return await _run_faces(out_png, spec, src, limit, device, reporter)
    if spec.arch == "siggraph_color":
        return await _run_colorize(out_png, spec, src, limit, device, reporter)
    if restore_faces:
        await _faces_installed()
    try:
        backend = await asyncio.to_thread(_backend, spec, device)
    except (AppError, runtime.ModelLoadError) as exc:
        message = exc.detail if isinstance(exc, AppError) else str(exc)
        raise _non_retryable(
            "model.load_failed", message, "Remove the model in AI Lab and download it again."
        ) from exc
    name = runtime.device_name(device)
    key = device_key(device, name)
    multiple = backend.model.multiple

    calibration: Calibration | None = None
    resume = _resume_details()
    done: set[Rect] = set()
    if resume:
        tile = TileSettings(
            tile=int(resume["tile"]), batch=int(resume["batch"]), context=spec.context, multiple=multiple
        )
        done = {Rect.from_list(r) for r in resume["done"]}
    elif device == "cuda":
        calibration = Calibration.from_dict(calibrations.get(key))
        fresh = calibration is None
        if calibration is None:
            await reporter.report(0.0, f"Measuring memory use on the {name} (first run)", force=True)
            calibration = await asyncio.to_thread(
                runtime.calibrate, backend, context=spec.context, multiple=multiple
            )
        budget = runtime.budget_bytes(settings.gpu_vram_reserve_mb)
        tile = choose_settings(
            calibration, budget, width=width, height=height, context=spec.context, multiple=multiple
        )
        if not fresh:
            calibration = None  # nothing new to store
    else:
        tile = cpu_settings(width=width, height=height, context=spec.context, multiple=multiple)

    def work(state: ThreadProgress) -> Any:
        return run_model_on_file(
            src,
            out_png,
            canvas,
            backend=backend,
            scale=spec.scale,
            channels=spec.channels,
            settings=tile,
            done=done,
            on_progress=lambda f, m, d: state.update(f, m, d),
            should_stop=state.cancelled.is_set,
            max_megapixels=limit,
            post=_face_post(device, state, 0.9, 0.05) if restore_faces else None,
        )

    try:
        out = await run_threaded(work, reporter)
    except InsufficientMemoryError as exc:
        raise _non_retryable(
            "gpu.insufficient_memory", str(exc), "Close other programs using the GPU, or try a smaller image."
        ) from exc
    except AppError as exc:
        raise _non_retryable(exc.code, exc.detail, exc.fix) from exc
    finally:
        backend.release()
    if backend.device != device:
        _loaded.clear()  # it fell back to the CPU; load fresh next time
    await _save_model_stats(spec, key, calibration=calibration, used=out.tiled.settings)
    return {
        "path": str(out.path),
        "width": out.width,
        "height": out.height,
        "device": backend.device,
        "device_name": name if backend.device == device else "CPU",
        "tile": out.tiled.settings.tile,
        "batch": out.tiled.settings.batch,
        "tiles": out.tiled.tiles_run,
        "seconds": round(out.tiled.seconds, 1),
        "fallbacks": [s.detail for s in out.tiled.steps],
        "restore_faces": restore_faces,
        "nonfinite": out.tiled.nonfinite,
    }


async def _run_faces(
    out_png: Path, spec: ModelSpec, src: Path, limit: int | None, device: str, reporter: Any
) -> dict[str, Any]:
    from siqe.ai import runtime
    from siqe.ai.faces import restore_faces
    from siqe.ai.pipeline import run_post_on_file

    loop = asyncio.get_running_loop()
    start = loop.time()
    count = 0

    def work(state: ThreadProgress) -> tuple[int, int]:
        nonlocal count
        restorer = _face_restorer(device)

        def post(rgb: Any) -> Any:
            nonlocal count
            state.update(0.1, "Looking for faces")
            out, count = restore_faces(
                rgb,
                restorer.detect,
                restorer.restore,
                on_face=lambda i, n: state.update(0.1 + 0.8 * i / n, f"Restoring face {i + 1} of {n}"),
            )
            return out

        return run_post_on_file(src, out_png, post, max_megapixels=limit)

    try:
        width, height = await run_threaded(work, reporter)
    except (AppError, runtime.ModelLoadError) as exc:
        message = exc.detail if isinstance(exc, AppError) else str(exc)
        raise _non_retryable(getattr(exc, "code", "model.load_failed"), message) from exc
    return {
        "path": str(out_png),
        "width": width,
        "height": height,
        "device": device,
        "device_name": runtime.device_name(device),
        "tile": None,
        "batch": None,
        "tiles": 1,
        "seconds": round(loop.time() - start, 1),
        "fallbacks": [],
        "faces": count,
    }


# --------------------------------------------------------------------- CPU worker


@activity.defn
async def run_background(job_id: str, request: AiRunRequest) -> dict[str, Any]:
    """Models that run on the CPU worker (ONNX Runtime): background removal, deblur, erase."""
    spec, src, limit, _, _, _ = await _source(request)
    _, out_png = _paths(job_id)
    reporter = ProgressReporter(job_id, start=0.0, span=0.85)
    return await run_cpu_file(spec, src, out_png, reporter=reporter, limit=limit, mask=request.mask)


async def run_cpu_file(
    spec: ModelSpec,
    src: Path,
    out_png: Path,
    *,
    reporter: Any,
    limit: int | None,
    mask: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a CPU-worker model on one file. Shared by AI Lab runs and flow steps."""
    if spec.arch == "onnx":
        return await _run_onnx_tiled(spec, src, out_png, reporter=reporter, limit=limit)
    if spec.arch == "lama_onnx":
        if not mask:
            raise _non_retryable(
                "erase.mask_required", "Paint over what to erase first.", "Use the brush in AI Lab."
            )
        return await _run_erase(spec, src, out_png, mask, reporter=reporter, limit=limit)
    return await run_background_file(spec, src, out_png, reporter=reporter, limit=limit)


def _single_pass(path: Path, width: int, height: int, seconds: float) -> dict[str, Any]:
    return {
        "path": str(path),
        "width": width,
        "height": height,
        "device": "cpu",
        "device_name": "CPU",
        "tile": None,
        "batch": None,
        "tiles": 1,
        "seconds": round(seconds, 1),
        "fallbacks": [],
    }


async def _run_onnx_tiled(
    spec: ModelSpec, src: Path, out_png: Path, *, reporter: Any, limit: int | None
) -> dict[str, Any]:
    """An image-to-image ONNX model, tile by tile on the CPU (the same tiler as GPU models)."""
    from siqe.ai.governor import cpu_settings, min_input_settings
    from siqe.ai.onnx_model import OnnxBackend
    from siqe.ai.pipeline import run_model_on_file
    from siqe.imaging.io import inspect as inspect_image

    info = await asyncio.to_thread(inspect_image, src, max_megapixels=limit)
    width, height = info.oriented_size
    tile = min_input_settings(
        cpu_settings(width=width, height=height, context=spec.context, multiple=spec.multiple), spec.min_input
    )
    backend = await asyncio.to_thread(OnnxBackend, weights_path(spec))
    canvas = out_png.with_suffix(".raw")
    resume = _resume_details()
    done = {Rect.from_list(r) for r in resume["done"]} if resume else set()

    def work(state: ThreadProgress) -> Any:
        return run_model_on_file(
            src,
            out_png,
            canvas,
            backend=backend,
            scale=spec.scale,
            channels=spec.channels,
            settings=tile,
            done=done,
            on_progress=lambda f, m, d: state.update(f, m, d),
            should_stop=state.cancelled.is_set,
            max_megapixels=limit,
        )

    try:
        out = await run_threaded(work, reporter)
    except AppError as exc:
        raise _non_retryable(exc.code, exc.detail, exc.fix) from exc
    return {
        "path": str(out.path),
        "width": out.width,
        "height": out.height,
        "device": "cpu",
        "device_name": "CPU",
        "tile": out.tiled.settings.tile,
        "batch": out.tiled.settings.batch,
        "tiles": out.tiled.tiles_run,
        "seconds": round(out.tiled.seconds, 1),
        "fallbacks": [s.detail for s in out.tiled.steps],
        "nonfinite": out.tiled.nonfinite,
    }


async def _run_erase(
    spec: ModelSpec, src: Path, out_png: Path, mask: dict[str, Any], *, reporter: Any, limit: int | None
) -> dict[str, Any]:
    from pydantic import ValidationError

    from siqe.ai.inpaint import Mask, inpaint_file, lama_runner
    from siqe.ai.onnx_model import session

    try:
        strokes = Mask.model_validate(mask)
    except ValidationError as exc:
        raise _non_retryable(
            "erase.bad_mask", "The painted area couldn't be read.", "Paint it again."
        ) from exc
    run = lama_runner(await asyncio.to_thread(session, weights_path(spec)))
    start = asyncio.get_running_loop().time()

    def work(state: ThreadProgress) -> tuple[int, int]:
        return inpaint_file(
            src, out_png, strokes, run, on_progress=lambda f, m: state.update(f, m), max_megapixels=limit
        )

    try:
        width, height = await run_threaded(work, reporter)
    except AppError as exc:
        raise _non_retryable(exc.code, exc.detail, exc.fix) from exc
    return _single_pass(out_png, width, height, asyncio.get_running_loop().time() - start)


async def _run_colorize(
    out_png: Path, spec: ModelSpec, src: Path, limit: int | None, device: str, reporter: Any
) -> dict[str, Any]:
    from siqe.ai import runtime
    from siqe.ai.colorize import colorize_file

    try:
        predict = await asyncio.to_thread(runtime.load_colorizer, weights_path(spec), device)  # type: ignore[arg-type]
    except runtime.ModelLoadError as exc:
        raise _non_retryable(
            "model.load_failed", str(exc), "Remove the model in AI Lab and download it again."
        ) from exc
    start = asyncio.get_running_loop().time()

    def work(state: ThreadProgress) -> tuple[int, int]:
        return colorize_file(
            src, out_png, predict, on_progress=lambda f, m: state.update(f, m), max_megapixels=limit
        )

    try:
        width, height = await run_threaded(work, reporter)
    except AppError as exc:
        raise _non_retryable(exc.code, exc.detail, exc.fix) from exc
    result = _single_pass(out_png, width, height, asyncio.get_running_loop().time() - start)
    result.update(device=device, device_name=runtime.device_name(device), restore_faces=False, nonfinite=0)
    return result


async def run_background_file(
    spec: ModelSpec, src: Path, out_png: Path, *, reporter: Any, limit: int | None
) -> dict[str, Any]:
    """Background removal (ONNX, CPU) on one file. Shared by AI Lab runs and flow steps."""
    from siqe.ai.background import remove_background

    loop = asyncio.get_running_loop()
    start = loop.time()

    def work(state: ThreadProgress) -> tuple[int, int]:
        return remove_background(
            src, out_png, weights_path(spec), on_progress=state.update, max_megapixels=limit
        )

    try:
        width, height = await run_threaded(work, reporter)
    except AppError as exc:
        raise _non_retryable(exc.code, exc.detail, exc.fix) from exc
    return {
        "path": str(out_png),
        "width": width,
        "height": height,
        "device": "cpu",
        "device_name": "CPU",
        "tile": None,
        "batch": None,
        "tiles": 1,
        "seconds": round(loop.time() - start, 1),
        "fallbacks": [],
    }


def derived_name(original: str, spec: ModelSpec) -> str:
    stem = Path(original).stem or "image"
    if spec.task == "upscale":
        label = f"{stem} ×{spec.scale} {spec.name.split(' ×')[0]}"
    elif spec.task == "background":
        label = f"{stem} cutout"
    elif spec.task == "denoise":
        label = f"{stem} denoised"
    elif spec.task == "deblur":
        label = f"{stem} deblurred"
    elif spec.task == "colorize":
        label = f"{stem} colorized"
    elif spec.task == "erase":
        label = f"{stem} retouched"
    else:
        label = f"{stem} faces restored"
    return (_SAFE_NAME.sub("_", label).strip(" .") or "image")[:190] + ".png"


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


@activity.defn
async def register_result(job_id: str, request: AiRunRequest, result: dict[str, Any]) -> str:
    """Store the result as a new image linked to its source. Returns the new asset id."""
    from sqlalchemy import select

    spec = get_spec(request.model_id)
    store = get_store()
    path = Path(result["path"])
    sha, size = await asyncio.to_thread(_hash, path)
    async with session_scope() as session:
        existing = (await session.execute(select(Asset).where(Asset.sha256 == sha))).scalar_one_or_none()
        if existing is not None:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            return str(existing.id)
        parent = await get_asset(session, uuid.UUID(request.asset_id))
        await asyncio.to_thread(store.commit, StagedUpload(path, sha, size), ".png")
        asset = Asset(
            sha256=sha,
            original_name=derived_name(parent.original_name, spec),
            extension=".png",
            format="png",
            width=int(result["width"]),
            height=int(result["height"]),
            bit_depth=parent.bit_depth,
            has_alpha=parent.has_alpha or spec.task == "background",
            size_bytes=size,
            status=AssetStatus.processing,
            exif={},
            has_gps=False,
            edits={},
            parent_id=parent.id,
            derivation={
                "job_id": job_id,
                "model_id": spec.id,
                "model_name": spec.name,
                "task": spec.task,
                "scale": spec.scale,
                **{k: v for k, v in result.items() if k != "path"},
            },
        )
        session.add(asset)
        await publish_asset(session, asset)
        return str(asset.id)


@activity.defn
async def discard_run_files(job_id: str) -> None:
    for path in _paths(job_id):
        await asyncio.to_thread(path.unlink, missing_ok=True)
