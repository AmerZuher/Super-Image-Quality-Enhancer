"""Read PyTorch checkpoints into numpy arrays without torch and without running pickled code.

Both the zip format (``torch.save`` since 1.6) and the older single-stream format are
supported. Unpickling is restricted to an allow-list, like ``torch.load(weights_only=True)``:
plain containers and tensor rebuild functions only, so a hostile checkpoint can't run code.
"""

import io
import pickle
import struct
import zipfile
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

LEGACY_MAGIC = 0x1950A86A20F9469CFC6C

_DTYPES: dict[str, np.dtype[Any]] = {
    "FloatStorage": np.dtype("<f4"),
    "DoubleStorage": np.dtype("<f8"),
    "HalfStorage": np.dtype("<f2"),
    "BFloat16Storage": np.dtype("<u2"),  # widened to float32 on materialise
    "LongStorage": np.dtype("<i8"),
    "IntStorage": np.dtype("<i4"),
    "ShortStorage": np.dtype("<i2"),
    "CharStorage": np.dtype("i1"),
    "ByteStorage": np.dtype("u1"),
    "BoolStorage": np.dtype("?"),
}


class CheckpointError(ValueError):
    """The file isn't a checkpoint we can read safely."""


@dataclass
class _Storage:
    kind: str
    key: str
    data: np.ndarray | None = None


@dataclass
class _TensorRef:
    storage: _Storage
    offset: int
    size: tuple[int, ...]
    stride: tuple[int, ...]

    def materialise(self) -> np.ndarray:
        if self.storage.data is None:
            raise CheckpointError(f"storage {self.storage.key} has no data")
        base = self.storage.data
        if not self.size:
            out = base[self.offset : self.offset + 1].reshape(())
        else:
            item = base.itemsize
            out = np.lib.stride_tricks.as_strided(
                base[self.offset :], shape=self.size, strides=tuple(s * item for s in self.stride)
            )
        out = np.array(out)  # own the memory, contiguous
        if self.storage.kind == "BFloat16Storage":
            out = (out.astype(np.uint32) << 16).view(np.float32)
        return out


class _StorageType:
    def __init__(self, name: str) -> None:
        self.name = name


def _rebuild_tensor(
    storage: _Storage, offset: int, size: tuple[int, ...], stride: tuple[int, ...], *_: Any
) -> _TensorRef:
    return _TensorRef(storage, offset, tuple(size), tuple(stride))


def _rebuild_parameter(data: Any, *_: Any) -> Any:
    return data


_ALLOWED: dict[tuple[str, str], Callable[..., Any] | type] = {
    ("collections", "OrderedDict"): OrderedDict,
    ("torch._utils", "_rebuild_tensor_v2"): _rebuild_tensor,
    ("torch._utils", "_rebuild_parameter"): _rebuild_parameter,
    ("torch._utils", "_rebuild_parameter_with_state"): _rebuild_parameter,
}


class _Unpickler(pickle.Unpickler):
    def __init__(self, file: BinaryIO, storages: dict[str, _Storage]) -> None:
        super().__init__(file)
        self.storages = storages

    def find_class(self, module: str, name: str) -> Any:
        if module == "torch" and name in _DTYPES:
            return _StorageType(name)
        found = _ALLOWED.get((module, name))
        if found is None:
            raise CheckpointError(f"refusing to load {module}.{name} from a checkpoint")
        return found

    def persistent_load(self, pid: Any) -> Any:
        if not isinstance(pid, tuple) or not pid or pid[0] != "storage":
            raise CheckpointError("unsupported persistent id in checkpoint")
        kind = pid[1]
        key = str(pid[2])
        if not isinstance(kind, _StorageType):
            raise CheckpointError("unsupported storage type in checkpoint")
        if key not in self.storages:
            self.storages[key] = _Storage(kind.name, key)
        return self.storages[key]


def _resolve(obj: Any) -> Any:
    if isinstance(obj, _TensorRef):
        return obj.materialise()
    if isinstance(obj, dict):
        return type(obj)((k, _resolve(v)) for k, v in obj.items())
    if isinstance(obj, list):
        return [_resolve(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_resolve(v) for v in obj)
    return obj


def _load_zip(path: Path) -> Any:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        pkl = next((n for n in names if n.endswith("/data.pkl") or n == "data.pkl"), None)
        if pkl is None:
            raise CheckpointError("no data.pkl in checkpoint")
        root = pkl[: -len("data.pkl")]
        storages: dict[str, _Storage] = {}
        obj = _Unpickler(io.BytesIO(zf.read(pkl)), storages).load()
        for key, st in storages.items():
            raw = zf.read(f"{root}data/{key}")
            st.data = np.frombuffer(raw, _DTYPES[st.kind])
    return obj


def _load_legacy(path: Path) -> Any:
    with path.open("rb") as f:
        for _ in range(3):  # magic number, protocol version, system info
            header = _Unpickler(f, {}).load()
            if _ == 0 and header != LEGACY_MAGIC:
                raise CheckpointError("not a PyTorch checkpoint")
        storages: dict[str, _Storage] = {}
        obj = _Unpickler(f, storages).load()
        keys = _Unpickler(f, {}).load()
        for key in keys:
            st = storages[str(key)]
            dtype = _DTYPES[st.kind]
            (numel,) = struct.unpack("<q", f.read(8))
            st.data = np.frombuffer(f.read(numel * dtype.itemsize), dtype)
    return obj


def load(path: Path) -> Any:
    """The checkpoint's object with every tensor as a numpy array."""
    obj = _load_zip(path) if zipfile.is_zipfile(path) else _load_legacy(path)
    return _resolve(obj)


def state_dict(path: Path) -> dict[str, np.ndarray]:
    """The model weights in a checkpoint: unwraps ``state_dict`` and strips a ``module.`` prefix."""
    obj = load(path)
    if isinstance(obj, dict) and "state_dict" in obj and isinstance(obj["state_dict"], dict):
        obj = obj["state_dict"]
    if not isinstance(obj, dict):
        raise CheckpointError("checkpoint holds no weights")
    return {str(k).removeprefix("module."): v for k, v in obj.items() if isinstance(v, np.ndarray)}
