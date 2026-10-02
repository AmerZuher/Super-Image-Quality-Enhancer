"""PyTorch tests. They run in the ai image (CI's backend-ai job) and skip elsewhere.

Real weights are used when SIQE_TEST_MODELS points at a folder of downloaded files.
"""

import os
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("spandrel")

from siqe.ai.convert import siqe_classic_from_h5  # noqa: E402
from siqe.ai.governor import cpu_settings  # noqa: E402
from siqe.ai.runtime import (  # noqa: E402
    ModelLoadError,
    TorchBackend,
    load_siqe_classic,
    load_spandrel,
)
from siqe.ai.tiling import Rect, TileSettings, run_tiled  # noqa: E402
from tests.unit.ai_helpers import keras_v10_forward, write_fake_v10  # noqa: E402

MODELS = Path(os.environ.get("SIQE_TEST_MODELS", "/nonexistent"))


def tiled(backend: TorchBackend, src: np.ndarray, scale: int, settings: TileSettings) -> np.ndarray:
    h, w, _ = src.shape
    out = np.zeros((h * scale, w * scale, backend.model.out_channels), np.float32)

    def read(r: Rect) -> np.ndarray:
        return src[r.y : r.y + r.h, r.x : r.x + r.w]

    def write(r: Rect, tile: np.ndarray) -> None:
        out[r.y * scale : (r.y + r.h) * scale, r.x * scale : (r.x + r.w) * scale] = tile

    run_tiled(width=w, height=h, scale=scale, read=read, write=write, backend=backend, settings=settings)
    return out


def test_siqe_classic_port_matches_the_keras_graph(tmp_path: Path) -> None:
    weights = write_fake_v10(tmp_path / "v10.h5", seed=4)
    siqe_classic_from_h5(tmp_path / "v10.h5", tmp_path / "v10.safetensors")
    model = load_siqe_classic(tmp_path / "v10.safetensors")
    y = np.random.default_rng(1).random((13, 17), dtype=np.float32)
    expected = keras_v10_forward(y, weights)
    with torch.inference_mode():
        got = model.module(torch.from_numpy(y)[None, None]).numpy()[0, 0]
    assert got.shape == (39, 51)
    np.testing.assert_allclose(got, expected, rtol=1e-4, atol=1e-4)


def test_siqe_classic_tiles_without_seams(tmp_path: Path) -> None:
    write_fake_v10(tmp_path / "v10.h5", seed=2)
    siqe_classic_from_h5(tmp_path / "v10.h5", tmp_path / "v10.safetensors")
    backend = TorchBackend(load_siqe_classic(tmp_path / "v10.safetensors"), "cpu")
    src = np.random.default_rng(5).random((70, 90, 1), dtype=np.float32)
    whole = tiled(backend, src, 3, TileSettings(tile=512, batch=1, context=16))
    pieces = tiled(backend, src, 3, TileSettings(tile=32, batch=3, context=16))
    np.testing.assert_allclose(pieces, whole, atol=1e-5)


def test_pickles_with_code_are_refused(tmp_path: Path) -> None:
    class Evil:
        def __reduce__(self):  # type: ignore[no-untyped-def]
            return (os.system, ("echo pwned",))

    path = tmp_path / "evil.pth"
    torch.save({"params": Evil()}, path)
    with pytest.raises(ModelLoadError, match="safely"):
        load_spandrel(path)


@pytest.mark.skipif(not (MODELS / "realesr-general-x4v3.pth").exists(), reason="needs downloaded weights")
def test_real_esrgan_loads_and_tiles_without_seams() -> None:
    model = load_spandrel(MODELS / "realesr-general-x4v3.pth")
    assert (model.scale, model.in_channels) == (4, 3)
    backend = TorchBackend(model, "cpu")
    src = np.random.default_rng(7).random((40, 52, 3), dtype=np.float32)
    whole = tiled(backend, src, 4, cpu_settings(width=52, height=40, context=32, multiple=model.multiple))
    pieces = tiled(backend, src, 4, TileSettings(tile=24, batch=2, context=32))
    np.testing.assert_allclose(pieces, whole, atol=2e-4)


@pytest.mark.skipif(not (MODELS / "v10.h5").exists(), reason="needs the original v10.h5")
def test_real_siqe_classic_upscales_by_three(tmp_path: Path) -> None:
    siqe_classic_from_h5(MODELS / "v10.h5", tmp_path / "v10.safetensors")
    model = load_siqe_classic(tmp_path / "v10.safetensors")
    y = np.full((1, 1, 20, 20), 0.5, np.float32)
    with torch.inference_mode():
        out = model.module(torch.from_numpy(y)).numpy()
    assert out.shape == (1, 1, 60, 60)
    # A flat grey input should come back roughly the same grey.
    assert abs(float(out[0, 0, 20:40, 20:40].mean()) - 0.5) < 0.1


@pytest.mark.skipif(
    not all((MODELS / f).exists() for f in ("GFPGANv1.4.pth", "detection_Resnet50_Final.pth", "faces.jpg")),
    reason="needs GFPGAN, RetinaFace and a photo with faces",
)
def test_faces_are_found_and_restored() -> None:
    import pyvips

    from siqe.ai.faces import restore_faces
    from siqe.ai.runtime import FaceRestorer

    restorer = FaceRestorer(MODELS / "GFPGANv1.4.pth", MODELS / "detection_Resnet50_Final.pth", "cpu")
    image = pyvips.Image.new_from_file(str(MODELS / "faces.jpg")).colourspace("srgb")[:3].cast("float") / 255
    faces = restorer.detect((image * 255).cast("uchar").numpy())
    assert len(faces) >= 1 and all(f.score > 0.9 for f in faces)
    out, count = restore_faces(image, restorer.detect, restorer.restore)
    assert count == len(faces)
    assert (out.width, out.height) == (image.width, image.height)
    # Something changed around the faces and nothing far from them.
    assert (out - image).abs().max() > 0.05
    assert (out - image).abs().crop(0, 0, 40, 40).max() == 0
