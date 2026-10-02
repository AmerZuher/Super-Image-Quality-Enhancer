"""Face counting for the Library, on the GPU queue (the detector needs PyTorch)."""

import asyncio
from typing import Any

from temporalio import activity

from siqe.core.logging import get_logger
from siqe.db.session import session_scope
from siqe.library import faces

log = get_logger(__name__)

_detector: dict[str, Any] = {}


def _load() -> Any:
    from siqe.ai import runtime
    from siqe.ai.manifest import FACE_MODEL_ID
    from siqe.ai.registry import file_path, get_spec

    device = runtime.pick_device("auto")
    cached = _detector.get(device)
    if cached is None:
        _detector.clear()
        cached = runtime.FaceDetector(file_path(get_spec(FACE_MODEL_ID), 1), device)
        _detector[device] = cached
    return cached


@activity.defn
async def count_faces_batch() -> dict[str, Any]:
    """Count faces in the next batch of images that haven't been counted."""
    if not faces.detector_ready():
        return {"done": 0, "remaining": 0, "ready": False}
    async with session_scope() as session:
        batch = await faces.next_batch(session)
    if not batch:
        return {"done": 0, "remaining": 0, "ready": True}
    detector = await asyncio.to_thread(_load)
    counts = {}
    for index, (asset_id, preview) in enumerate(batch):
        activity.heartbeat(index)
        try:
            counts[asset_id] = await asyncio.to_thread(faces.count, detector.detect, preview)
        except Exception as exc:
            if "out of memory" in str(exc).lower():
                raise
            log.warning("faces.unreadable", asset_id=str(asset_id), error=str(exc))
            counts[asset_id] = faces.UNREADABLE
    async with session_scope() as session:
        await faces.save(session, counts)
        remaining = await faces.count_pending(session)
    return {"done": len(counts), "remaining": remaining, "ready": True}
