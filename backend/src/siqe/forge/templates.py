"""Ready-made Forge models to start from."""

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from siqe.forge.graph import ForgeGraph


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    summary: str
    graph: dict[str, Any]


def _graph(
    blocks: list[tuple[str, str, dict[str, Any], int, int]], links: list[tuple[str, str]]
) -> dict[str, Any]:
    return ForgeGraph.model_validate(
        {
            "blocks": [
                {"id": i, "type": t, "params": p, "position": {"x": x, "y": y}} for i, t, p, x, y in blocks
            ],
            "links": [{"source": s, "target": t} for s, t in links],
        }
    ).model_dump()


def _chain(blocks: list[tuple[str, str, dict[str, Any], int, int]]) -> dict[str, Any]:
    return _graph(blocks, [(a[0], b[0]) for a, b in pairwise(blocks)])


TEMPLATES: tuple[Template, ...] = (
    Template(
        "siqe-classic",
        "SIQE Classic",
        "Your original model: two residual dense blocks on brightness, then ×3 depth-to-space. "
        "357k parameters.",
        _chain(
            [
                ("in", "input", {"color": "y"}, 0, 120),
                ("entry", "conv", {"filters": 64, "kernel": "5", "act": "relu"}, 200, 120),
                ("block1", "rdb", {"channels": 64, "layers": 3}, 400, 120),
                ("block2", "rdb", {"channels": 32, "layers": 3}, 600, 120),
                ("tail", "conv", {"filters": 9, "kernel": "3", "act": "relu"}, 800, 120),
                ("shuffle", "d2s", {"factor": "3"}, 1000, 120),
                ("out", "output", {}, 1200, 120),
            ]
        ),
    ),
    Template(
        "espcn",
        "ESPCN",
        "The classic fast upscaler: three convolutions, then depth-to-space. Tiny and quick to train.",
        _chain(
            [
                ("in", "input", {"color": "y"}, 0, 120),
                ("c1", "conv", {"filters": 64, "kernel": "5", "act": "tanh"}, 200, 120),
                ("c2", "conv", {"filters": 32, "kernel": "3", "act": "tanh"}, 400, 120),
                ("c3", "conv", {"filters": 9, "kernel": "3", "act": "none"}, 600, 120),
                ("shuffle", "d2s", {"factor": "3"}, 800, 120),
                ("out", "output", {}, 1000, 120),
            ]
        ),
    ),
    Template(
        "edsr-lite",
        "EDSR-lite",
        "Residual blocks with a long skip, then ×2 depth-to-space, in colour. A strong baseline.",
        _graph(
            [
                ("in", "input", {"color": "rgb"}, 0, 120),
                ("head", "conv", {"filters": 64, "kernel": "3", "act": "none"}, 200, 120),
                ("body", "res", {"blocks": 8, "res_scale": 1.0}, 400, 40),
                ("body_end", "conv", {"filters": 64, "kernel": "3", "act": "none"}, 600, 40),
                ("skip", "add", {}, 800, 120),
                ("expand", "conv", {"filters": 256, "kernel": "3", "act": "none"}, 1000, 120),
                ("shuffle", "d2s", {"factor": "2"}, 1200, 120),
                ("tail", "conv", {"filters": 3, "kernel": "3", "act": "none"}, 1400, 120),
                ("out", "output", {}, 1600, 120),
            ],
            [
                ("in", "head"),
                ("head", "body"),
                ("body", "body_end"),
                ("body_end", "skip"),
                ("head", "skip"),
                ("skip", "expand"),
                ("expand", "shuffle"),
                ("shuffle", "tail"),
                ("tail", "out"),
            ],
        ),
    ),
    Template(
        "residual-x4",
        "Bicubic plus detail ×4",
        "Learns only what bicubic enlargement misses: a small network's output is added to a bicubic copy.",
        _graph(
            [
                ("in", "input", {"color": "rgb"}, 0, 160),
                ("bicubic", "upsample", {"factor": "4", "mode": "bicubic"}, 600, 300),
                ("head", "conv", {"filters": 48, "kernel": "3", "act": "prelu"}, 200, 40),
                ("body", "res", {"blocks": 4, "res_scale": 1.0}, 400, 40),
                ("attend", "attention", {"reduction": "8"}, 600, 40),
                ("expand", "conv", {"filters": 48, "kernel": "3", "act": "none"}, 800, 40),
                ("shuffle", "d2s", {"factor": "4"}, 1000, 40),
                ("sum", "add", {}, 1200, 160),
                ("out", "output", {}, 1400, 160),
            ],
            [
                ("in", "head"),
                ("head", "body"),
                ("body", "attend"),
                ("attend", "expand"),
                ("expand", "shuffle"),
                ("shuffle", "sum"),
                ("in", "bicubic"),
                ("bicubic", "sum"),
                ("sum", "out"),
            ],
        ),
    ),
    Template(
        "unet-denoise",
        "U-Net denoiser",
        "Same size in and out: goes down to see more context, comes back up, and adds the input back.",
        _graph(
            [
                ("in", "input", {"color": "rgb"}, 0, 160),
                ("enc", "conv", {"filters": 32, "kernel": "3", "act": "relu"}, 200, 160),
                ("down", "down", {"filters": 64, "act": "relu"}, 400, 40),
                ("mid", "conv", {"filters": 64, "kernel": "3", "act": "relu"}, 600, 40),
                ("up", "up", {"filters": 32, "act": "relu"}, 800, 40),
                ("join", "concat", {}, 1000, 160),
                ("dec", "conv", {"filters": 32, "kernel": "3", "act": "relu"}, 1200, 160),
                ("tail", "conv", {"filters": 3, "kernel": "3", "act": "none"}, 1400, 160),
                ("residual", "add", {}, 1600, 300),
                ("out", "output", {}, 1800, 300),
            ],
            [
                ("in", "enc"),
                ("enc", "down"),
                ("down", "mid"),
                ("mid", "up"),
                ("enc", "join"),
                ("up", "join"),
                ("join", "dec"),
                ("dec", "tail"),
                ("tail", "residual"),
                ("in", "residual"),
                ("residual", "out"),
            ],
        ),
    ),
)

TEMPLATES_BY_ID: dict[str, Template] = {t.id: t for t in TEMPLATES}

EMPTY: dict[str, Any] = _graph(
    [("in", "input", {"color": "rgb"}, 0, 120), ("out", "output", {}, 400, 120)], []
)
