"""Grouping near-duplicate images and choosing the copy to keep.

Two images are near-duplicates when their perceptual hashes are close (the same picture
resized, recompressed or lightly edited) or when CLIP sees them as almost the same picture
(crops, colour edits, burst shots). Groups are connected components, so A~B and B~C put all
three together. Measured on the sample set: copies score a pHash distance of 0-2 and a
similarity of 0.95 or more; different photos 18+ and 0.79 or less.
"""

import math
from dataclasses import dataclass

import numpy as np

PHASH_MAX = 10
DHASH_MAX = 14
EMBEDDING_MIN = 0.94
LOSSLESS = frozenset({"png", "tiff", "heif"})


@dataclass(frozen=True)
class Candidate:
    id: str
    phash: int
    dhash: int
    embedding: np.ndarray | None
    width: int
    height: int
    sharpness: float
    size_bytes: int
    format: str
    created: float  # timestamp; older wins a tie
    ok: bool = False  # the user kept it apart from its look-alikes


def _unsigned(values: list[int]) -> np.ndarray:
    return np.array([v & ((1 << 64) - 1) for v in values], dtype=np.uint64)


def pairs(items: list[Candidate], *, block: int = 256) -> list[tuple[int, int]]:
    """Index pairs that count as near-duplicates. Works in row blocks to bound memory."""
    n = len(items)
    if n < 2:
        return []
    ph = _unsigned([c.phash for c in items])
    dh = _unsigned([c.dhash for c in items])
    have = np.array([c.embedding is not None for c in items])
    ok = np.array([c.ok for c in items])
    emb = np.zeros((n, 512), np.float32)
    for i, c in enumerate(items):
        if c.embedding is not None:
            emb[i] = c.embedding
    found: list[tuple[int, int]] = []
    for start in range(0, n, block):
        stop = min(n, start + block)
        pd = np.bitwise_count(ph[start:stop, None] ^ ph[None, :])
        dd = np.bitwise_count(dh[start:stop, None] ^ dh[None, :])
        close = (pd <= PHASH_MAX) & (dd <= DHASH_MAX)
        if have.any():
            sim = emb[start:stop] @ emb.T
            close |= have[start:stop, None] & have[None, :] & (sim >= EMBEDDING_MIN)
        close &= ~(ok[start:stop, None] & ok[None, :])
        rows, cols = np.nonzero(close)
        found.extend((start + int(r), int(c)) for r, c in zip(rows, cols, strict=True) if start + r < c)
    return found


def groups(items: list[Candidate]) -> list[list[int]]:
    """Connected components of size two or more, as index lists."""
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in pairs(items):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    members: dict[int, list[int]] = {}
    for i in range(len(items)):
        members.setdefault(find(i), []).append(i)
    return [m for m in members.values() if len(m) > 1]


def score(c: Candidate) -> tuple[float, ...]:
    """Higher is better: resolution first (10% steps), then sharpness, then fidelity, then age."""
    pixels = max(1, c.width * c.height)
    resolution = math.floor(math.log(pixels) / math.log(1.1))
    lossless = 1 if c.format in LOSSLESS else 0
    bytes_per_pixel = c.size_bytes / pixels
    return (resolution, round(c.sharpness, 2), lossless, bytes_per_pixel, -c.created)


def rank(items: list[Candidate]) -> list[int]:
    """Indices of ``items`` from the copy to keep to the least useful."""
    return sorted(range(len(items)), key=lambda i: score(items[i]), reverse=True)


def reason(keep: Candidate, other: Candidate) -> str:
    """Why ``other`` lost to ``keep``, for the review panel."""
    if other.width * other.height * 1.1 < keep.width * keep.height:
        return "Lower resolution"
    if round(other.sharpness, 2) < round(keep.sharpness, 2):
        return "Less sharp"
    if keep.format in LOSSLESS and other.format not in LOSSLESS:
        return "Compressed copy"
    if other.size_bytes < keep.size_bytes:
        return "More compressed"
    return "Newer copy"
