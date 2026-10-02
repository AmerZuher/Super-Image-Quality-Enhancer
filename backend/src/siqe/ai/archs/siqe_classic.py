"""SIQE Classic: the original Super Image Quality Enhancer network, ported from Keras.

Two residual dense blocks (64 then 32 channels) on the luminance (Y) channel, then a 3×3
convolution to 9 channels and a ×3 pixel shuffle. Layer for layer it matches ``v10.h5``
(Keras 2.10); ``siqe.ai.convert.siqe_classic_from_h5`` maps the weights.
"""

import torch
from torch import nn


def _conv(cin: int, cout: int, k: int) -> nn.Conv2d:
    return nn.Conv2d(cin, cout, k, padding=k // 2)


class DenseBlock(nn.Module):
    def __init__(self, cin: int, ch: int) -> None:
        super().__init__()
        self.head = _conv(cin, ch, 3)
        self.c1 = _conv(ch, ch, 3)
        self.c2 = _conv(2 * ch, ch, 3)
        self.c3 = _conv(3 * ch, ch, 3)
        self.fuse = _conv(4 * ch, ch, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1 = torch.relu(self.head(x))
        x2 = torch.relu(self.c1(x1))
        x3 = torch.relu(self.c2(torch.cat([x1, x2], 1)))
        x4 = torch.relu(self.c3(torch.cat([x1, x2, x3], 1)))
        return torch.relu(self.fuse(torch.cat([x1, x2, x3, x4], 1))) + x1


class SiqeClassic(nn.Module):
    scale = 3

    def __init__(self) -> None:
        super().__init__()
        self.entry = _conv(1, 64, 5)
        self.block1 = DenseBlock(64, 64)
        self.block2 = DenseBlock(64, 32)
        self.tail = _conv(32, 9, 3)
        self.shuffle = nn.PixelShuffle(3)

    def forward(self, y: torch.Tensor) -> torch.Tensor:
        x = torch.relu(self.entry(y))
        x = self.block2(self.block1(x))
        return self.shuffle(torch.relu(self.tail(x)))
