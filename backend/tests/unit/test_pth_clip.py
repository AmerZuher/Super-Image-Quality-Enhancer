"""Reading PyTorch checkpoints without torch, and the numpy CLIP encoders."""

import importlib.util
import os
import pickle
import zipfile
from pathlib import Path

import numpy as np
import pytest

from siqe.ai import clip, pth
from siqe.ai.convert import ConversionError, clip_from_pth
from tests.unit.library_helpers import tiny_clip, write_checkpoint

HAS_TORCH = importlib.util.find_spec("torch") is not None
needs_fake_torch = pytest.mark.skipif(HAS_TORCH, reason="the stand-in writer replaces the torch module")


@needs_fake_torch
@pytest.mark.parametrize("legacy", [False, True])
def test_reads_both_checkpoint_formats(tmp_path: Path, legacy: bool) -> None:
    rng = np.random.default_rng(0)
    tensors = {
        "module.a.weight": rng.standard_normal((3, 4)).astype(np.float32),
        "module.b": rng.standard_normal(5).astype(np.float16),
        "steps": np.arange(6, dtype=np.int64).reshape(2, 3),
    }
    path = tmp_path / "ckpt.pt"
    write_checkpoint(path, tensors, legacy=legacy)
    assert zipfile.is_zipfile(path) is not legacy
    state = pth.state_dict(path)
    assert set(state) == {"a.weight", "b", "steps"}  # unwrapped and "module." stripped
    for key, value in tensors.items():
        np.testing.assert_array_equal(state[key.removeprefix("module.")], value)
        assert state[key.removeprefix("module.")].dtype == value.dtype


def test_refuses_code_in_a_checkpoint(tmp_path: Path) -> None:
    class Evil:
        def __reduce__(self) -> tuple[object, tuple[str]]:
            import os

            return (os.system, ("echo pwned",))

    path = tmp_path / "evil.pt"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("archive/data.pkl", pickle.dumps({"state_dict": Evil()}, protocol=2))
    with pytest.raises(pth.CheckpointError, match="refusing"):
        pth.load(path)


def test_rejects_files_that_are_not_checkpoints(tmp_path: Path) -> None:
    path = tmp_path / "x.pt"
    path.write_bytes(pickle.dumps(12345, protocol=2) + b"rest")
    with pytest.raises(pth.CheckpointError):
        pth.load(path)


@needs_fake_torch
def test_clip_conversion_stores_half_precision(tmp_path: Path) -> None:
    weights = tiny_clip(layers=1)
    write_checkpoint(tmp_path / "clip.pt", weights)
    clip_from_pth(tmp_path / "clip.pt", tmp_path / "clip.safetensors")
    from safetensors.numpy import load_file

    out = load_file(str(tmp_path / "clip.safetensors"))
    assert out["visual.proj"].dtype == np.float16
    np.testing.assert_allclose(out["visual.proj"].astype(np.float32), weights["visual.proj"], atol=1e-3)
    write_checkpoint(tmp_path / "other.pt", {"x": np.zeros(3, np.float32)})
    with pytest.raises(ConversionError):
        clip_from_pth(tmp_path / "other.pt", tmp_path / "other.safetensors")


def test_image_and_text_encoders_return_unit_vectors() -> None:
    w = tiny_clip()
    rng = np.random.default_rng(1)
    images = clip.encode_images(w, rng.random((3, 224, 224, 3), dtype=np.float32))
    assert images.shape == (3, 512)
    np.testing.assert_allclose(np.linalg.norm(images, axis=1), 1, rtol=1e-5)
    tokens = np.zeros((2, clip.CONTEXT), np.int64)
    tokens[0, :4] = [49406, 320, 1125, 49407]
    tokens[1, :3] = [49406, 1615, 49407]
    texts = clip.encode_texts(w, tokens)
    assert texts.shape == (2, 512)
    np.testing.assert_allclose(np.linalg.norm(texts, axis=1), 1, rtol=1e-5)


def test_text_encoder_is_causal() -> None:
    """Tokens after the end-of-text token must not change the result."""
    w = tiny_clip()
    a = np.zeros((1, clip.CONTEXT), np.int64)
    a[0, :3] = [49406, 1615, 49407]
    b = a.copy()
    b[0, 3:6] = [500, 600, 700]
    np.testing.assert_allclose(clip.encode_texts(w, a), clip.encode_texts(w, b), atol=1e-6)


def test_text_weights_drop_the_image_tower() -> None:
    w = clip.text_weights(tiny_clip(layers=1))
    assert not any(k.startswith("visual.") for k in w)
    assert "token_embedding.weight" in w


# Downloaded files (as in CI's backend-ai job): SIQE_TEST_MODELS=/path/to/models
VOCAB = Path(os.environ.get("SIQE_TEST_MODELS", "/nonexistent")) / "bpe_simple_vocab_16e6.txt.gz"


@pytest.mark.skipif(not VOCAB.exists(), reason="set SIQE_TEST_MODELS to a folder with the CLIP vocabulary")
def test_tokenizer_matches_openai_ids() -> None:
    tok = clip.Tokenizer(VOCAB)
    assert tok.encode("a photo of a car!") == [320, 1125, 539, 320, 1615, 256]
    ids = tok(["Hello   World"])
    assert ids[0, :4].tolist() == [49406, 3306, 1002, 49407]
    long = tok(["word " * 200])
    assert long.shape == (1, 77) and long[0, -1] == 49407
