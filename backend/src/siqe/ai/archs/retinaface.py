"""RetinaFace (ResNet-50) face detector, matching the facexlib checkpoint layout (MIT).

Returns boxes, scores and five landmarks (eyes, nose, mouth corners) per face, which is what
face alignment needs. Preprocessing follows the published model: BGR, mean-subtracted, 0..255.
"""

import math

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn
from torchvision.models import resnet50
from torchvision.models._utils import IntermediateLayerGetter
from torchvision.ops import nms

MIN_SIZES = ((16, 32), (64, 128), (256, 512))
STEPS = (8, 16, 32)
VARIANCE = (0.1, 0.2)
MEAN_BGR = (104.0, 117.0, 123.0)


def _conv_bn(inp: int, oup: int, leaky: float = 0.0) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(inp, oup, 3, 1, 1, bias=False), nn.BatchNorm2d(oup), nn.LeakyReLU(leaky, inplace=True)
    )


def _conv_bn_no_relu(inp: int, oup: int) -> nn.Sequential:
    return nn.Sequential(nn.Conv2d(inp, oup, 3, 1, 1, bias=False), nn.BatchNorm2d(oup))


def _conv_bn1x1(inp: int, oup: int, leaky: float = 0.0) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(inp, oup, 1, 1, 0, bias=False), nn.BatchNorm2d(oup), nn.LeakyReLU(leaky, inplace=True)
    )


class SSH(nn.Module):
    def __init__(self, cin: int, cout: int) -> None:
        super().__init__()
        leaky = 0.1 if cout <= 64 else 0.0
        self.conv3X3 = _conv_bn_no_relu(cin, cout // 2)
        self.conv5X5_1 = _conv_bn(cin, cout // 4, leaky)
        self.conv5X5_2 = _conv_bn_no_relu(cout // 4, cout // 4)
        self.conv7X7_2 = _conv_bn(cout // 4, cout // 4, leaky)
        self.conv7x7_3 = _conv_bn_no_relu(cout // 4, cout // 4)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a = self.conv3X3(x)
        b1 = self.conv5X5_1(x)
        b = self.conv5X5_2(b1)
        c = self.conv7x7_3(self.conv7X7_2(b1))
        return F.relu(torch.cat([a, b, c], 1))


class FPN(nn.Module):
    def __init__(self, channels: tuple[int, int, int], cout: int) -> None:
        super().__init__()
        leaky = 0.1 if cout <= 64 else 0.0
        self.output1 = _conv_bn1x1(channels[0], cout, leaky)
        self.output2 = _conv_bn1x1(channels[1], cout, leaky)
        self.output3 = _conv_bn1x1(channels[2], cout, leaky)
        self.merge1 = _conv_bn(cout, cout, leaky)
        self.merge2 = _conv_bn(cout, cout, leaky)

    def forward(self, feats: list[torch.Tensor]) -> list[torch.Tensor]:
        o1, o2, o3 = self.output1(feats[0]), self.output2(feats[1]), self.output3(feats[2])
        o2 = self.merge2(o2 + F.interpolate(o3, size=o2.shape[2:], mode="nearest"))
        o1 = self.merge1(o1 + F.interpolate(o2, size=o1.shape[2:], mode="nearest"))
        return [o1, o2, o3]


class _Head(nn.Module):
    def __init__(self, cin: int, per_anchor: int, anchors: int = 2) -> None:
        super().__init__()
        self.per_anchor = per_anchor
        self.conv1x1 = nn.Conv2d(cin, anchors * per_anchor, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.conv1x1(x).permute(0, 2, 3, 1).contiguous()
        return out.view(out.shape[0], -1, self.per_anchor)


class RetinaFace(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.body = IntermediateLayerGetter(resnet50(weights=None), {"layer2": 1, "layer3": 2, "layer4": 3})
        self.fpn = FPN((512, 1024, 2048), 256)
        self.ssh1, self.ssh2, self.ssh3 = SSH(256, 256), SSH(256, 256), SSH(256, 256)
        self.ClassHead = nn.ModuleList([_Head(256, 2) for _ in range(3)])
        self.BboxHead = nn.ModuleList([_Head(256, 4) for _ in range(3)])
        self.LandmarkHead = nn.ModuleList([_Head(256, 10) for _ in range(3)])

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        f1, f2, f3 = self.fpn(list(self.body(x).values()))
        feats = [self.ssh1(f1), self.ssh2(f2), self.ssh3(f3)]
        boxes = torch.cat([h(f) for h, f in zip(self.BboxHead, feats, strict=True)], 1)
        scores = torch.cat([h(f) for h, f in zip(self.ClassHead, feats, strict=True)], 1)
        landmarks = torch.cat([h(f) for h, f in zip(self.LandmarkHead, feats, strict=True)], 1)
        return boxes, F.softmax(scores, dim=-1), landmarks


def load_state(model: RetinaFace, state: dict[str, torch.Tensor]) -> RetinaFace:
    model.load_state_dict({k.removeprefix("module."): v for k, v in state.items()})
    return model.eval()


def priors(height: int, width: int) -> torch.Tensor:
    out: list[list[float]] = []
    for sizes, step in zip(MIN_SIZES, STEPS, strict=True):
        for i in range(math.ceil(height / step)):
            for j in range(math.ceil(width / step)):
                for size in sizes:
                    out.append(
                        [(j + 0.5) * step / width, (i + 0.5) * step / height, size / width, size / height]
                    )
    return torch.tensor(out)


@torch.inference_mode()
def detect(
    model: RetinaFace, rgb: np.ndarray, device: str, *, threshold: float = 0.9, iou: float = 0.4
) -> list[tuple[float, np.ndarray, np.ndarray]]:
    """Faces in an H×W×3 uint8 RGB image: (score, box x1 y1 x2 y2, landmarks 5×2), in pixels."""
    h, w = rgb.shape[:2]
    bgr = rgb[:, :, ::-1].astype(np.float32) - np.array(MEAN_BGR, np.float32)
    x = torch.from_numpy(np.ascontiguousarray(bgr.transpose(2, 0, 1)))[None].to(device)
    loc, conf, landm = (t[0].float().cpu() for t in model(x))
    p = priors(h, w)
    centres = p[:, :2] + loc[:, :2] * VARIANCE[0] * p[:, 2:]
    sizes = p[:, 2:] * torch.exp(loc[:, 2:] * VARIANCE[1])
    boxes = torch.cat([centres - sizes / 2, centres + sizes / 2], 1) * torch.tensor([w, h, w, h])
    points = torch.cat(
        [p[:, :2] + landm[:, 2 * k : 2 * k + 2] * VARIANCE[0] * p[:, 2:] for k in range(5)], 1
    ) * torch.tensor([w, h] * 5)
    scores = conf[:, 1]
    keep = scores > threshold
    boxes, points, scores = boxes[keep], points[keep], scores[keep]
    order = nms(boxes, scores, iou)
    return [(float(scores[i]), boxes[i].numpy(), points[i].numpy().reshape(5, 2)) for i in order.tolist()]
