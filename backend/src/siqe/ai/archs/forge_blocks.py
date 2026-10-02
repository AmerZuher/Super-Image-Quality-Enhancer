"""The PyTorch modules behind Forge's blocks.

Everything below the marker is copied verbatim into the code Forge generates, so a model
trained here loads into the generated file with ``load_state_dict`` and nothing else.
"""

import torch
from torch import nn
from torch.nn import functional as F

# --- forge blocks ---


def make_act(name: str, channels: int) -> nn.Module:
    """An activation by name; PReLU learns one slope per channel."""
    if name == "relu":
        return nn.ReLU()
    if name == "leaky_relu":
        return nn.LeakyReLU(0.2)
    if name == "prelu":
        return nn.PReLU(channels)
    if name == "gelu":
        return nn.GELU()
    if name == "silu":
        return nn.SiLU()
    if name == "tanh":
        return nn.Tanh()
    if name == "sigmoid":
        return nn.Sigmoid()
    return nn.Identity()


class ConvAct(nn.Module):
    """A convolution (same padding) followed by an activation."""

    def __init__(self, cin: int, cout: int, kernel: int = 3, act: str = "none", stride: int = 1) -> None:
        super().__init__()
        self.conv = nn.Conv2d(cin, cout, kernel, stride=stride, padding=kernel // 2)
        self.act = make_act(act, cout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.act(self.conv(x))


class UpConv(nn.Module):
    """A learned 2× enlargement (transposed convolution) followed by an activation."""

    def __init__(self, cin: int, cout: int, act: str = "none") -> None:
        super().__init__()
        self.conv = nn.ConvTranspose2d(cin, cout, 2, stride=2)
        self.act = make_act(act, cout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.act(self.conv(x))


class Norm(nn.Module):
    def __init__(self, kind: str, channels: int) -> None:
        super().__init__()
        self.norm = nn.BatchNorm2d(channels) if kind == "batch" else nn.GroupNorm(1, channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.norm(x)


class ResBlock(nn.Module):
    """EDSR's block: conv, ReLU, conv, scaled, plus the input."""

    def __init__(self, channels: int, res_scale: float = 1.0) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1)
        self.res_scale = res_scale

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.conv2(F.relu(self.conv1(x))) * self.res_scale


class ResGroup(nn.Sequential):
    def __init__(self, channels: int, blocks: int, res_scale: float = 1.0) -> None:
        super().__init__(*(ResBlock(channels, res_scale) for _ in range(blocks)))


class DenseBlock(nn.Module):
    """A residual dense block: each layer sees all earlier outputs; a 1×1 conv fuses them."""

    def __init__(self, cin: int, channels: int, layers: int = 3) -> None:
        super().__init__()
        self.head = nn.Conv2d(cin, channels, 3, padding=1)
        self.convs = nn.ModuleList(
            nn.Conv2d(i * channels, channels, 3, padding=1) for i in range(1, layers + 1)
        )
        self.fuse = nn.Conv2d((layers + 1) * channels, channels, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        first = F.relu(self.head(x))
        features = [first]
        for conv in self.convs:
            features.append(F.relu(conv(torch.cat(features, 1))))
        return F.relu(self.fuse(torch.cat(features, 1))) + first


class ChannelAttention(nn.Module):
    """Squeeze and excitation: weigh each channel by a learned function of its average."""

    def __init__(self, channels: int, reduction: int = 16) -> None:
        super().__init__()
        mid = max(1, channels // reduction)
        self.down = nn.Conv2d(channels, mid, 1)
        self.up = nn.Conv2d(mid, channels, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        weight = torch.sigmoid(self.up(F.relu(self.down(F.adaptive_avg_pool2d(x, 1)))))
        return x * weight


class Resize(nn.Module):
    """A fixed (not learned) enlargement."""

    def __init__(self, factor: int, mode: str = "bicubic") -> None:
        super().__init__()
        self.factor = factor
        self.mode = mode

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.mode == "nearest":
            return F.interpolate(x, scale_factor=self.factor, mode="nearest")
        return F.interpolate(x, scale_factor=self.factor, mode=self.mode, align_corners=False)
