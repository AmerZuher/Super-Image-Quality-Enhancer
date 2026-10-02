import numpy as np
import pytest

from siqe.ai.oom import InsufficientMemoryError
from siqe.ai.tiling import (
    Cancelled,
    Rect,
    TileSettings,
    pad_hwc,
    padded_size,
    plan_cores,
    run_tiled,
    window_for,
)


class OutOfMemoryError(RuntimeError):
    """Same class name as torch.OutOfMemoryError."""


class BlurUpscale:
    """A tiny stand-in model: 3×3 box blur (receptive radius 1), then nearest ×scale."""

    def __init__(self, scale: int = 2, capacity_px: int | None = None, device: str = "cuda") -> None:
        self.scale = scale
        self.capacity_px = capacity_px
        self.device = device
        self.calls: list[tuple[int, ...]] = []

    def forward(self, batch: np.ndarray) -> np.ndarray:
        self.calls.append(batch.shape)
        if self.device != "cpu" and self.capacity_px and batch.size // batch.shape[1] > self.capacity_px:
            raise OutOfMemoryError("CUDA out of memory. Tried to allocate 1.00 GiB")
        padded = np.pad(batch, ((0, 0), (0, 0), (1, 1), (1, 1)))
        h, w = batch.shape[2:]
        blurred = sum(padded[:, :, dy : dy + h, dx : dx + w] for dy in range(3) for dx in range(3)) / 9
        return blurred.repeat(self.scale, axis=2).repeat(self.scale, axis=3)

    def to_cpu(self) -> None:
        self.device = "cpu"

    def release(self) -> None:
        pass


def image(h: int = 53, w: int = 71, c: int = 3) -> np.ndarray:
    rng = np.random.default_rng(3)
    return rng.random((h, w, c), dtype=np.float32)


def run(src: np.ndarray, settings: TileSettings, model: BlurUpscale, **kwargs):  # type: ignore[no-untyped-def]
    h, w, _ = src.shape
    out = np.zeros((h * model.scale, w * model.scale, src.shape[2]), np.float32)

    def read(r: Rect) -> np.ndarray:
        return src[r.y : r.y + r.h, r.x : r.x + r.w]

    def write(r: Rect, tile: np.ndarray) -> None:
        s = model.scale
        out[r.y * s : (r.y + r.h) * s, r.x * s : (r.x + r.w) * s] = tile

    result = run_tiled(
        width=w,
        height=h,
        scale=model.scale,
        read=read,
        write=write,
        backend=model,
        settings=settings,
        **kwargs,
    )
    return out, result


def test_plan_covers_the_image_exactly_once() -> None:
    cores = plan_cores(71, 53, 16)
    coverage = np.zeros((53, 71), int)
    for r in cores:
        coverage[r.y : r.y + r.h, r.x : r.x + r.w] += 1
    assert (coverage == 1).all()
    assert len(cores) == 5 * 4


def test_window_places_the_core_after_context_and_border_padding() -> None:
    size = padded_size(16, 4, multiple=8)
    assert size == 24
    first = window_for(Rect(y=0, x=0, h=16, w=16), 71, 53, 4, size)
    assert first.source == Rect(y=0, x=0, h=20, w=20)
    assert first.core_offset == (4, 4)
    last = window_for(Rect(y=48, x=64, h=5, w=7), 71, 53, 4, size)
    assert last.core_offset == (4, 4)
    assert pad_hwc(np.zeros((last.source.h, last.source.w, 3)), last.pad).shape == (24, 24, 3)


def test_single_pixel_regions_pad_without_errors() -> None:
    assert pad_hwc(np.ones((1, 1, 1)), (3, 3, 4, 4)).shape == (8, 8, 1)


@pytest.mark.parametrize(("tile", "batch"), [(16, 1), (16, 4), (32, 3), (200, 1)])
def test_tiled_output_equals_whole_image_output(tile: int, batch: int) -> None:
    src = image()
    whole, _ = run(src, TileSettings(tile=512, batch=1, context=2), BlurUpscale())
    tiled, result = run(src, TileSettings(tile=tile, batch=batch, context=2), BlurUpscale())
    np.testing.assert_allclose(tiled, whole, atol=1e-6)
    assert result.steps == []


