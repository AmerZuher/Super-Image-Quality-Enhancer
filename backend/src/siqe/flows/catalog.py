"""The building blocks of a flow: every node type, its parameters and where it runs.

A flow moves one image at a time from its **Images** node along the edges. Conditions send
the image down one of their ports; edits and AI nodes produce a new working image; outputs
export it, save it to the Library, or change the Library (tags, albums, quarantine). The UI
reads this catalog to draw the palette and the parameter forms, and the API validates every
flow against it.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from siqe.imaging.edits import EditDocument
from siqe.imaging.formats import OUTPUT_FORMATS
from siqe.library.rules import RuleSet

Category = Literal["input", "condition", "edit", "ai", "output"]
Queue = Literal["none", "cpu", "gpu"]
ParamKind = Literal[
    "number",
    "integer",
    "choice",
    "text",
    "boolean",
    "model",
    "album",
    "rules",
    "adjustments",
    "color",
    "tags",
]


@dataclass(frozen=True)
class ParamSpec:
    name: str
    label: str
    kind: ParamKind
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    choices: tuple[tuple[str, str], ...] = ()  # (value, label)
    help: str = ""
    optional: bool = False
    # For "model": the model task to choose from.
    task: str | None = None


@dataclass(frozen=True)
class NodeSpec:
    type: str
    label: str
    category: Category
    summary: str
    params: tuple[ParamSpec, ...] = ()
    inputs: int = 1
    outputs: tuple[str, ...] = ("out",)
    queue: Queue = "cpu"
    # Changes the image (later nodes see the new pixels).
    transforms: bool = False
    # Changes the Library; simulated in a dry run.
    writes_library: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ai(self) -> bool:
        return self.category == "ai"


ASPECTS: tuple[tuple[str, str], ...] = (
    ("1:1", "1:1 square"),
    ("4:5", "4:5 portrait"),
    ("3:2", "3:2"),
    ("2:3", "2:3"),
    ("4:3", "4:3"),
    ("3:4", "3:4"),
    ("16:9", "16:9 desktop"),
    ("9:16", "9:16 story"),
    ("9:19.5", "9:19.5 phone"),
    ("21:9", "21:9 ultrawide"),
)
POSITIONS: tuple[tuple[str, str], ...] = tuple(
    (f"{v}-{h}", f"{v.capitalize()} {h}".replace("Middle centre", "Centre"))
    for v in ("top", "middle", "bottom")
    for h in ("left", "centre", "right")
)
FORMATS: tuple[tuple[str, str], ...] = tuple((f.name, f.label) for f in OUTPUT_FORMATS.values())

NODES: tuple[NodeSpec, ...] = (
    NodeSpec(
        "input",
        "Images",
        "input",
        "Where the flow starts: the images you run it on, or that arrive in its watched folder.",
        inputs=0,
        queue="none",
    ),
    # ------------------------------------------------------------------ conditions
    NodeSpec(
        "condition",
        "If",
        "condition",
        "Sends each image one way or the other, using the same rules as smart albums.",
        (
            ParamSpec(
                "rules",
                "Rules",
                "rules",
                {"match": "all", "rules": [{"field": "orientation", "op": "is", "value": "landscape"}]},
            ),
        ),
        outputs=("yes", "no"),
    ),
    NodeSpec(
        "skip_duplicates",
        "Skip duplicates",
        "condition",
        "Lets through only the best copy of each duplicate group; the other copies stop here.",
    ),
    # ------------------------------------------------------------------------ edits
    NodeSpec(
        "adjust",
        "Adjust",
        "edit",
        "Light and colour adjustments, the same as in Studio.",
        (ParamSpec("ops", "Adjustments", "adjustments", [{"id": "contrast", "params": {"amount": 15}}]),),
        transforms=True,
    ),
    NodeSpec(
        "studio_edits",
        "Apply Studio edits",
        "edit",
        "Applies the edits saved on each image in Studio (crop, rotation and adjustments).",
        transforms=True,
    ),
    NodeSpec(
        "resize",
        "Resize",
        "edit",
        "Scales the image down (or up) to a size.",
        (
            ParamSpec(
                "mode",
                "Fit",
                "choice",
                "longest",
                choices=(("longest", "Longest side"), ("width", "Width"), ("height", "Height")),
            ),
            ParamSpec("size", "Size", "integer", 2048, 16, 65_535, 1, "px"),
            ParamSpec("upscale", "Allow enlarging", "boolean", False, help="Classic resampling, not AI."),
        ),
        transforms=True,
    ),
    NodeSpec(
        "crop",
        "Crop to shape",
        "edit",
        "Crops to an aspect ratio, keeping the most interesting part in frame.",
        (
            ParamSpec("aspect", "Shape", "choice", "1:1", choices=ASPECTS),
            ParamSpec(
                "focus",
                "Keep in frame",
                "choice",
                "attention",
                choices=(
                    ("attention", "The subject"),
                    ("centre", "The centre"),
                    ("entropy", "The busiest part"),
                ),
            ),
        ),
        transforms=True,
    ),
    NodeSpec(
        "rotate",
        "Rotate or flip",
        "edit",
        "Turns the image in 90° steps or mirrors it.",
        (
            ParamSpec(
                "angle",
                "Rotate",
                "choice",
                "0",
                choices=(
                    ("0", "None"),
                    ("90", "90° clockwise"),
                    ("180", "180°"),
                    ("270", "90° anticlockwise"),
                ),
            ),
            ParamSpec(
                "flip",
                "Mirror",
                "choice",
                "none",
                choices=(("none", "None"), ("horizontal", "Left to right"), ("vertical", "Top to bottom")),
            ),
        ),
        transforms=True,
    ),
    NodeSpec(
        "trim",
        "Trim edges",
        "edit",
        "Removes plain or transparent borders, for example after removing the background.",
        (ParamSpec("margin", "Keep a margin of", "integer", 0, 0, 2000, 1, "px"),),
        transforms=True,
    ),
    NodeSpec(
        "canvas",
        "Place on canvas",
        "edit",
        "Centres the image on a canvas of a given shape and colour, for product shots and wallpapers.",
        (
            ParamSpec("aspect", "Shape", "choice", "1:1", choices=ASPECTS),
            ParamSpec(
                "color", "Background", "color", "#ffffff", help="A colour like #ffffff, or transparent."
            ),
            ParamSpec("padding", "Padding", "integer", 5, 0, 45, 1, "%"),
        ),
        transforms=True,
    ),
    NodeSpec(
        "watermark",
        "Watermark",
        "edit",
        "Adds a line of text in a corner.",
        (
            ParamSpec("text", "Text", "text", "© Your name"),
            ParamSpec("position", "Position", "choice", "bottom-right", choices=POSITIONS),
            ParamSpec(
                "size", "Text height", "number", 3, 0.5, 20, 0.5, "%", help="Of the image's shorter side."
            ),
            ParamSpec("opacity", "Opacity", "integer", 70, 5, 100, 5, "%"),
            ParamSpec("color", "Colour", "color", "#ffffff"),
        ),
        transforms=True,
    ),
    # --------------------------------------------------------------------------- AI
    NodeSpec(
        "upscale",
        "Upscale",
        "ai",
        "Enlarges with an AI model (Real-ESRGAN, SwinIR or SIQE Classic).",
        (
            ParamSpec("model", "Model", "model", "realesr-general-x4v3", task="upscale"),
            ParamSpec("restore_faces", "Also restore faces", "boolean", False),
        ),
        queue="gpu",
        transforms=True,
    ),
    NodeSpec(
        "denoise",
        "Denoise",
        "ai",
        "Removes camera noise with an AI model.",
        (ParamSpec("model", "Model", "model", "scunet-real-psnr", task="denoise"),),
        queue="gpu",
        transforms=True,
    ),
    NodeSpec(
        "remove_background",
        "Remove background",
        "ai",
        "Cuts out the subject and makes the background transparent.",
        (ParamSpec("model", "Model", "model", "isnet-general", task="background"),),
        queue="cpu",
        transforms=True,
    ),
    NodeSpec(
        "restore_faces",
        "Restore faces",
        "ai",
        "Finds faces and restores blurry or damaged ones (GFPGAN).",
        (ParamSpec("model", "Model", "model", "gfpgan-v1.4", task="face"),),
        queue="gpu",
        transforms=True,
    ),
    # ----------------------------------------------------------------------- outputs
    NodeSpec(
        "export",
        "Export",
        "output",
        "Saves a file to the output folder, with the same format checks as Studio.",
        (
            ParamSpec("format", "Format", "choice", "jpeg", choices=FORMATS),
            ParamSpec("quality", "Quality", "integer", 90, 1, 100, 1),
            ParamSpec("max_side", "Longest side", "integer", None, 16, 65_535, 1, "px", optional=True),
            ParamSpec("target_kb", "Target size", "integer", None, 10, 2_000_000, 1, "KB", optional=True),
            ParamSpec("strip_metadata", "Remove camera data and location", "boolean", True),
            ParamSpec(
                "folder", "Subfolder", "text", "", optional=True, help="Inside this run's output folder."
            ),
            ParamSpec(
                "name",
                "File name",
                "text",
                "{name}",
                help="{name} is the original name; {flow}, {n} and {date} also work.",
            ),
        ),
        outputs=(),
    ),
    NodeSpec(
        "save_to_library",
        "Save to Library",
        "output",
        "Adds the result to the Library as a new image, linked to the original.",
        (ParamSpec("suffix", "Name ending", "text", " (flow)", optional=True),),
        outputs=(),
        writes_library=True,
    ),
    NodeSpec(
        "tag",
        "Tag the original",
        "output",
        "Adds tags to the original image in the Library.",
        (ParamSpec("tags", "Tags", "tags", ["processed"]),),
        writes_library=True,
    ),
    NodeSpec(
        "add_to_album",
        "Add to album",
        "output",
        "Adds the original image to a hand-picked album.",
        (ParamSpec("album", "Album", "album", None),),
        writes_library=True,
    ),
    NodeSpec(
        "quarantine",
        "Move to quarantine",
        "output",
        "Moves the original to the Library's quarantine (undoable), for example blurry shots.",
        (ParamSpec("reason", "Reason", "text", "Sorted out by a flow"),),
        outputs=(),
        writes_library=True,
    ),
)

NODES_BY_TYPE = {n.type: n for n in NODES}
CATEGORY_LABELS: dict[Category, str] = {
    "input": "Start",
    "condition": "Decide",
    "edit": "Edit",
    "ai": "AI",
    "output": "Finish",
}


class ParamError(ValueError):
    pass


def _number(spec: ParamSpec, value: Any, integer: bool) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ParamError(f"{spec.label} needs a number")
    if integer and float(value) != int(value):
        raise ParamError(f"{spec.label} needs a whole number")
    if (spec.min is not None and value < spec.min) or (spec.max is not None and value > spec.max):
        raise ParamError(f"{spec.label} must be between {spec.min:g} and {spec.max:g}")
    return int(value) if integer else float(value)


def _color(spec: ParamSpec, value: Any) -> str:
    text = str(value).strip().lower()
    if text == "transparent":
        return text
    if len(text) == 7 and text.startswith("#") and all(c in "0123456789abcdef" for c in text[1:]):
        return text
    raise ParamError(f"{spec.label} must look like #ffffff, or be transparent")


def validate_param(spec: ParamSpec, value: Any) -> Any:
    if value is None:
        if spec.optional:
            return None
        if spec.kind in ("album",):
            raise ParamError(f"Choose {spec.label.lower()}")
        value = spec.default
    if spec.kind in ("number", "integer"):
        return _number(spec, value, spec.kind == "integer")
    if spec.kind == "boolean":
        if not isinstance(value, bool):
            raise ParamError(f"{spec.label} needs yes or no")
        return value
    if spec.kind == "choice":
        if str(value) not in {c for c, _ in spec.choices}:
            raise ParamError(f"{spec.label} can't be {value!r}")
        return str(value)
    if spec.kind in ("text", "model", "album"):
        if not isinstance(value, str):
            raise ParamError(f"{spec.label} needs some text")
        text = value[:300]
        if spec.kind != "text" and not text.strip():
            raise ParamError(f"Choose {spec.label.lower()}")
        return text
    if spec.kind == "color":
        return _color(spec, value)
    if spec.kind == "tags":
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            raise ParamError(f"{spec.label} needs a list of words")
        tags = [" ".join(t.strip().lower().split())[:40] for t in value]
        tags = [t for t in dict.fromkeys(tags) if t]
        if not tags:
            raise ParamError(f"Add at least one tag to {spec.label.lower()}")
        return tags[:20]
    if spec.kind == "rules":
        return RuleSet.model_validate(value).model_dump()
    if spec.kind == "adjustments":
        doc = EditDocument.model_validate({"ops": value})
        return [e.model_dump() for e in doc.ops]
    raise ParamError(f"unknown parameter kind {spec.kind}")


def validate_params(node: NodeSpec, raw: dict[str, Any]) -> dict[str, Any]:
    unknown = set(raw) - {p.name for p in node.params}
    if unknown:
        raise ParamError(f"{node.label} has no setting called {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for spec in node.params:
        try:
            out[spec.name] = validate_param(spec, raw.get(spec.name))
        except ParamError:
            raise
        except ValueError as exc:  # pydantic, from rules and adjustments
            raise ParamError(f"{spec.label}: {str(exc).splitlines()[-1].strip()}") from exc
    if node.type == "export":
        fmt = OUTPUT_FORMATS[out["format"]]
        if out.get("target_kb") and not fmt.lossy:
            raise ParamError(f"A target size needs a lossy format; {fmt.label} is lossless")
    return out


def catalog() -> list[dict[str, Any]]:
    """Node metadata for the UI."""
    return [
        {
            "type": n.type,
            "label": n.label,
            "category": n.category,
            "category_label": CATEGORY_LABELS[n.category],
            "summary": n.summary,
            "inputs": n.inputs,
            "outputs": list(n.outputs),
            "queue": n.queue,
            "ai": n.ai,
            "transforms": n.transforms,
            "writes_library": n.writes_library,
            "params": [
                {
                    "name": p.name,
                    "label": p.label,
                    "kind": p.kind,
                    "default": p.default,
                    "min": p.min,
                    "max": p.max,
                    "step": p.step,
                    "unit": p.unit,
                    "choices": [{"value": v, "label": label} for v, label in p.choices],
                    "help": p.help,
                    "optional": p.optional,
                    "task": p.task,
                }
                for p in n.params
            ],
        }
        for n in NODES
    ]
