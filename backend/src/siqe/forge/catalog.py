"""The blocks a Forge model is drawn with.

Every block maps to one module in ``siqe.ai.archs.forge_blocks`` (or to a tensor operation for
Add and Concat), so the graph, the generated PyTorch code and the trainer all describe the same
network. The UI draws its palette and settings forms from this catalog; the parameter types are
the ones Flows uses.
"""

from dataclasses import dataclass
from typing import Any, Literal

from siqe.flows.catalog import ParamError, ParamSpec, validate_param

Category = Literal["io", "layers", "blocks", "merge", "resize"]

CATEGORY_LABELS: dict[str, str] = {
    "io": "Input and output",
    "layers": "Layers",
    "blocks": "Blocks",
    "merge": "Merge",
    "resize": "Change size",
}

ACTIVATIONS: tuple[tuple[str, str], ...] = (
    ("none", "None"),
    ("relu", "ReLU"),
    ("leaky_relu", "Leaky ReLU"),
    ("prelu", "PReLU (learned)"),
    ("gelu", "GELU"),
    ("silu", "SiLU"),
    ("tanh", "Tanh"),
    ("sigmoid", "Sigmoid"),
)
FACTORS: tuple[tuple[str, str], ...] = (("2", "×2"), ("3", "×3"), ("4", "×4"))


@dataclass(frozen=True)
class BlockSpec:
    type: str
    label: str
    category: Category
    summary: str
    params: tuple[ParamSpec, ...] = ()
    # 0 for the input, 1 for most blocks, 2 for "two or more" (Add, Concat).
    inputs: int = 1
    has_output: bool = True


def _filters(default: int, label: str = "Filters") -> ParamSpec:
    return ParamSpec("filters", label, "integer", default, 1, 1024, 1, help="Output channels.")


def _act(default: str = "relu") -> ParamSpec:
    return ParamSpec("act", "Activation", "choice", default, choices=ACTIVATIONS)


BLOCKS: tuple[BlockSpec, ...] = (
    BlockSpec(
        "input",
        "Input",
        "io",
        "The low-resolution image the model receives.",
        (
            ParamSpec(
                "color",
                "Colour",
                "choice",
                "rgb",
                choices=(("rgb", "RGB (3 channels)"), ("y", "Brightness only (Y, 1 channel)")),
                help="Brightness-only models are smaller; colour is added back from the original.",
            ),
        ),
        inputs=0,
    ),
    BlockSpec(
        "output",
        "Output",
        "io",
        "The finished image. Needs the input's channels at a whole-number scale.",
        has_output=False,
    ),
    BlockSpec(
        "conv",
        "Conv 2D",
        "layers",
        "A convolution with an optional activation.",
        (
            _filters(64),
            ParamSpec(
                "kernel",
                "Kernel",
                "choice",
                "3",
                choices=(("1", "1×1"), ("3", "3×3"), ("5", "5×5"), ("7", "7×7"), ("9", "9×9")),
            ),
            _act(),
        ),
    ),
    BlockSpec(
        "activation",
        "Activation",
        "layers",
        "An activation on its own.",
        (_act(),),
    ),
    BlockSpec(
        "norm",
        "Normalisation",
        "layers",
        "Batch or layer normalisation. Super-resolution models usually work better without it.",
        (
            ParamSpec(
                "kind", "Kind", "choice", "batch", choices=(("batch", "Batch norm"), ("layer", "Layer norm"))
            ),
        ),
    ),
    BlockSpec(
        "dropout",
        "Dropout",
        "layers",
        "Randomly drops whole channels while training.",
        (ParamSpec("p", "Probability", "number", 0.1, 0.0, 0.9, 0.05),),
    ),
    BlockSpec(
        "res",
        "Residual blocks",
        "blocks",
        "A stack of EDSR-style blocks: conv, ReLU, conv, plus the block's input.",
        (
            ParamSpec("blocks", "Blocks", "integer", 8, 1, 64, 1),
            ParamSpec(
                "res_scale",
                "Residual scale",
                "number",
                1.0,
                0.05,
                1.0,
                0.05,
                help="0.1 steadies very deep stacks.",
            ),
        ),
    ),
    BlockSpec(
        "rdb",
        "Residual dense block",
        "blocks",
        "Each layer sees every earlier layer's output; a 1×1 conv fuses them and the block's first "
        "layer is added back. SIQE Classic is built from these.",
        (
            ParamSpec("channels", "Channels", "integer", 64, 4, 512, 4),
            ParamSpec("layers", "Layers", "integer", 3, 1, 8, 1),
        ),
    ),
    BlockSpec(
        "attention",
        "Channel attention",
        "blocks",
        "Learns how much each channel matters and scales it (squeeze and excitation).",
        (
            ParamSpec(
                "reduction", "Reduction", "choice", "16", choices=(("4", "4"), ("8", "8"), ("16", "16"))
            ),
        ),
    ),
    BlockSpec(
        "add", "Add", "merge", "Adds two or more inputs of the same shape (a skip connection).", inputs=2
    ),
    BlockSpec(
        "concat",
        "Concat",
        "merge",
        "Stacks two or more inputs' channels. They must be the same size.",
        inputs=2,
    ),
    BlockSpec(
        "d2s",
        "Depth-to-space",
        "resize",
        "Pixel shuffle: turns channels into resolution. Needs factor² × the channels you want out.",
        (ParamSpec("factor", "Factor", "choice", "2", choices=FACTORS),),
    ),
    BlockSpec(
        "upsample",
        "Resize up",
        "resize",
        "Enlarges without learning anything. Bicubic makes a good skip connection.",
        (
            ParamSpec("factor", "Factor", "choice", "2", choices=FACTORS),
            ParamSpec(
                "mode",
                "Method",
                "choice",
                "bicubic",
                choices=(("nearest", "Nearest"), ("bilinear", "Bilinear"), ("bicubic", "Bicubic")),
            ),
        ),
    ),
    BlockSpec(
        "down",
        "Down (stride 2)",
        "resize",
        "A 3×3 conv with stride 2: half the size. For U-Net style models.",
        (_filters(64), _act()),
    ),
    BlockSpec(
        "up",
        "Up (transposed)",
        "resize",
        "A learned 2× enlargement (transposed conv). Pairs with Down.",
        (_filters(64), _act()),
    ),
)

BLOCKS_BY_TYPE: dict[str, BlockSpec] = {b.type: b for b in BLOCKS}


def validate_block_params(spec: BlockSpec, raw: dict[str, Any]) -> dict[str, Any]:
    unknown = set(raw) - {p.name for p in spec.params}
    if unknown:
        raise ParamError(f"{spec.label} has no setting called {', '.join(sorted(unknown))}")
    return {p.name: validate_param(p, raw.get(p.name)) for p in spec.params}


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "type": b.type,
            "label": b.label,
            "category": b.category,
            "category_label": CATEGORY_LABELS[b.category],
            "summary": b.summary,
            "inputs": b.inputs,
            "has_output": b.has_output,
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
                }
                for p in b.params
            ],
        }
        for b in BLOCKS
    ]