def test_inputs_are_padded_to_a_multiple() -> None:
    model = BlurUpscale()
    run(image(), TileSettings(tile=16, batch=2, context=3, multiple=8), model)
    assert {shape[2:] for shape in model.calls} == {(24, 24)}


def test_oom_walks_the_ladder_and_still_matches() -> None:
    src = image(64, 64)
    whole, _ = run(src, TileSettings(tile=512, batch=1, context=2), BlurUpscale())
    # Fits only one 20×20 input at a time: batch 4 → 2 → 1, then tile 32 → 16.
    model = BlurUpscale(capacity_px=20 * 20)
    tiled, result = run(src, TileSettings(tile=32, batch=4, context=2, min_tile=8), model)
    np.testing.assert_allclose(tiled, whole, atol=1e-6)
    kinds = [s.kind for s in result.steps]
    assert kinds == ["retry", "batch", "retry", "batch", "retry", "tile"]
    assert result.settings.tile == 16 and result.settings.batch == 1
    assert result.device == "cuda"


def test_falls_back_to_cpu_when_the_smallest_tile_does_not_fit() -> None:
    src = image(32, 32)
    model = BlurUpscale(capacity_px=1)
    out, result = run(src, TileSettings(tile=16, batch=1, context=2, min_tile=16), model)
    assert [s.kind for s in result.steps] == ["retry", "cpu"]
    assert result.device == "cpu"
    whole, _ = run(src, TileSettings(tile=512, batch=1, context=2), BlurUpscale())
    np.testing.assert_allclose(out, whole, atol=1e-6)


def test_gives_up_with_a_typed_error_on_cpu() -> None:
    model = BlurUpscale(capacity_px=1, device="cpu")

    def oom(batch: np.ndarray) -> np.ndarray:
        raise OutOfMemoryError("DefaultCPUAllocator: can't allocate memory")

    model.forward = oom  # type: ignore[method-assign]
    with pytest.raises(InsufficientMemoryError):
        run(image(16, 16), TileSettings(tile=16, batch=1, context=2, min_tile=16), model)


def test_other_errors_are_not_swallowed() -> None:
    model = BlurUpscale()

    def broken(batch: np.ndarray) -> np.ndarray:
        raise ValueError("bad weights")

    model.forward = broken  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="bad weights"):
        run(image(16, 16), TileSettings(tile=16, batch=1, context=2), model)


def test_resumes_without_redoing_finished_cores() -> None:
    src = image(48, 48)
    first = BlurUpscale()
    seen: list[set[Rect]] = []

    def stop_after_two() -> bool:
        return len(first.calls) >= 2

    with pytest.raises(Cancelled):
        run(
            src,
            TileSettings(tile=16, batch=1, context=2),
            first,
            on_progress=lambda f, done, s: seen.append(set(done)),
            should_stop=stop_after_two,
        )
    done = seen[-1]
    assert len(done) == 2
    second = BlurUpscale()
    _, result = run(src, TileSettings(tile=16, batch=1, context=2), second, done=done)
    assert result.tiles_run == 9 - 2
    # Cores finished with bigger tiles stay done after a tile-size change.
    third = BlurUpscale()
    _, result = run(src, TileSettings(tile=8, batch=1, context=2), third, done=done)
    assert result.tiles_run == 36 - 2 * 4


def test_progress_reaches_one() -> None:
    fractions: list[float] = []
    run(
        image(),
        TileSettings(tile=16, batch=2, context=2),
        BlurUpscale(),
        on_progress=lambda f, d, s: fractions.append(f),
    )
    assert fractions[-1] == pytest.approx(1.0)
    assert fractions == sorted(fractions)


def test_nan_outputs_are_replaced_and_counted() -> None:
    model = BlurUpscale()
    real = model.forward

    def leaky(batch: np.ndarray) -> np.ndarray:
        out = real(batch)
        out[0, 0, 5, 5] = np.nan
        return out

    model.forward = leaky  # type: ignore[method-assign]
    out, result = run(image(16, 16), TileSettings(tile=16, batch=1, context=2), model)
    assert result.nonfinite == 1
    assert np.isfinite(out).all()
