"""Writing PyTorch-format checkpoints without torch, for testing ``siqe.ai.pth``.

``torch.save`` pickles tensors as calls to ``torch._utils._rebuild_tensor_v2`` with a
persistent id for each storage. These helpers produce the same bytes by pickling stand-ins
under the same names (registered as modules only while pickling).
"""

import io
import pickle
import struct
import sys
import types
import zipfile
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np

_STORAGE_NAMES = {
    np.dtype("float32"): "FloatStorage",
    np.dtype("float16"): "HalfStorage",
    np.dtype("int64"): "LongStorage",
}


class _StorageType:
    pass


def _rebuild_tensor_v2(*args: object) -> None:  # never called; only its name is pickled
    raise AssertionError


@contextmanager
def _fake_torch() -> Iterator[dict[str, type]]:
    saved = {name: sys.modules.get(name) for name in ("torch", "torch._utils")}
    torch_mod = types.ModuleType("torch")
    utils_mod = types.ModuleType("torch._utils")
    types_by_name: dict[str, type] = {}
    for name in _STORAGE_NAMES.values():
        cls = type(name, (_StorageType,), {"__module__": "torch"})
        setattr(torch_mod, name, cls)
        types_by_name[name] = cls
    _rebuild_tensor_v2.__module__ = "torch._utils"
    utils_mod._rebuild_tensor_v2 = _rebuild_tensor_v2  # type: ignore[attr-defined]
    torch_mod._utils = utils_mod  # type: ignore[attr-defined]
    sys.modules["torch"], sys.modules["torch._utils"] = torch_mod, utils_mod
    try:
        yield types_by_name
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _Tensor:
    def __init__(self, key: str, array: np.ndarray) -> None:
        self.key = key
        self.array = np.ascontiguousarray(array)


def _pickle(obj: object, storage_types: dict[str, type]) -> bytes:
    buf = io.BytesIO()

    class P(pickle.Pickler):
        def persistent_id(self, o: object) -> object:
            if isinstance(o, tuple) and len(o) == 2 and o[0] == "__storage__":
                t: _Tensor = o[1]
                kind = storage_types[_STORAGE_NAMES[t.array.dtype]]
                return ("storage", kind, t.key, "cpu", t.array.size)
            return None

        def reducer_override(self, o: object) -> object:
            if isinstance(o, _Tensor):
                stride = tuple(s // o.array.itemsize for s in o.array.strides)
                args = (("__storage__", o), 0, o.array.shape, stride, False, OrderedDict())
                return _rebuild_tensor_v2, args
            return NotImplemented

    P(buf, protocol=2).dump(obj)
    return buf.getvalue()


def write_checkpoint(
    path: Path, tensors: dict[str, np.ndarray], *, legacy: bool = False, wrap: bool = True
) -> None:
    """A checkpoint like ``torch.save({"state_dict": tensors}, path)``."""
    stand_ins = {k: _Tensor(str(i), v) for i, (k, v) in enumerate(tensors.items())}
    obj: object = {"epoch": 3, "state_dict": OrderedDict(stand_ins)} if wrap else OrderedDict(stand_ins)
    with _fake_torch() as storage_types:
        data = _pickle(obj, storage_types)
    if legacy:
        with path.open("wb") as f:
            f.write(pickle.dumps(0x1950A86A20F9469CFC6C, protocol=2))
            f.write(pickle.dumps(1001, protocol=2))
            f.write(pickle.dumps({"little_endian": True}, protocol=2))
            f.write(data)
            f.write(pickle.dumps([t.key for t in stand_ins.values()], protocol=2))
            for t in stand_ins.values():
                f.write(struct.pack("<q", t.array.size))
                f.write(t.array.tobytes())
        return
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("archive/data.pkl", data)
        for t in stand_ins.values():
            z.writestr(f"archive/data/{t.key}", t.array.tobytes())
        z.writestr("archive/version", "3\n")


def tiny_clip(
    seed: int = 0, width: int = 128, text_width: int = 128, layers: int = 2
) -> dict[str, np.ndarray]:
    """Random CLIP weights in the OpenAI layout, small enough for unit tests."""
    rng = np.random.default_rng(seed)

    def r(*shape: int, scale: float = 0.05) -> np.ndarray:
        return (rng.standard_normal(shape) * scale).astype(np.float32)

    w: dict[str, np.ndarray] = {
        "visual.conv1.weight": r(width, 3, 32, 32, scale=0.01),
        "visual.class_embedding": r(width),
        "visual.positional_embedding": r(50, width),
        "visual.ln_pre.weight": np.ones(width, np.float32),
        "visual.ln_pre.bias": np.zeros(width, np.float32),
        "visual.ln_post.weight": np.ones(width, np.float32),
        "visual.ln_post.bias": np.zeros(width, np.float32),
        "visual.proj": r(width, 512),
        "token_embedding.weight": r(49408, text_width),
        "positional_embedding": r(77, text_width),
        "ln_final.weight": np.ones(text_width, np.float32),
        "ln_final.bias": np.zeros(text_width, np.float32),
        "text_projection": r(text_width, 512),
        "logit_scale": np.array(4.6052, np.float32),
    }
    for prefix, d in (("visual.transformer", width), ("transformer", text_width)):
        for i in range(layers):
            p = f"{prefix}.resblocks.{i}."
            w[p + "ln_1.weight"] = np.ones(d, np.float32)
            w[p + "ln_1.bias"] = np.zeros(d, np.float32)
            w[p + "ln_2.weight"] = np.ones(d, np.float32)
            w[p + "ln_2.bias"] = np.zeros(d, np.float32)
            w[p + "attn.in_proj_weight"] = r(3 * d, d)
            w[p + "attn.in_proj_bias"] = r(3 * d)
            w[p + "attn.out_proj.weight"] = r(d, d)
            w[p + "attn.out_proj.bias"] = r(d)
            w[p + "mlp.c_fc.weight"] = r(4 * d, d)
            w[p + "mlp.c_fc.bias"] = r(4 * d)
            w[p + "mlp.c_proj.weight"] = r(d, 4 * d)
            w[p + "mlp.c_proj.bias"] = r(d)
    return w
