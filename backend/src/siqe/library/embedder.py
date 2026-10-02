"""Loading the installed CLIP model once per process, and using it for images, text and tags.

The CPU worker loads the whole model to index images; the API loads only the text half to
turn a search box query into a vector. Both are cached until the files change.
"""

import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from safetensors.numpy import load_file

from siqe.ai import clip
from siqe.ai.manifest import CLIP_MODEL_ID, MODELS_BY_ID
from siqe.ai.registry import file_path, files_present
from siqe.library.vocabulary import MAX_TAGS, MIN_LIFT, MIN_SHARE, TAGS

SPEC = MODELS_BY_ID[CLIP_MODEL_ID]
BATCH = 16


@dataclass
class _Loaded:
    key: tuple[str, float]
    weights: clip.Weights
    tokenizer: clip.Tokenizer
    tag_vectors: np.ndarray | None = None


_lock = threading.Lock()
_cache: dict[bool, _Loaded] = {}


def installed() -> bool:
    return files_present(SPEC)


def _weights_file() -> Path:
    return file_path(SPEC, 0)


def model_key() -> float:
    """Changes when the installed weights change, for caches keyed on the model."""
    return _weights_file().stat().st_mtime


def _load(text_only: bool) -> _Loaded:
    path = _weights_file()
    key = (str(path), path.stat().st_mtime)
    with _lock:
        hit = _cache.get(text_only)
        if hit is not None and hit.key == key:
            return hit
        raw = load_file(str(path))
        if text_only:
            raw = clip.text_weights(raw)
        weights = {
            # The token table is only ever indexed, so it can stay half precision.
            k: v if k == "token_embedding.weight" else v.astype(np.float32)
            for k, v in raw.items()
        }
        loaded = _Loaded(key, weights, clip.Tokenizer(file_path(SPEC, 1)))
        _cache[text_only] = loaded
        return loaded


def encode_text(texts: list[str]) -> np.ndarray:
    m = _load(text_only=True)
    return clip.encode_texts(m.weights, m.tokenizer(texts))


def query_vector(text: str) -> np.ndarray:
    """A search vector for ``text``, ranked by inner product with image embeddings.

    Some images score high against any text. Subtracting the mean of the tag phrases removes
    that per-image bias (by linearity, image · (q - m) = image · q - image · m), which puts
    the image that matches best first rather than the image that matches everything.
    """
    m = _load(text_only=True)
    if m.tag_vectors is None:
        m.tag_vectors = clip.encode_texts(m.weights, m.tokenizer(list(TAGS.values())))
    phrase = text if len(text.split()) > 3 or "photo" in text.lower() else f"a photo of {text}"
    q = clip.encode_texts(m.weights, m.tokenizer([phrase]))[0]
    return np.asarray(q - m.tag_vectors.mean(0), dtype=np.float32)


def encode_images(pixels: np.ndarray) -> np.ndarray:
    m = _load(text_only=False)
    out = [clip.encode_images(m.weights, pixels[i : i + BATCH]) for i in range(0, len(pixels), BATCH)]
    return np.concatenate(out) if out else np.zeros((0, clip.DIM), np.float32)


def _tag_vectors() -> np.ndarray:
    m = _load(text_only=False)
    if m.tag_vectors is None:
        m.tag_vectors = clip.encode_texts(m.weights, m.tokenizer(list(TAGS.values())))
    return m.tag_vectors


def choose_tags(vectors: np.ndarray, tag_vectors: np.ndarray, names: list[str]) -> list[list[str]]:
    """Zero-shot tags per image: softmax at CLIP's temperature, best first."""
    sims = vectors @ tag_vectors.T
    lift = sims - sims.mean(1, keepdims=True)
    logits = 100.0 * sims
    p = np.exp(logits - logits.max(1, keepdims=True))
    p /= p.sum(1, keepdims=True)
    out: list[list[str]] = []
    for row, gain in zip(p, lift, strict=True):
        order = row.argsort()[::-1][:MAX_TAGS]
        out.append([names[i] for i in order if row[i] >= MIN_SHARE and gain[i] >= MIN_LIFT])
    return out


def tags_for(vectors: np.ndarray) -> list[list[str]]:
    return choose_tags(vectors, _tag_vectors(), list(TAGS))
