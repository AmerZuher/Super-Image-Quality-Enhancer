"""The SIGGRAPH 2017 colorization network (Zhang et al., "Real-Time User-Guided Image
Colorization with Learned Deep Priors"), ported for inference.

Architecture and weights: https://github.com/richzhang/colorization, BSD-2-Clause,
Copyright (c) 2016, Richard Zhang, Phillip Isola, Alexei A. Efros. Module names match the
original so its state dict loads as is. Only automatic colorization is used: no colour hints.
"""

import torch
from torch import nn

L_CENT, L_NORM, AB_NORM = 50.0, 100.0, 110.0


def _convs(cin: int, cout: int, n: int, dilation: int = 1) -> list[nn.Module]:
    layers: list[nn.Module] = []
    for i in range(n):
        layers += [
            nn.Conv2d(cin if i == 0 else cout, cout, 3, padding=dilation, dilation=dilation, bias=True),
            nn.ReLU(True),
        ]
    return [*layers, nn.BatchNorm2d(cout)]


class SiggraphColorizer(nn.Module):
    def __init__(self, classes: int = 529) -> None:
        super().__init__()
        self.model1 = nn.Sequential(*_convs(4, 64, 2))
        self.model2 = nn.Sequential(*_convs(64, 128, 2))
        self.model3 = nn.Sequential(*_convs(128, 256, 3))
        self.model4 = nn.Sequential(*_convs(256, 512, 3))
        self.model5 = nn.Sequential(*_convs(512, 512, 3, dilation=2))
        self.model6 = nn.Sequential(*_convs(512, 512, 3, dilation=2))
        self.model7 = nn.Sequential(*_convs(512, 512, 3))
        self.model8up = nn.Sequential(nn.ConvTranspose2d(512, 256, 4, stride=2, padding=1, bias=True))
        self.model3short8 = nn.Sequential(nn.Conv2d(256, 256, 3, padding=1, bias=True))
        self.model8 = nn.Sequential(
            nn.ReLU(True),
            nn.Conv2d(256, 256, 3, padding=1, bias=True),
            nn.ReLU(True),
            nn.Conv2d(256, 256, 3, padding=1, bias=True),
            nn.ReLU(True),
            nn.BatchNorm2d(256),
        )
        self.model9up = nn.Sequential(nn.ConvTranspose2d(256, 128, 4, stride=2, padding=1, bias=True))
        self.model2short9 = nn.Sequential(nn.Conv2d(128, 128, 3, padding=1, bias=True))
        self.model9 = nn.Sequential(
            nn.ReLU(True), nn.Conv2d(128, 128, 3, padding=1, bias=True), nn.ReLU(True), nn.BatchNorm2d(128)
        )
        self.model10up = nn.Sequential(nn.ConvTranspose2d(128, 128, 4, stride=2, padding=1, bias=True))
        self.model1short10 = nn.Sequential(nn.Conv2d(64, 128, 3, padding=1, bias=True))
        self.model10 = nn.Sequential(
            nn.ReLU(True), nn.Conv2d(128, 128, 3, padding=1, bias=True), nn.LeakyReLU(negative_slope=0.2)
        )
        # The classification head is part of the checkpoint but unused for automatic colorization.
        self.model_class = nn.Sequential(nn.Conv2d(256, classes, 1, bias=True))
        self.model_out = nn.Sequential(nn.Conv2d(128, 2, 1, bias=True), nn.Tanh())

    def forward(self, lightness: torch.Tensor) -> torch.Tensor:
        """N×1×H×W CIELAB lightness (0..100, H and W multiples of 8) → N×2×H×W ab."""
        hints = torch.zeros_like(lightness).repeat(1, 3, 1, 1)  # no ab hints, no hint mask
        conv1 = self.model1(torch.cat(((lightness - L_CENT) / L_NORM, hints), dim=1))
        conv2 = self.model2(conv1[:, :, ::2, ::2])
        conv3 = self.model3(conv2[:, :, ::2, ::2])
        conv4 = self.model4(conv3[:, :, ::2, ::2])
        conv7 = self.model7(self.model6(self.model5(conv4)))
        conv8 = self.model8(self.model8up(conv7) + self.model3short8(conv3))
        conv9 = self.model9(self.model9up(conv8) + self.model2short9(conv2))
        conv10 = self.model10(self.model10up(conv9) + self.model1short10(conv1))
        return self.model_out(conv10) * AB_NORM
