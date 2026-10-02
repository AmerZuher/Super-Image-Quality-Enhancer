"""The image operations behind a flow's Edit blocks."""

from pathlib import Path

import pytest
import pyvips

from siqe.flows import ops
from siqe.imaging.working import Working, from_working


def _work(
    width: int, height: int, *, alpha: bool = False, colour: tuple[float, float, float] = (0.2, 0.4, 0.6)
) -> Working:
    rgb = (pyvips.Image.black(width, height, bands=3) + list(colour)).cast("float")
    a = (pyvips.Image.black(width, height) + 1.0).cast("float") if alpha else None
    return Working(rgb=rgb, alpha=a, depth=8)


def _framed(width: int, height: int, border: int) -> Working:
    """A dark square on a white background, ``border`` pixels in from every edge."""
    inner = pyvips.Image.black(width - 2 * border, height - 2 * border, bands=3) + 0.1
    rgb = inner.embed(border, border, width, height, extend="white").cast("float")
    # embed's "white" is 255 for uchar sources; normalise to the 0..1 working range.
    rgb = (rgb > 1.0).ifthenelse(1.0, rgb)
    return Working(rgb=rgb, alpha=None, depth=8)


def test_resize_longest_side_never_upscales_unless_asked() -> None:
    work = _work(400, 200)
    assert (
        ops.resize(work, "longest", 100, False).width,
        ops.resize(work, "longest", 100, False).height,
    ) == (100, 50)
    assert ops.resize(work, "longest", 800, False) is work
    bigger = ops.resize(work, "longest", 800, True)
    assert (bigger.width, bigger.height) == (800, 400)


def test_resize_by_width_and_height() -> None:
    work = _work(400, 200)
    assert ops.resize(work, "width", 200, False).height == 100
    assert ops.resize(work, "height", 100, False).width == 200


@pytest.mark.parametrize(("aspect", "size"), [("1:1", (300, 300)), ("16:9", (400, 225)), ("4:5", (240, 300))])
def test_crop_to_aspect(aspect: str, size: tuple[int, int]) -> None:
    work = _work(400, 300)
    for focus in ("centre", "attention", "entropy"):
        out = ops.crop(work, aspect, focus)
        assert (out.width, out.height) == size


def test_rotate_and_flip() -> None:
    work = _work(400, 200, alpha=True)
    turned = ops.rotate(work, "90", "none")
    assert (turned.width, turned.height) == (200, 400)
    assert turned.alpha is not None and turned.alpha.width == 200
    assert ops.rotate(work, "0", "none") is work
    assert ops.rotate(work, "180", "horizontal").width == 400


def test_trim_removes_plain_borders_and_keeps_a_margin() -> None:
    out = ops.trim(_framed(300, 200, 40), 0)
    assert (out.width, out.height) == (220, 120)
    padded = ops.trim(_framed(300, 200, 40), 10)
    assert (padded.width, padded.height) == (240, 140)


def test_trim_uses_transparency_when_there_is_some() -> None:
    work = _work(100, 100)
    alpha = (pyvips.Image.black(60, 50) + 1.0).embed(20, 30, 100, 100, extend="black").cast("float")
    out = ops.trim(Working(rgb=work.rgb, alpha=alpha, depth=8), 0)
    assert (out.width, out.height) == (60, 50)


def test_canvas_fits_the_image_with_padding() -> None:
    out = ops.canvas(_work(400, 200), "1:1", "#ffffff", 10)
    assert out.width == out.height
    assert out.width >= 400 / 0.8 - 1
    assert out.alpha is None
    corner = from_working(out).getpoint(0, 0)
    assert corner[:3] == [255, 255, 255]
    clear = ops.canvas(_work(400, 200), "1:1", "transparent", 0)
    assert clear.alpha is not None and clear.alpha.getpoint(0, 0) == [0.0]


def test_watermark_draws_text_even_with_markup_characters() -> None:
    work = _work(600, 300, colour=(0.0, 0.0, 0.0))
    out = ops.watermark(work, "<b> & Co", "bottom-right", 8, 100, "#ffffff")
    rendered = from_working(out)
    assert rendered.max() == 255  # white text on black
    assert rendered.crop(0, 0, 300, 150).max() == 0  # nothing in the top-left quarter
    assert ops.watermark(work, "  ", "bottom-right", 8, 100, "#ffffff") is work


def test_run_step_round_trips_through_lossless_png(tmp_path: Path) -> None:
    src = tmp_path / "in.png"
    from_working(_work(320, 240, alpha=True)).pngsave(str(src))
    out = tmp_path / "out" / "step.png"
    assert ops.run_step("crop", {"aspect": "1:1", "focus": "centre"}, src, out) == (240, 240)
    saved = pyvips.Image.new_from_file(str(out))
    assert saved.hasalpha()
    assert not list(out.parent.glob("*.partial.png"))


def test_unknown_step_is_a_typed_error() -> None:
    from siqe.core.errors import AppError

    with pytest.raises(AppError) as err:
        ops.apply("explode", {}, _work(10, 10))
    assert err.value.code == "flow.unknown_step"
