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
                ("entry", "conv", {"filters": 64, "kernel": "5", "act": "relu"}, 240, 120),
                ("block1", "rdb", {"channels": 64, "layers": 3}, 480, 120),
                ("block2", "rdb", {"channels": 32, "layers": 3}, 720, 120),
                ("tail", "conv", {"filters": 9, "kernel": "3", "act": "relu"}, 960, 120),
                ("shuffle", "d2s", {"factor": "3"}, 1200, 120),
                ("out", "output", {}, 1440, 120),
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
                ("c1", "conv", {"filters": 64, "kernel": "5", "act": "tanh"}, 240, 120),
                ("c2", "conv", {"filters": 32, "kernel": "3", "act": "tanh"}, 480, 120),
                ("c3", "conv", {"filters": 9, "kernel": "3", "act": "none"}, 720, 120),
                ("shuffle", "d2s", {"factor": "3"}, 960, 120),
                ("out", "output", {}, 1200, 120),
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
                ("head", "conv", {"filters": 64, "kernel": "3", "act": "none"}, 240, 120),
                ("body", "res", {"blocks": 8, "res_scale": 1.0}, 480, 40),
                ("body_end", "conv", {"filters": 64, "kernel": "3", "act": "none"}, 720, 40),
                ("skip", "add", {}, 960, 120),
                ("expand", "conv", {"filters": 256, "kernel": "3", "act": "none"}, 1200, 120),
                ("shuffle", "d2s", {"factor": "2"}, 1440, 120),
                ("tail", "conv", {"filters": 3, "kernel": "3", "act": "none"}, 1680, 120),
                ("out", "output", {}, 1920, 120),
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
                ("bicubic", "upsample", {"factor": "4", "mode": "bicubic"}, 720, 300),
                ("head", "conv", {"filters": 48, "kernel": "3", "act": "prelu"}, 240, 40),
                ("body", "res", {"blocks": 4, "res_scale": 1.0}, 480, 40),
                ("attend", "attention", {"reduction": "8"}, 720, 40),
                ("expand", "conv", {"filters": 48, "kernel": "3", "act": "none"}, 960, 40),
                ("shuffle", "d2s", {"factor": "4"}, 1200, 40),
                ("sum", "add", {}, 1440, 160),
                ("out", "output", {}, 1680, 160),
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
                ("enc", "conv", {"filters": 32, "kernel": "3", "act": "relu"}, 240, 160),
                ("down", "down", {"filters": 64, "act": "relu"}, 480, 40),
                ("mid", "conv", {"filters": 64, "kernel": "3", "act": "relu"}, 720, 40),
                ("up", "up", {"filters": 32, "act": "relu"}, 960, 40),
                ("join", "concat", {}, 1200, 160),
                ("dec", "conv", {"filters": 32, "kernel": "3", "act": "relu"}, 1440, 160),
                ("tail", "conv", {"filters": 3, "kernel": "3", "act": "none"}, 1680, 160),
                ("residual", "add", {}, 1920, 300),
                ("out", "output", {}, 2160, 300),
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
    [("in", "input", {"color": "rgb"}, 0, 120), ("out", "output", {}, 480, 120)], []
)
