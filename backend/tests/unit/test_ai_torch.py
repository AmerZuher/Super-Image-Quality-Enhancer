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


# ------------------------------------------------------------------------------ CLIP


def _torch_clip_block(
    x: "torch.Tensor", w: dict[str, np.ndarray], p: str, mask: "torch.Tensor | None"
) -> "torch.Tensor":
    """OpenAI CLIP's ResidualAttentionBlock, built from torch's own attention."""
    d = x.shape[-1]
    attn = torch.nn.MultiheadAttention(d, d // 64, batch_first=True)
    attn.in_proj_weight.data = torch.from_numpy(w[p + "attn.in_proj_weight"])
    attn.in_proj_bias.data = torch.from_numpy(w[p + "attn.in_proj_bias"])
    attn.out_proj.weight.data = torch.from_numpy(w[p + "attn.out_proj.weight"])
    attn.out_proj.bias.data = torch.from_numpy(w[p + "attn.out_proj.bias"])

    def ln(t: "torch.Tensor", name: str) -> "torch.Tensor":
        return torch.nn.functional.layer_norm(
            t, (d,), torch.from_numpy(w[p + name + ".weight"]), torch.from_numpy(w[p + name + ".bias"])
        )

    h = ln(x, "ln_1")
    x = x + attn(h, h, h, attn_mask=mask, need_weights=False)[0]
    h = ln(x, "ln_2") @ torch.from_numpy(w[p + "mlp.c_fc.weight"]).T + torch.from_numpy(
        w[p + "mlp.c_fc.bias"]
    )
    h = h * torch.sigmoid(1.702 * h)
    return x + h @ torch.from_numpy(w[p + "mlp.c_proj.weight"]).T + torch.from_numpy(w[p + "mlp.c_proj.bias"])


@torch.inference_mode()
def test_numpy_clip_matches_torch_attention() -> None:
    from siqe.ai import clip
    from tests.unit.library_helpers import tiny_clip

    w = tiny_clip(layers=2)
    t = {k: torch.from_numpy(v) for k, v in w.items()}
    rng = np.random.default_rng(3)
    pixels = rng.random((2, 224, 224, 3), dtype=np.float32)

    x = (torch.from_numpy(pixels) - torch.from_numpy(clip.MEAN)) / torch.from_numpy(clip.STD)
    x = torch.nn.functional.conv2d(x.permute(0, 3, 1, 2), t["visual.conv1.weight"], stride=32)
    x = x.flatten(2).transpose(1, 2)
    x = torch.cat([t["visual.class_embedding"].expand(2, 1, -1), x], 1) + t["visual.positional_embedding"]
    x = torch.nn.functional.layer_norm(x, (x.shape[-1],), t["visual.ln_pre.weight"], t["visual.ln_pre.bias"])
    for i in range(2):
        x = _torch_clip_block(x, w, f"visual.transformer.resblocks.{i}.", None)
    x = torch.nn.functional.layer_norm(
        x[:, 0], (x.shape[-1],), t["visual.ln_post.weight"], t["visual.ln_post.bias"]
    )
    expected = torch.nn.functional.normalize(x @ t["visual.proj"], dim=-1).numpy()
    np.testing.assert_allclose(clip.encode_images(w, pixels), expected, atol=2e-5)

    tokens = np.zeros((2, clip.CONTEXT), np.int64)
    tokens[0, :4] = [49406, 320, 1125, 49407]
    tokens[1, :3] = [49406, 1615, 49407]
    y = t["token_embedding.weight"][torch.from_numpy(tokens)] + t["positional_embedding"]
    mask = torch.full((clip.CONTEXT, clip.CONTEXT), float("-inf")).triu(1)
    for i in range(2):
        y = _torch_clip_block(y, w, f"transformer.resblocks.{i}.", mask)
    y = torch.nn.functional.layer_norm(y, (y.shape[-1],), t["ln_final.weight"], t["ln_final.bias"])
    y = y[torch.arange(2), torch.from_numpy(tokens).argmax(-1)] @ t["text_projection"]
    np.testing.assert_allclose(
        clip.encode_texts(w, tokens), torch.nn.functional.normalize(y, dim=-1).numpy(), atol=2e-5
    )


def test_pth_reader_matches_torch_load(tmp_path: Path) -> None:
    from siqe.ai import pth

    state = {
        "a.weight": torch.randn(4, 3),
        "b": torch.randn(5).half(),
        "c": torch.arange(6).reshape(2, 3)[:, 1:],
    }
    torch.save({"state_dict": state}, tmp_path / "zip.pt")
    torch.save({"state_dict": state}, tmp_path / "legacy.pt", _use_new_zipfile_serialization=False)
    for name in ("zip.pt", "legacy.pt"):
        loaded = pth.state_dict(tmp_path / name)
        for key, value in state.items():
            np.testing.assert_array_equal(loaded[key], value.numpy())
