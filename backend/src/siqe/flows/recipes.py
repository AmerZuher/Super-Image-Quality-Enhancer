"""Ready-made flows to start from. Each is an ordinary flow document; using one makes a copy."""

from dataclasses import dataclass
from typing import Any

from siqe.flows.document import FlowDocument, check


@dataclass(frozen=True)
class Recipe:
    id: str
    name: str
    summary: str
    ai: bool
    document: dict[str, Any]


def _doc(
    nodes: list[tuple[str, str, dict[str, Any], float, float]], edges: list[tuple[str, str, str]]
) -> dict[str, Any]:
    return {
        "version": 1,
        "nodes": [{"id": i, "type": t, "params": p, "position": {"x": x, "y": y}} for i, t, p, x, y in nodes],
        "edges": [{"source": s, "target": t, "port": port} for s, t, port in edges],
    }


RECIPES: tuple[Recipe, ...] = (
    Recipe(
        "wallpapers",
        "Wallpaper pipeline",
        "Skips duplicates, then makes desktop wallpapers from landscape photos (upscaling small ones) "
        "and phone wallpapers from the rest.",
        True,
        _doc(
            [
                ("in", "input", {}, 0, 160),
                ("dup", "skip_duplicates", {}, 220, 160),
                (
                    "wide",
                    "condition",
                    {
                        "rules": {
                            "match": "all",
                            "rules": [{"field": "orientation", "op": "is", "value": "landscape"}],
                        }
                    },
                    440,
                    160,
                ),
                (
                    "small",
                    "condition",
                    {"rules": {"match": "all", "rules": [{"field": "width", "op": "lte", "value": 1920}]}},
                    680,
                    40,
                ),
                ("up", "upscale", {"model": "realesr-general-x4v3"}, 920, 0),
                ("desk", "resize", {"mode": "longest", "size": 3840}, 1160, 60),
                (
                    "desk_out",
                    "export",
                    {"format": "webp", "quality": 86, "folder": "desktop", "name": "{name}"},
                    1400,
                    60,
                ),
                ("phone", "crop", {"aspect": "9:19.5", "focus": "attention"}, 680, 300),
                ("phone_size", "resize", {"mode": "height", "size": 2532}, 920, 300),
                (
                    "phone_out",
                    "export",
                    {"format": "webp", "quality": 86, "folder": "phone", "name": "{name}"},
                    1160,
                    300,
                ),
            ],
            [
                ("in", "dup", "out"),
                ("dup", "wide", "out"),
                ("wide", "small", "yes"),
                ("small", "up", "yes"),
                ("up", "desk", "out"),
                ("small", "desk", "no"),
                ("desk", "desk_out", "out"),
                ("wide", "phone", "no"),
                ("phone", "phone_size", "out"),
                ("phone_size", "phone_out", "out"),
            ],
        ),
    ),
    Recipe(
        "product-shots",
        "Product shots",
        "Cuts out the product, trims the edges and centres it on a white square.",
        True,
        _doc(
            [
                ("in", "input", {}, 0, 80),
                ("cut", "remove_background", {"model": "isnet-general"}, 220, 80),
                ("trim", "trim", {"margin": 0}, 440, 80),
                ("square", "canvas", {"aspect": "1:1", "color": "#ffffff", "padding": 8}, 660, 80),
                (
                    "out",
                    "export",
                    {
                        "format": "jpeg",
                        "quality": 92,
                        "max_side": 2000,
                        "folder": "products",
                        "name": "{name}",
                    },
                    880,
                    80,
                ),
            ],
            [
                ("in", "cut", "out"),
                ("cut", "trim", "out"),
                ("trim", "square", "out"),
                ("square", "out", "out"),
            ],
        ),
    ),
    Recipe(
        "web-gallery",
        "Web gallery",
        "Applies your Studio edits, resizes to 2,048 px, adds a watermark and exports small WebP files "
        "without camera data or location.",
        False,
        _doc(
            [
                ("in", "input", {}, 0, 80),
                ("edits", "studio_edits", {}, 220, 80),
                ("size", "resize", {"mode": "longest", "size": 2048}, 440, 80),
                ("mark", "watermark", {"text": "© Your name", "position": "bottom-right"}, 660, 80),
                (
                    "out",
                    "export",
                    {"format": "webp", "quality": 85, "target_kb": 500, "name": "{name}"},
                    880,
                    80,
                ),
            ],
            [
                ("in", "edits", "out"),
                ("edits", "size", "out"),
                ("size", "mark", "out"),
                ("mark", "out", "out"),
            ],
        ),
    ),
    Recipe(
        "restore-old-photos",
        "Restore old photos",
        "Removes noise, restores faces and upscales ×4, then saves the result to the Library.",
        True,
        _doc(
            [
                ("in", "input", {}, 0, 80),
                ("clean", "denoise", {"model": "scunet-real-psnr"}, 220, 80),
                ("faces", "restore_faces", {"model": "gfpgan-v1.4"}, 440, 80),
                ("up", "upscale", {"model": "realesrgan-x4plus"}, 660, 80),
                ("save", "save_to_library", {"suffix": " (restored)"}, 900, 20),
                ("out", "export", {"format": "png", "folder": "restored", "name": "{name}"}, 900, 160),
            ],
            [
                ("in", "clean", "out"),
                ("clean", "faces", "out"),
                ("faces", "up", "out"),
                ("up", "save", "out"),
                ("up", "out", "out"),
            ],
        ),
    ),
    Recipe(
        "sort-blurry",
        "Sort out blurry shots",
        "Moves blurry photos to quarantine (you can restore them) and tags the sharp ones.",
        False,
        _doc(
            [
                ("in", "input", {}, 0, 80),
                (
                    "blurry",
                    "condition",
                    {
                        "rules": {
                            "match": "all",
                            "rules": [{"field": "sharpness", "op": "lte", "value": 0.25}],
                        }
                    },
                    220,
                    80,
                ),
                ("away", "quarantine", {"reason": "Blurry"}, 460, 0),
                ("keep", "tag", {"tags": ["sharp"]}, 460, 160),
            ],
            [("in", "blurry", "out"), ("blurry", "away", "yes"), ("blurry", "keep", "no")],
        ),
    ),
)

RECIPES_BY_ID = {r.id: r for r in RECIPES}


def validated(recipe: Recipe) -> dict[str, Any]:
    doc, problems = check(FlowDocument.model_validate(recipe.document))
    if problems:
        raise ValueError(f"recipe {recipe.id}: {problems[0].message}")
    return doc.model_dump()
