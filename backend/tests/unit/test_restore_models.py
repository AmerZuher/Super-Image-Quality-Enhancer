"""Deblur (ONNX tiling), erase (LaMa regions and blending) and colorize (Lab recombination).

The real networks are replaced by small stand-ins: a tiny ONNX graph built here, and plain
functions for the eraser and the colorizer. The torch port of the colorizer is checked in
test_ai_torch.py.
"""

from pathlib import Path

import numpy as np
import onnx
import pytest
import pyvips
from onnx import TensorProto, helper

from siqe.ai.colorize import colorize_file
from siqe.ai.governor import TileSettings, min_input_settings
from siqe.ai.inpaint import Mask, inpaint_file, regions
from siqe.ai.manifest import COMMERCIAL_SAFE, MODELS_BY_ID
from siqe.ai.onnx_model import OnnxBackend, describe, session
from siqe.ai.pipeline import run_model_on_file
from siqe.ai.plan import DeviceInfo, plan_run
from siqe.core.errors import AppError


def _invert_model(path: Path) -> Path:
    """y = 1 - x, with dynamic height and width: enough to check tiling end to end."""
    x = helper.make_tensor_value_info("lq", TensorProto.FLOAT, ["n", 3, "h", "w"])
    y = helper.make_tensor_value_info("out", TensorProto.FLOAT, ["n", 3, "h", "w"])
    one = helper.make_tensor("one", TensorProto.FLOAT, [], [1.0])
    graph = helper.make_graph([helper.make_node("Sub", ["one", "lq"], ["out"])], "invert", [x], [y], [one])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.save(model, path)
    return path


def _photo(path: Path, width: int = 300, height: int = 200) -> Path:
    xyz = pyvips.Image.xyz(width, height)
    rgb = (xyz[0] / width * 255).bandjoin([xyz[1] / height * 255, (xyz[0] + xyz[1]) % 256])
    rgb.cast("uchar").copy(interpretation="srgb").pngsave(str(path))
    return path


def test_new_models_are_commercial_safe_and_pinned() -> None:
    for model_id in ("nafnet-deblur", "lama-erase", "siggraph17-colorize"):
        spec = MODELS_BY_ID[model_id]
        assert spec.license in COMMERCIAL_SAFE
        assert all(len(f.sha256) == 64 and f.size > 0 for f in spec.files)
        assert "/main/" not in spec.files[0].url  # pinned, never a moving branch


def test_onnx_backend_runs_through_the_tiler(tmp_path: Path) -> None:
    model = _invert_model(tmp_path / "invert.onnx")
    inputs, outputs = describe(session(model, threads=1))
    assert inputs[0].name == "lq" and outputs[0].name == "out"
    src = _photo(tmp_path / "in.png")
    settings = TileSettings(tile=64, batch=1, context=8, multiple=16)
    out = run_model_on_file(
        src,
        tmp_path / "out.png",
        tmp_path / "canvas.raw",
        backend=OnnxBackend(model, threads=1),
        scale=1,
        channels="rgb",
        settings=settings,
    )
    assert (out.width, out.height) == (300, 200)
    a = np.asarray(pyvips.Image.new_from_file(str(src)).numpy(), np.int32)
    b = np.asarray(pyvips.Image.new_from_file(str(out.path)).numpy(), np.int32)
    assert np.abs((255 - a) - b).max() <= 1  # inverted everywhere, no seams between tiles


def test_a_broken_onnx_file_is_a_typed_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.onnx"
    bad.write_bytes(b"not a model")
    with pytest.raises(AppError) as err:
        session(bad)
    assert err.value.code == "model.load_failed"


def test_minimum_input_grows_the_tile() -> None:
    small = TileSettings(tile=128, batch=1, context=32, multiple=16)
    grown = min_input_settings(small, 384)
    assert grown.tile + 2 * grown.context >= 384 and grown.tile % 16 == 0
    assert min_input_settings(small, 0) == small


