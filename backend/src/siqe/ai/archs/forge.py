"""Forge models in PyTorch: a network built from a checked graph's plan.

Module attributes are named after the blocks, the same as in the generated code
(``siqe.forge.codegen``), so state dicts are interchangeable.
"""

from typing import Any

import torch
from torch import nn

from siqe.ai.archs.forge_blocks import (
    ChannelAttention,
    ConvAct,
    DenseBlock,
    Norm,
    ResGroup,
    Resize,
    UpConv,
    make_act,
)


def build_module(step: dict[str, Any]) -> nn.Module | None:
    a, t = step["args"], step["type"]
    if t == "conv":
        return ConvAct(a["cin"], a["cout"], a["kernel"], a["act"])
    if t == "down":
        return ConvAct(a["cin"], a["cout"], 3, a["act"], stride=2)
    if t == "up":
        return UpConv(a["cin"], a["cout"], a["act"])
    if t == "activation":
        return make_act(a["act"], a["channels"])
    if t == "norm":
        return Norm(a["kind"], a["channels"])
    if t == "dropout":
        return nn.Dropout2d(a["p"])
    if t == "res":
        return ResGroup(a["channels"], a["blocks"], a["res_scale"])
    if t == "rdb":
        return DenseBlock(a["cin"], a["channels"], a["layers"])
    if t == "attention":
        return ChannelAttention(a["channels"], a["reduction"])
    if t == "d2s":
        return nn.PixelShuffle(a["factor"])
    if t == "upsample":
        return Resize(a["factor"], a["mode"])
    return None


class GraphNet(nn.Module):
    def __init__(self, plan: list[dict[str, Any]], scale: int, in_channels: int) -> None:
        super().__init__()
        if not plan:
            raise ValueError("an empty plan; check the graph first")
        self.plan = plan
        self.scale = scale
        self.in_channels = in_channels
        for step in plan:
            module = build_module(step)
            if module is not None:
                self.add_module(step["name"], module)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        values: dict[str, torch.Tensor] = {}
        for step in self.plan:
            name, inputs, kind = step["name"], step["inputs"], step["type"]
            if kind == "input":
                values[name] = x
            elif kind == "output":
                return values[inputs[0]]
            elif kind == "add":
                total = values[inputs[0]]
                for other in inputs[1:]:
                    total = total + values[other]
                values[name] = total
            elif kind == "concat":
                values[name] = torch.cat([values[i] for i in inputs], 1)
            else:
                values[name] = getattr(self, name)(values[inputs[0]])
        raise ValueError("the plan has no output")
