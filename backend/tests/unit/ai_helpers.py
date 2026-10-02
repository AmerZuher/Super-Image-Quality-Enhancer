"""Shared helpers for AI tests: a synthetic Keras v10 file and a numpy reference forward pass."""

from pathlib import Path

import h5py
import numpy as np

from siqe.ai.convert import SIQE_CLASSIC_LAYERS

# (kernel, in, out) per Keras layer, as in v10.h5.
SHAPES = {
    "conv2d": (5, 1, 64),
    "conv2d_1": (3, 64, 64),
    "conv2d_2": (3, 64, 64),
    "conv2d_3": (3, 128, 64),
    "conv2d_4": (3, 192, 64),
    "conv2d_5": (1, 256, 64),
    "conv2d_6": (3, 64, 32),
    "conv2d_7": (3, 32, 32),
    "conv2d_8": (3, 64, 32),
    "conv2d_9": (3, 96, 32),
    "conv2d_10": (1, 128, 32),
    "conv2d_11": (3, 32, 9),
}


def write_fake_v10(path: Path, seed: int = 0) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    rng = np.random.default_rng(seed)
    weights: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    with h5py.File(path, "w") as f:
        root = f.create_group("model_weights")
        for name, (k, cin, cout) in SHAPES.items():
            kernel = (rng.standard_normal((k, k, cin, cout)) * np.sqrt(2 / (k * k * cin))).astype(np.float32)
            bias = (rng.standard_normal(cout) * 0.01).astype(np.float32)
            g = root.create_group(name).create_group(name)
            g["kernel:0"] = kernel
            g["bias:0"] = bias
            weights[name] = (kernel, bias)
    assert set(weights) == set(SIQE_CLASSIC_LAYERS)
    return weights


def _conv_same(x: np.ndarray, kernel: np.ndarray, bias: np.ndarray) -> np.ndarray:
    """Keras Conv2D(padding='same') on H×W×C, written independently of PyTorch."""
    k = kernel.shape[0]
    p = k // 2
    h, w, _ = x.shape
    padded = np.pad(x, ((p, p), (p, p), (0, 0)))
    out = np.zeros((h, w, kernel.shape[3]), np.float64)
    for dy in range(k):
        for dx in range(k):
            out += padded[dy : dy + h, dx : dx + w] @ kernel[dy, dx]
    return out + bias


def keras_v10_forward(y: np.ndarray, weights: dict[str, tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """The original model graph, layer by layer, on an H×W luminance array."""

    def conv(name: str, x: np.ndarray) -> np.ndarray:
        return np.maximum(_conv_same(x, *weights[name]), 0)

    x0 = conv("conv2d", y[:, :, None].astype(np.float64))
    a1 = conv("conv2d_1", x0)
    a2 = conv("conv2d_2", a1)
    a3 = conv("conv2d_3", np.concatenate([a1, a2], 2))
    a4 = conv("conv2d_4", np.concatenate([a1, a2, a3], 2))
    b = conv("conv2d_5", np.concatenate([a1, a2, a3, a4], 2)) + a1
    c1 = conv("conv2d_6", b)
    c2 = conv("conv2d_7", c1)
    c3 = conv("conv2d_8", np.concatenate([c1, c2], 2))
    c4 = conv("conv2d_9", np.concatenate([c1, c2, c3], 2))
    d = conv("conv2d_10", np.concatenate([c1, c2, c3, c4], 2)) + c1
    t = conv("conv2d_11", d)  # H×W×9
    # tf.nn.depth_to_space(block_size=3) with one output channel.
    h, w, _ = t.shape
    return t.reshape(h, w, 3, 3).transpose(0, 2, 1, 3).reshape(h * 3, w * 3)
