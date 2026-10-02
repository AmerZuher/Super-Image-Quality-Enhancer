from pathlib import Path

import numpy as np
import pytest
import pyvips

from siqe.ai.pipeline import rgb_to_ycbcr, run_model_on_file, ycbcr_to_rgb
from siqe.ai.tiling import Cancelled, Rect, TileSettings


class Nearest:
    """Stand-in model: nearest-neighbour ×scale, optionally scaled brightness."""

    def __init__(self, scale: int, gain: float = 1.0) -> None:
        self.scale = scale
        self.gain = gain
        self.device = "cpu"
        self.calls = 0

    def forward(self, batch: np.ndarray) -> np.ndarray:
        self.calls += 1
        return (batch * self.gain).repeat(self.scale, axis=2).repeat(self.scale, axis=3)

    def to_cpu(self) -> None:
        pass

    def release(self) -> None:
        pass


def photo(tmp_path: Path, *, alpha: bool = False, depth: int = 8, size: tuple[int, int] = (37, 29)) -> Path:
    w, h = size
    xy = pyvips.Image.xyz(w, h)
    rgb = (xy[0] * (255 / w)).bandjoin([xy[1] * (255 / h), (xy[0] + xy[1]) * (127 / (w + h))])
    if alpha:
        rgb = rgb.bandjoin((xy[0] > w // 2).ifthenelse(255, 64))
    if depth == 16:
        image = (rgb * 257).cast("ushort").copy(interpretation="rgb16")
    else:
        image = rgb.cast("uchar").copy(interpretation="srgb")
    path = tmp_path / "in.png"
    image.pngsave(str(path))
    return path


def run(tmp_path: Path, src: Path, backend: Nearest, **kwargs):  # type: ignore[no-untyped-def]
    return run_model_on_file(
        src,
        tmp_path / "out.png",
        tmp_path / "canvas.raw",
        backend=backend,
        scale=backend.scale,
        settings=kwargs.pop("settings", TileSettings(tile=16, batch=2, context=4)),
        channels=kwargs.pop("channels", "rgb"),
        **kwargs,
    )


def test_upscales_to_png_and_cleans_up(tmp_path: Path) -> None:
    result = run(tmp_path, photo(tmp_path), Nearest(2))
    out = pyvips.Image.new_from_file(str(result.path))
    assert (out.width, out.height, out.bands, out.format) == (74, 58, 3, "uchar")
    assert not (tmp_path / "canvas.raw").exists()
    src = pyvips.Image.new_from_file(str(tmp_path / "in.png"))
    assert out.getpoint(20, 10) == src.getpoint(10, 5)


def test_alpha_is_reattached_and_sixteen_bit_kept(tmp_path: Path) -> None:
    result = run(tmp_path, photo(tmp_path, alpha=True, depth=16), Nearest(2))
    out = pyvips.Image.new_from_file(str(result.path))
    assert (out.bands, out.format) == (4, "ushort")
    assert out.getpoint(2, 30)[3] == pytest.approx(64 * 257, abs=600)
    assert out.getpoint(70, 30)[3] == pytest.approx(65535, abs=600)


def test_ycbcr_round_trip_is_lossless_enough() -> None:
    rgb = pyvips.Image.xyz(16, 16).cast("float") / 16
    rgb = rgb.bandjoin(rgb[0] * 0.5)
    back = ycbcr_to_rgb(*rgb_to_ycbcr(rgb))
    assert (back - rgb).abs().max() < 1e-5


def test_luminance_models_keep_colour(tmp_path: Path) -> None:
    src = photo(tmp_path)
    result = run(tmp_path, src, Nearest(1), channels="y")
    out = pyvips.Image.new_from_file(str(result.path))
    original = pyvips.Image.new_from_file(str(src))
    assert (out - original).abs().max() <= 2


def test_interrupted_run_resumes_from_the_canvas(tmp_path: Path) -> None:
    src = photo(tmp_path, size=(64, 48))
    whole = pyvips.Image.new_from_file(str(run(tmp_path, src, Nearest(2, gain=0.8)).path)).numpy()
    first = Nearest(2, gain=0.8)
    details: list[dict] = []
    with pytest.raises(Cancelled):
        run(
            tmp_path,
            src,
            first,
            settings=TileSettings(tile=16, batch=1, context=4),
            on_progress=lambda f, m, d: details.append(d) if d else None,
            should_stop=lambda: first.calls >= 3,
        )
    assert (tmp_path / "canvas.raw").exists()
    done = {Rect.from_list(r) for r in details[-1]["done"]}
    second = Nearest(2, gain=0.8)
    result = run(tmp_path, src, second, settings=TileSettings(tile=16, batch=1, context=4), done=done)
    assert second.calls == 12 - 3
    np.testing.assert_array_equal(pyvips.Image.new_from_file(str(result.path)).numpy(), whole)
