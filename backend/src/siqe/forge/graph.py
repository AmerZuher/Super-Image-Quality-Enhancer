"""A Forge model as a graph, and everything we can tell about it without PyTorch.

``analyze`` walks the graph in order and works out, for every block, how many channels it
produces and at what scale of the input (1/2 after a Down, 3 after a ×3 Depth-to-space). From
that it reports problems (most with a one-click fix), counts parameters and compute, estimates
training memory, and produces the **plan**: the ordered list of layers that both the generated
code (``siqe.forge.codegen``) and the trainer (``siqe.ai.archs.forge``) build the network from.
"""

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel, Field

from siqe.flows.catalog import ParamError
from siqe.forge.catalog import BLOCKS_BY_TYPE, validate_block_params

MAX_BLOCKS = 80
SCALES = (1, 2, 3, 4, 8)
# For the training-memory estimate shown while designing.
ESTIMATE_BATCH = 16
ESTIMATE_PATCH = 64


class ForgePosition(BaseModel):
    x: float = 0
    y: float = 0


class ForgeBlock(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    position: ForgePosition = Field(default_factory=ForgePosition)
    label: str | None = Field(default=None, max_length=80)


class ForgeLink(BaseModel):
    source: str
    target: str


class ForgeGraph(BaseModel):
    version: Literal[1] = 1
    blocks: list[ForgeBlock] = Field(default_factory=list, max_length=MAX_BLOCKS)
    links: list[ForgeLink] = Field(default_factory=list, max_length=MAX_BLOCKS * 4)


class ForgeFix(BaseModel):
    label: str
    block: str
    params: dict[str, Any]


class ForgeProblem(BaseModel):
    block: str | None = None
    message: str
    fix: ForgeFix | None = None


class ForgeShape(BaseModel):
    channels: int
    scale: str = Field(description="Size relative to the input, e.g. '1', '1/2' or '3'.")


class ForgeStats(BaseModel):
    params: int
    macs_per_pixel: int = Field(description="Multiply-adds per input pixel.")
    gmacs_per_megapixel: float
    scale: int | None = Field(description="Output size ÷ input size; null until the graph is valid.")
    color: Literal["rgb", "y"]
    layers: int
    train_memory_mb: int = Field(
        description=f"Estimated GPU memory to train at batch {ESTIMATE_BATCH}, patch {ESTIMATE_PATCH}."
    )
    patch_multiple: int = Field(description="Training patches must be a multiple of this (from Down blocks).")
    context: int = Field(description="Input pixels each output pixel sees on each side (for tiling).")


class ForgeAnalysis(BaseModel):
    graph: ForgeGraph
    shapes: dict[str, ForgeShape]
    problems: list[ForgeProblem]
    stats: ForgeStats
    plan: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class _Out:
    channels: int
    scale: Fraction


@dataclass
class _Cost:
    params: int = 0
    macs: Fraction = field(default_factory=lambda: Fraction(0))  # per input pixel
    activations: Fraction = field(default_factory=lambda: Fraction(0))  # floats per input pixel
    # Receptive radius in input pixels (an upper bound).
    reach: Fraction = field(default_factory=lambda: Fraction(0))


def attr_name(block_id: str) -> str:
    """The module attribute (and state_dict prefix) for a block."""
    return "b_" + block_id.replace("-", "_")


def _scale_text(s: Fraction) -> str:
    return str(s.numerator) if s.denominator == 1 else f"{s.numerator}/{s.denominator}"


def _order(blocks: dict[str, ForgeBlock], links: list[ForgeLink]) -> list[str] | None:
    """Blocks in an order where every block comes after its inputs; None if there is a loop."""
    incoming = {b: 0 for b in blocks}
    for link in links:
        incoming[link.target] += 1
    ready = [b for b in blocks if incoming[b] == 0]
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for link in links:
            if link.source == current:
                incoming[link.target] -= 1
                if incoming[link.target] == 0:
                    ready.append(link.target)
    return order if len(order) == len(blocks) else None


def _conv_cost(cin: int, cout: int, k: int, scale: Fraction) -> tuple[int, Fraction]:
    return k * k * cin * cout + cout, Fraction(k * k * cin * cout) * scale * scale


def analyze(raw: ForgeGraph) -> ForgeAnalysis:
    problems: list[ForgeProblem] = []
    blocks: list[ForgeBlock] = []
    seen: set[str] = set()
    attrs: set[str] = set()
    for block in raw.blocks:
        spec = BLOCKS_BY_TYPE.get(block.type)
        if block.id in seen or attr_name(block.id) in attrs:
            problems.append(ForgeProblem(block=block.id, message=f"Two blocks are called {block.id}"))
            continue
        seen.add(block.id)
        attrs.add(attr_name(block.id))
        if spec is None:
            problems.append(
                ForgeProblem(block=block.id, message=f"There's no {block.type} block in this version")
            )
            blocks.append(block)
            continue
        try:
            params = validate_block_params(spec, block.params)
        except (ParamError, ValueError) as exc:
            problems.append(ForgeProblem(block=block.id, message=str(exc)))
            params = {p.name: p.default for p in spec.params}
        blocks.append(block.model_copy(update={"params": params}))
    graph = ForgeGraph(
        blocks=blocks, links=[link for link in raw.links if link.source in seen and link.target in seen]
    )
    by_id = {b.id: b for b in blocks}

    inputs_of: dict[str, list[str]] = {b.id: [] for b in blocks}
    for link in graph.links:
        if link.source == link.target:
            problems.append(ForgeProblem(block=link.source, message="A block can't feed itself"))
            continue
        if link.source in inputs_of[link.target]:
            continue
        inputs_of[link.target].append(link.source)

    starts = [b for b in blocks if b.type == "input"]
    ends = [b for b in blocks if b.type == "output"]
    if len(starts) != 1:
        problems.append(
            ForgeProblem(message="Add exactly one Input block" if not starts else "Use only one Input block")
        )
    if len(ends) != 1:
        problems.append(
            ForgeProblem(message="Add exactly one Output block" if not ends else "Use only one Output block")
        )
    color = str(starts[0].params.get("color", "rgb")) if starts else "rgb"
    in_channels = 1 if color == "y" else 3

    links = [link for link in graph.links if link.source != link.target]
    order = _order(by_id, links)
    shapes: dict[str, _Out] = {}
    cost = _Cost()
    plan: list[dict[str, Any]] = []
    if order is None:
        problems.append(
            ForgeProblem(message="The graph has a loop; data must flow one way, from Input to Output")
        )
        order = []

    def need(block: ForgeBlock, message: str, fix: ForgeFix | None = None) -> None:
        problems.append(ForgeProblem(block=block.id, message=message, fix=fix))

    def feeder_fix(source_id: str, channels: int, why: str) -> ForgeFix | None:
        source = by_id.get(source_id)
        if source is not None and source.type in ("conv", "down", "up"):
            return ForgeFix(
                label=f"Set {why} to {channels} filter{'' if channels == 1 else 's'}",
                block=source.id,
                params={**source.params, "filters": channels},
            )
        if source is not None and source.type == "rdb":
            return ForgeFix(
                label=f"Set {why} to {channels} channels",
                block=source.id,
                params={**source.params, "channels": channels},
            )
        return None

    for block_id in order:
        block = by_id[block_id]
        spec = BLOCKS_BY_TYPE.get(block.type)
        if spec is None:
            continue
        p = block.params
        ins = [shapes[i] for i in inputs_of[block_id] if i in shapes]
        wanted = spec.inputs
        if wanted == 0 and inputs_of[block_id]:
            need(block, "Nothing can feed the Input block")
        if wanted == 1 and len(inputs_of[block_id]) != 1:
            need(
                block,
                f"{spec.label} needs one input"
                if not inputs_of[block_id]
                else f"{spec.label} takes only one input",
            )
            continue
        if wanted == 2 and len(inputs_of[block_id]) < 2:
            need(block, f"{spec.label} needs two or more inputs")
            continue
        if len(ins) != len(inputs_of[block_id]):
            continue  # an input is already broken; its problem is reported there
        step: dict[str, Any] = {
            "id": block_id,
            "name": attr_name(block_id),
            "type": block.type,
            "inputs": [attr_name(i) for i in inputs_of[block_id]],
            "args": {},
        }
        out: _Out
        if block.type == "input":
            out = _Out(in_channels, Fraction(1))
            step["args"] = {"channels": in_channels}
        elif block.type == "output":
            src = ins[0]
            out = src
            if src.channels != in_channels:
                need(
                    block,
                    f"The output has {src.channels} channels but the input has {in_channels}",
                    feeder_fix(inputs_of[block_id][0], in_channels, "the block before Output"),
                )
            if src.scale.denominator != 1 or int(src.scale) not in SCALES:
                need(
                    block,
                    f"The output is {_scale_text(src.scale)}× the input; "
                    "use a whole factor of 1, 2, 3, 4 or 8",
                )
        elif block.type in ("conv", "down", "up"):
            src = ins[0]
            k = int(p.get("kernel", 3)) if block.type == "conv" else 3
            filters = int(p["filters"])
            if block.type == "down":
                scale = src.scale / 2
                params_n, _ = _conv_cost(src.channels, filters, 3, scale)
                macs = Fraction(9 * src.channels * filters) * scale * scale
            elif block.type == "up":
                scale = src.scale * 2
                params_n = 4 * src.channels * filters + filters
                macs = Fraction(4 * src.channels * filters) * src.scale * src.scale
            else:
                scale = src.scale
                params_n, macs = _conv_cost(src.channels, filters, k, scale)
            if p.get("act") == "prelu":
                params_n += filters
            cost.reach += Fraction(k // 2) / src.scale if block.type == "conv" else Fraction(1) / src.scale
            cost.params += params_n
            cost.macs += macs
            cost.activations += 2 * filters * scale * scale
            out = _Out(filters, scale)
            step["args"] = {"cin": src.channels, "cout": filters, "act": p.get("act", "none")}
            if block.type == "conv":
                step["args"]["kernel"] = k
        elif block.type == "activation":
            src = ins[0]
            out = src
            if p["act"] == "prelu":
                cost.params += src.channels
            cost.activations += src.channels * src.scale * src.scale
            step["args"] = {"act": p["act"], "channels": src.channels}
        elif block.type == "norm":
            src = ins[0]
            out = src
            cost.params += 2 * src.channels
            cost.activations += src.channels * src.scale * src.scale
            step["args"] = {"kind": p["kind"], "channels": src.channels}
        elif block.type == "dropout":
            out = ins[0]
            step["args"] = {"p": float(p["p"])}
        elif block.type == "res":
            src = ins[0]
            n = int(p["blocks"])
            per, macs = _conv_cost(src.channels, src.channels, 3, src.scale)
            cost.params += 2 * n * per
            cost.macs += 2 * n * macs
            cost.reach += Fraction(2 * n) / src.scale
            cost.activations += 3 * n * src.channels * src.scale * src.scale
            out = src
            step["args"] = {"channels": src.channels, "blocks": n, "res_scale": float(p["res_scale"])}
        elif block.type == "rdb":
            src = ins[0]
            ch, layers = int(p["channels"]), int(p["layers"])
            params_n, macs = _conv_cost(src.channels, ch, 3, src.scale)
            for i in range(1, layers + 1):
                a, b = _conv_cost(i * ch, ch, 3, src.scale)
                params_n, macs = params_n + a, macs + b
            a, b = _conv_cost((layers + 1) * ch, ch, 1, src.scale)
            cost.params += params_n + a
            cost.macs += macs + b
            cost.reach += Fraction(layers + 1) / src.scale
            cost.activations += 2 * (layers + 2) * ch * src.scale * src.scale
            out = _Out(ch, src.scale)
            step["args"] = {"cin": src.channels, "channels": ch, "layers": layers}
        elif block.type == "attention":
            src = ins[0]
            r = int(p["reduction"])
            mid = max(1, src.channels // r)
            cost.params += src.channels * mid + mid + mid * src.channels + src.channels
            cost.activations += src.channels * src.scale * src.scale
            out = src
            step["args"] = {"channels": src.channels, "reduction": r}
        elif block.type in ("add", "concat"):
            scales = {s.scale for s in ins}
            if len(scales) > 1:
                need(
                    block,
                    f"{spec.label} needs inputs of the same size; these are "
                    + ", ".join(sorted(f"{_scale_text(s)}×" for s in scales)),
                )
                continue
            if block.type == "add":
                channels = {s.channels for s in ins}
                if len(channels) > 1:
                    target = max(ins, key=lambda s: s.channels).channels
                    wrong = next(
                        i for i, s in zip(inputs_of[block_id], ins, strict=True) if s.channels != target
                    )
                    need(
                        block,
                        "Add needs inputs with the same channels; these have "
                        + " and ".join(str(c) for c in sorted(channels)),
                        feeder_fix(wrong, target, wrong),
                    )
                    continue
                out = ins[0]
            else:
                out = _Out(sum(s.channels for s in ins), ins[0].scale)
            cost.activations += out.channels * out.scale * out.scale
        elif block.type == "d2s":
            src = ins[0]
            r = int(p["factor"])
            if src.channels % (r * r):
                target = max(r * r, round(src.channels / (r * r)) * r * r)
                downstream = [link.target for link in links if link.source == block_id]
                if downstream and by_id[downstream[0]].type == "output":
                    target = in_channels * r * r
                need(
                    block,
                    f"Depth-to-space ×{r} needs channels divisible by {r * r}; it gets {src.channels}",
                    feeder_fix(inputs_of[block_id][0], target, "the block before it"),
                )
                continue
            out = _Out(src.channels // (r * r), src.scale * r)
            step["args"] = {"factor": r}
        elif block.type == "upsample":
            src = ins[0]
            r = int(p["factor"])
            out = _Out(src.channels, src.scale * r)
            cost.activations += src.channels * out.scale * out.scale
            step["args"] = {"factor": r, "mode": p["mode"]}
        else:  # pragma: no cover - every catalog type is handled above
            continue
        shapes[block_id] = out
        plan.append(step)

    if order and ends and starts:
        reach = _reachable(starts[0].id, links)
        for block in blocks:
            if block.id not in reach and block.type != "input":
                problems.append(
                    ForgeProblem(block=block.id, message="This block isn't connected to the Input")
                )
        feeds = _feeds(ends[0].id, links)
        for block in blocks:
            if block.id not in feeds and block.type != "output" and block.id in reach:
                problems.append(
                    ForgeProblem(block=block.id, message="Nothing from this block reaches the Output")
                )

    # Deduplicate (a block can be reported twice through different paths).
    unique: list[ForgeProblem] = []
    for problem in problems:
        if all(problem.message != u.message or problem.block != u.block for u in unique):
            unique.append(problem)

    out_scale = shapes[ends[0].id].scale if ends and ends[0].id in shapes else None
    downs = sum(1 for b in blocks if b.type == "down")
    train_bytes = (
        float(cost.activations) * ESTIMATE_BATCH * ESTIMATE_PATCH**2 * 4 * 2  # forward and backward
        + cost.params * 16  # weights, gradients and Adam's two moments, float32
        + 300 * 2**20  # CUDA context and workspace
    )
    stats = ForgeStats(
        params=cost.params,
        macs_per_pixel=int(cost.macs),
        gmacs_per_megapixel=round(float(cost.macs) * 1e6 / 1e9, 2),
        scale=int(out_scale) if not unique and out_scale is not None else None,
        color="y" if color == "y" else "rgb",
        layers=len(plan),
        train_memory_mb=int(train_bytes / 2**20),
        patch_multiple=2**downs if downs else 1,
        context=min(96, max(8, math.ceil(cost.reach) + 4)),
    )
    return ForgeAnalysis(
        graph=graph,
        shapes={k: ForgeShape(channels=v.channels, scale=_scale_text(v.scale)) for k, v in shapes.items()},
        problems=unique,
        stats=stats,
        plan=plan if not unique else [],
    )


def _reachable(start: str, links: list[ForgeLink]) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        current = stack.pop()
        for link in links:
            if link.source == current and link.target not in seen:
                seen.add(link.target)
                stack.append(link.target)
    return seen


def _feeds(end: str, links: list[ForgeLink]) -> set[str]:
    seen, stack = {end}, [end]
    while stack:
        current = stack.pop()
        for link in links:
            if link.target == current and link.source not in seen:
                seen.add(link.source)
                stack.append(link.source)
    return seen
