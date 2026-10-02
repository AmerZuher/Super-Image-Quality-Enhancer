import os
from pathlib import Path

import numpy as np
import pytest
import pyvips

from siqe.ai import background

MODELS = Path(os.environ.get("SIQE_TEST_MODELS", "/nonexistent"))


class FakeSession:
    """Predicts 'subject' on the left half, with raw logits outside 0..1 like the real model."""

    class Input:
        name = "input_image"

    def get_inputs(self):  # type: ignore[no-untyped-def]
        return [self.Input()]

    def run(self, _outputs, feeds):  # type: ignore[no-untyped-def]
        (x,) = feeds.values()
        assert x.shape == (1, 3, 1024, 1024) and x.dtype == np.float32
        assert x.max() == pytest.approx(0.5, abs=1e-5)
        pred = np.full((1, 1, 1024, 1024), -3.0, np.float32)
        pred[..., :512] = 7.0
        return [pred]


def make_photo(tmp_path: Path, w: int = 300, h: int = 200) -> Path:
    image = (
        (pyvips.Image.xyz(w, h)[0] * (255 / w)).bandjoin([60, 120]).cast("uchar").copy(interpretation="srgb")
    )
    image.pngsave(str(tmp_path / "in.png"))
    return tmp_path / "in.png"


def test_mask_becomes_full_resolution_alpha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(background, "session", lambda path: FakeSession())
    size = background.remove_background(make_photo(tmp_path), tmp_path / "out.png", Path("isnet.onnx"))
    assert size == (300, 200)
    out = pyvips.Image.new_from_file(str(tmp_path / "out.png"))
    assert (out.width, out.height, out.bands) == (300, 200, 4)
    assert out.getpoint(20, 100)[3] == 255
    assert out.getpoint(280, 100)[3] == 0
    assert out.getpoint(20, 100)[:3] == pyvips.Image.new_from_file(str(tmp_path / "in.png")).getpoint(20, 100)


@pytest.mark.skipif(not (MODELS / "isnet-general-use.onnx").exists(), reason="needs downloaded weights")
def test_real_isnet_finds_a_subject(tmp_path: Path) -> None:
    samples = Path(__file__).resolve().parents[3] / "samples"
    src = samples / "rose-blue.jpg"
    w, h = background.remove_background(src, tmp_path / "out.png", MODELS / "isnet-general-use.onnx")
    alpha = pyvips.Image.new_from_file(str(tmp_path / "out.png"))[3]
    # Some of the image is kept and some removed.
    assert 0.05 < alpha.avg() / 255 < 0.95
    assert (w, h) == (alpha.width, alpha.height)