def test_deblur_plans_on_the_cpu_with_its_minimum_tile() -> None:
    gpu = DeviceInfo("cuda", "RTX 3090", 20e9, True)
    plan = plan_run(
        MODELS_BY_ID["nafnet-deblur"],
        width=4000,
        height=3000,
        bit_depth=8,
        has_alpha=False,
        device=gpu,
        calibration=None,
        reserve_mb=1536,
    )
    assert plan["device"] == "cpu"
    assert plan["tile"] + 2 * 32 >= 384
    assert any("minutes" in w for w in plan["warnings"])
    for task_model in ("lama-erase", "siggraph17-colorize"):
        p = plan_run(
            MODELS_BY_ID[task_model],
            width=4000,
            height=3000,
            bit_depth=8,
            has_alpha=False,
            device=gpu,
            calibration=None,
            reserve_mb=1536,
        )
        assert p["tiles"] == 1 and (p["output_width"], p["output_height"]) == (4000, 3000)


def test_strokes_close_together_form_one_region() -> None:
    mask = Mask.model_validate(
        {
            "strokes": [
                {"points": [[0.2, 0.2], [0.25, 0.2]], "radius": 0.01},
                {"points": [[0.27, 0.21]], "radius": 0.01},
                {"points": [[0.8, 0.8]], "radius": 0.01},
            ]
        }
    )
    parts = regions(mask, 4000, 3000)
    assert sorted(len(r.strokes) for r in parts) == [1, 2]
    for r in parts:
        assert r.left >= 0 and r.left + r.side_w <= 4000 and r.top >= 0 and r.top + r.side_h <= 3000
        assert min(r.side_w, r.side_h) >= 512


def test_erase_changes_only_the_painted_area(tmp_path: Path) -> None:
    src = _photo(tmp_path / "in.png", 900, 600)
    mask = Mask.model_validate({"strokes": [{"points": [[0.5, 0.5], [0.55, 0.5]], "radius": 0.02}]})

    def fill_red(image: np.ndarray, painted: np.ndarray) -> np.ndarray:
        assert image.shape == (512, 512, 3) and painted.shape == (512, 512) and painted.any()
        out = image.copy()
        out[painted > 0.5] = (1.0, 0.0, 0.0)
        return out

    size = inpaint_file(src, tmp_path / "out.png", mask, fill_red)
    assert size == (900, 600)
    a = np.asarray(pyvips.Image.new_from_file(str(src)).numpy(), np.int32)
    b = np.asarray(pyvips.Image.new_from_file(str(tmp_path / "out.png")).numpy(), np.int32)
    changed = np.abs(a - b).max(axis=2) > 8
    ys, xs = np.nonzero(changed)
    # The stroke spans x 450..495 with an 18 px brush; nothing far from it may change.
    assert changed.any()
    assert xs.min() > 400 and xs.max() < 545 and ys.min() > 250 and ys.max() < 350
    assert b[300, 470, 0] > 200 and b[300, 470, 1] < 60  # the middle of the stroke is filled
    # The mask is grown past the brush, so the object's edge pixels are replaced too.
    assert b[300, 516, 0] > 200 and b[300, 429, 0] > 200


def test_too_many_separate_areas_are_refused() -> None:
    strokes = [{"points": [[(i % 10) / 10 + 0.05, (i // 10) / 3 + 0.1]], "radius": 0.005} for i in range(30)]
    with pytest.raises(AppError) as err:
        regions(Mask.model_validate({"strokes": strokes}), 4000, 3000)
    assert err.value.code == "erase.too_many_regions"


def test_colorize_keeps_lightness_and_alpha(tmp_path: Path) -> None:
    grey = pyvips.Image.xyz(320, 240)[0] / 320 * 255
    alpha = (pyvips.Image.xyz(320, 240)[1] > 120).ifthenelse(255, 0)
    src = tmp_path / "grey.png"
    grey.bandjoin(alpha).cast("uchar").copy(interpretation="b-w").pngsave(str(src))

    def warm(lightness: np.ndarray) -> np.ndarray:
        assert lightness.shape == (256, 256)
        return np.stack([np.full_like(lightness, 20.0), np.full_like(lightness, 40.0)])  # orange

    assert colorize_file(src, tmp_path / "out.png", warm) == (320, 240)
    out = pyvips.Image.new_from_file(str(tmp_path / "out.png"))
    assert out.bands == 4 and out[3].min() == 0 and out[3].max() == 255
    before = pyvips.Image.new_from_file(str(src))[0].colourspace("lab")[0]
    after = out[:3].colourspace("lab")[0]
    assert abs(before.avg() - after.avg()) < 1.5  # detail and brightness stay
    middle = np.asarray(out.crop(150, 10, 20, 20).numpy(), np.int32)
    assert (middle[..., 0] - middle[..., 2]).mean() > 30  # and colour is added (warm: red over blue)
