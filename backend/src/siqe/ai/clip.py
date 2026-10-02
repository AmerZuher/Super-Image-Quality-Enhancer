"""CLIP ViT-B/32 image and text encoders in numpy, for Library search.

The weights are OpenCLIP's LAION-400M ViT-B/32 (QuickGELU, MIT), which has OpenAI CLIP's
layout. Running in numpy keeps search on the CPU worker and the API, which have no torch:
a batch of 32 images takes a few seconds on four cores, a text query a few milliseconds.
"""

import gzip
import html
import re
from collections.abc import Sequence
from functools import cache
from pathlib import Path

import numpy as np

SIZE = 224
CONTEXT = 77
DIM = 512
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)

Weights = dict[str, np.ndarray]


def _layer_norm(x: np.ndarray, w: np.ndarray, b: np.ndarray, eps: float = 1e-5) -> np.ndarray:
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + eps) * w + b


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(-1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(-1, keepdims=True)


def _block(x: np.ndarray, w: Weights, p: str, heads: int, mask: np.ndarray | None) -> np.ndarray:
    n, t, d = x.shape
    h = _layer_norm(x, w[f"{p}ln_1.weight"], w[f"{p}ln_1.bias"])
    qkv = h @ w[f"{p}attn.in_proj_weight"].T + w[f"{p}attn.in_proj_bias"]
    qkv = qkv.reshape(n, t, 3, heads, d // heads).transpose(2, 0, 3, 1, 4)  # 3, n, heads, t, hd
    q, k, v = qkv[0], qkv[1], qkv[2]
    att = (q @ k.transpose(0, 1, 3, 2)) * np.float32((d // heads) ** -0.5)
    if mask is not None:
        att = att + mask
    o = (_softmax(att) @ v).transpose(0, 2, 1, 3).reshape(n, t, d)
    x = x + o @ w[f"{p}attn.out_proj.weight"].T + w[f"{p}attn.out_proj.bias"]
    h = _layer_norm(x, w[f"{p}ln_2.weight"], w[f"{p}ln_2.bias"])
    h = h @ w[f"{p}mlp.c_fc.weight"].T + w[f"{p}mlp.c_fc.bias"]
    h = h * (0.5 + 0.5 * np.tanh(0.851 * h))  # QuickGELU: x·sigmoid(1.702x), without overflow
    return x + h @ w[f"{p}mlp.c_proj.weight"].T + w[f"{p}mlp.c_proj.bias"]


def _layers(w: Weights, prefix: str) -> int:
    return len({k.split(".")[len(prefix.split(".")) - 1] for k in w if k.startswith(prefix)})


def encode_images(w: Weights, pixels: np.ndarray) -> np.ndarray:
    """N×224×224×3 float RGB in 0..1 → N×512 unit vectors."""
    x = ((pixels.astype(np.float32) - MEAN) / STD).transpose(0, 3, 1, 2)  # N, 3, 224, 224
    conv = w["visual.conv1.weight"]  # width, 3, patch, patch
    width, _, patch, _ = conv.shape
    g = SIZE // patch
    n = x.shape[0]
    patches = x.reshape(n, 3, g, patch, g, patch).transpose(0, 2, 4, 1, 3, 5).reshape(n, g * g, -1)
    tokens = patches @ conv.reshape(width, -1).T
    cls = np.broadcast_to(w["visual.class_embedding"], (n, 1, width))
    t = np.concatenate([cls, tokens], 1) + w["visual.positional_embedding"]
    t = _layer_norm(t, w["visual.ln_pre.weight"], w["visual.ln_pre.bias"])
    heads = width // 64
    for i in range(_layers(w, "visual.transformer.resblocks.")):
        t = _block(t, w, f"visual.transformer.resblocks.{i}.", heads, None)
    out = _layer_norm(t[:, 0], w["visual.ln_post.weight"], w["visual.ln_post.bias"]) @ w["visual.proj"]
    return _normalise(out)


def encode_texts(w: Weights, tokens: np.ndarray) -> np.ndarray:
    """N×77 token ids → N×512 unit vectors."""
    x = w["token_embedding.weight"][tokens] + w["positional_embedding"]
    width = x.shape[-1]
    mask = np.triu(np.full((CONTEXT, CONTEXT), -np.inf, np.float32), 1)
    for i in range(_layers(w, "transformer.resblocks.")):
        x = _block(x, w, f"transformer.resblocks.{i}.", width // 64, mask)
    x = _layer_norm(x, w["ln_final.weight"], w["ln_final.bias"])
    eot = x[np.arange(len(tokens)), tokens.argmax(-1)]
    return _normalise(eot @ w["text_projection"])


def _normalise(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def text_weights(w: Weights) -> Weights:
    """Only what the text encoder needs, so the API holds a third of the model."""
    return {k: v for k, v in w.items() if not k.startswith("visual.")}


# ---- Tokenizer: byte-level BPE, a port of OpenAI CLIP's simple_tokenizer (MIT). ----

_PATTERN = re.compile(
    r"""<\|startoftext\|>|<\|endoftext\|>|'s|'t|'re|'ve|'m|'ll|'d|[^\W\d_]+|\d|(?:[^\s\w]|_)+""",
    re.IGNORECASE,
)


@cache
def _bytes_to_unicode() -> dict[int, str]:
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1))
    bs += list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, map(chr, cs), strict=True))


class Tokenizer:
    def __init__(self, vocab_path: Path) -> None:
        with gzip.open(vocab_path, "rt", encoding="utf-8") as f:
            merges_text = f.read().split("\n")
        merges = [tuple(m.split()) for m in merges_text[1 : 49152 - 256 - 2 + 1]]
        vocab = list(_bytes_to_unicode().values())
        vocab = vocab + [v + "</w>" for v in vocab] + ["".join(m) for m in merges]
        vocab += ["<|startoftext|>", "<|endoftext|>"]
        self.encoder = {v: i for i, v in enumerate(vocab)}
        self.ranks = {m: i for i, m in enumerate(merges)}
        self.byte_encoder = _bytes_to_unicode()
        self.sot = self.encoder["<|startoftext|>"]
        self.eot = self.encoder["<|endoftext|>"]
        self._cache: dict[str, str] = {}

    def _bpe(self, token: str) -> str:
        if token in self._cache:
            return self._cache[token]
        word = [*token[:-1], token[-1] + "</w>"]
        while len(word) > 1:
            pairs = {(word[i], word[i + 1]) for i in range(len(word) - 1)}
            best = min(pairs, key=lambda p: self.ranks.get(p, 1 << 30))
            if best not in self.ranks:
                break
            merged: list[str] = []
            i = 0
            while i < len(word):
                if i < len(word) - 1 and (word[i], word[i + 1]) == best:
                    merged.append(word[i] + word[i + 1])
                    i += 2
                else:
                    merged.append(word[i])
                    i += 1
            word = merged
        out = " ".join(word)
        if len(self._cache) < 50_000:
            self._cache[token] = out
        return out

    def encode(self, text: str) -> list[int]:
        text = re.sub(r"\s+", " ", html.unescape(html.unescape(text))).strip().lower()
        ids: list[int] = []
        for token in _PATTERN.findall(text):
            mapped = "".join(self.byte_encoder[b] for b in token.encode("utf-8"))
            ids.extend(self.encoder[t] for t in self._bpe(mapped).split(" "))
        return ids

    def __call__(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), CONTEXT), np.int64)
        for row, text in enumerate(texts):
            ids = [self.sot, *self.encode(text)[: CONTEXT - 2], self.eot]
            out[row, : len(ids)] = ids
        return out
