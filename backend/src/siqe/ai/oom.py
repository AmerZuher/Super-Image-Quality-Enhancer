"""Out-of-memory handling shared by every GPU task.

``run_with_halving`` is the core of the fallback ladder described in
docs/architecture.md (section 5.5): try a work size, and on an OOM error free cached memory,
halve the size and retry, down to a minimum. Phase 2 builds the full ladder (tile batch,
tile size, CPU fallback) on top of this.
"""

import gc
from collections.abc import Callable

from siqe.core.logging import get_logger

log = get_logger(__name__)

_OOM_MARKERS = (
    "out of memory",
    "failed to allocate memory",
    "can't allocate memory",
    "cudnn_status_alloc_failed",
)


class InsufficientMemoryError(RuntimeError):
    """Raised when even the smallest allowed work size does not fit."""

    code = "gpu.insufficient_memory"


def is_oom_error(exc: BaseException) -> bool:
    if type(exc).__name__ == "OutOfMemoryError":
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _OOM_MARKERS)


def release_gpu_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def run_with_halving[T](
    fn: Callable[[int], T],
    size: int,
    *,
    minimum: int,
    on_fallback: Callable[[int, int], None] | None = None,
) -> tuple[T, int]:
    """Call ``fn(size)``, halving ``size`` after each OOM. Returns the result and the size that worked."""
    if size < minimum:
        raise ValueError(f"size {size} is below minimum {minimum}")
    retried_same_size = False
    while True:
        try:
            return fn(size), size
        except Exception as exc:
            if not is_oom_error(exc):
                raise
            release_gpu_memory()
            if not retried_same_size:
                # The first OOM is often fragmentation; one retry after freeing the cache is cheap.
                retried_same_size = True
                log.info("oom.retry_same_size", size=size)
                continue
            smaller = size // 2
            if smaller < minimum:
                raise InsufficientMemoryError(
                    f"Out of memory even at the minimum size ({size}); "
                    "close other GPU programs or choose a smaller job."
                ) from exc
            log.warning("oom.fallback", from_size=size, to_size=smaller)
            if on_fallback:
                on_fallback(size, smaller)
            size = smaller
            retried_same_size = False
