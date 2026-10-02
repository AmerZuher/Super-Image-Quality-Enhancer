"""Converting downloaded weights into the formats SIQE Studio loads. numpy only, no torch.

SIQE Classic ships as the original Keras ``v10.h5``; it is converted once, at download time,
to safetensors with PyTorch layer names and layout (out, in, kh, kw).
"""

from pathlib import Path

import h5py
import numpy as np
from safetensors.numpy import save_file

# Keras layer → PyTorch module, in network order (see siqe.ai.archs.siqe_classic).
SIQE_CLASSIC_LAYERS = {
    "conv2d": "entry",
    "conv2d_1": "block1.head",
    "conv2d_2": "block1.c1",
    "conv2d_3": "block1.c2",
    "conv2d_4": "block1.c3",
    "conv2d_5": "block1.fuse",
    "conv2d_6": "block2.head",
    "conv2d_7": "block2.c1",
    "conv2d_8": "block2.c2",
    "conv2d_9": "block2.c3",
    "conv2d_10": "block2.fuse",
    "conv2d_11": "tail",
}


class ConversionError(ValueError):
    pass


def siqe_classic_state(h5_path: Path) -> dict[str, np.ndarray]:
    state: dict[str, np.ndarray] = {}
    with h5py.File(h5_path, "r") as f:
        if "model_weights" not in f:
            raise ConversionError("not a Keras model file (no model_weights group)")
        weights = f["model_weights"]
        for keras_name, torch_name in SIQE_CLASSIC_LAYERS.items():
            try:
                group = weights[keras_name][keras_name]
                kernel = np.asarray(group["kernel:0"], dtype=np.float32)
                bias = np.asarray(group["bias:0"], dtype=np.float32)
            except KeyError as exc:
                raise ConversionError(f"layer {keras_name} is missing") from exc
            # Keras: (kh, kw, in, out). PyTorch: (out, in, kh, kw).
            state[f"{torch_name}.weight"] = np.ascontiguousarray(kernel.transpose(3, 2, 0, 1))
            state[f"{torch_name}.bias"] = bias
    return state


def siqe_classic_from_h5(h5_path: Path, out_path: Path) -> None:
    save_file(siqe_classic_state(h5_path), str(out_path), metadata={"source": "SIQE v10 (Keras 2.10)"})
