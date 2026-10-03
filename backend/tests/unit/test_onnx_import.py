"""Adding your own ONNX model: the probe finds scale, size step and output range by running
small graphs built here, and refuses what the tiled pipeline can't run."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import onnx
import pytest
import pyvips
from onnx import TensorProto, helper

from siqe.ai import registry
from siqe.ai.governor import TileSettings
from siqe.ai.onnx_import import probe, speed_label, task_for
from siqe.ai.onnx_model import OnnxBackend
from siqe.ai.pipeline import run_model_on_file
from siqe.core.errors import AppError

H, W = "h", "w"


def _save(path: Path, nodes: list[Any], inputs: list[Any], outputs: list[Any], inits: list[Any]) -> Path:
    graph = helper.make_graph(nodes, "test", inputs, outputs, inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.save(model, path)
    return path


def _image(name: str, shape: list[Any] | None = None, kind: int = TensorProto.FLOAT) -> Any:
    return helper.make_tensor_value_info(name, kind, shape or ["n", 3, H, W])


def _upscaler(path: Path, factor: int, *, times: float = 1.0) -> Path:
    """Nearest-neighbour ×factor, then × ``times`` (255 makes a 0..255 model)."""
    scales = helper.make_tensor("scales", TensorProto.FLOAT, [4], [1, 1, factor, factor])
    k = helper.make_tensor("k", TensorProto.FLOAT, [], [times])
    nodes = [
        helper.make_node("Resize", ["x", "", "scales"], ["up"], mode="nearest"),
        helper.make_node("Mul", ["up", "k"], ["y"]),
    ]
    return _save(path, nodes, [_image("x")], [_image("y")], [scales, k])


def _strided(path: Path, stride: int) -> Path:
    """Average-pool down by ``stride`` and back up: like a U-Net, sides must be multiples of it."""
    scales = helper.make_tensor("scales", TensorProto.FLOAT, [4], [1, 1, stride, stride])
    pool = {"kernel_shape": [stride, stride], "strides": [stride, stride]}
    nodes = [
        helper.make_node("AveragePool", ["x"], ["down"], **pool),
        helper.make_node("Resize", ["down", "", "scales"], ["up"], mode="nearest"),
        helper.make_node("Sub", ["x", "up"], ["detail"]),  # fails unless the sides divide evenly
        helper.make_node("Add", ["up", "detail"], ["y"]),
    ]
    return _save(path, nodes, [_image("x")], [_image("y")], [scales])


def test_an_upscaler_is_measured(tmp_path: Path) -> None:
    found = probe(_upscaler(tmp_path / "x2.onnx", 2), threads=1)
    assert (found.scale, found.multiple, found.output_range) == (2, 1, 1)
    assert (found.in_channels, found.out_channels, found.min_input) == (3, 3, 0)
    assert found.input_name == "x" and found.seconds_per_mp >= 0
    assert task_for(found, "deblur") == "upscale"  # models that enlarge are always upscalers


def test_0_to_255_output_is_noticed_and_scaled_back(tmp_path: Path) -> None:
    path = _upscaler(tmp_path / "x1-255.onnx", 1, times=255.0)
    found = probe(path, threads=1)
    assert (found.scale, found.output_range) == (1, 255)
    assert task_for(found, None) == "denoise" and task_for(found, "deblur") == "deblur"
    out = OnnxBackend(path, output_range=255, threads=1).forward(np.full((1, 3, 8, 8), 0.4, np.float32))
    assert np.allclose(out, 0.4, atol=1e-5)


def test_the_size_step_is_found(tmp_path: Path) -> None:
    found = probe(_strided(tmp_path / "unet.onnx", 8), threads=1)
    assert (found.scale, found.multiple) == (1, 8)


def test_fixed_size_models_are_refused(tmp_path: Path) -> None:
    k = helper.make_tensor("k", TensorProto.FLOAT, [], [1.0])
    fixed = [1, 3, 256, 256]
    path = _save(
        tmp_path / "fixed.onnx",
        [helper.make_node("Mul", ["x", "k"], ["y"])],
        [_image("x", fixed)],
        [_image("y", fixed)],
        [k],
    )
    with pytest.raises(AppError) as err:
        probe(path, threads=1)
    assert err.value.code == "onnx.fixed_size"


def test_two_inputs_are_refused(tmp_path: Path) -> None:
    path = _save(
        tmp_path / "two.onnx",
        [helper.make_node("Add", ["a", "b"], ["y"])],
        [_image("a"), _image("b")],
        [_image("y")],
        [],
    )
    with pytest.raises(AppError) as err:
        probe(path, threads=1)
    assert err.value.code == "onnx.unsupported_inputs"


def test_a_classifier_is_not_an_image_model(tmp_path: Path) -> None:
    path = _save(
        tmp_path / "classify.onnx",
        [helper.make_node("GlobalAveragePool", ["x"], ["y"])],
        [_image("x")],
        [_image("y", ["n", 3, 1, 1])],
        [],
    )
    with pytest.raises(AppError) as err:
        probe(path, threads=1)
    assert err.value.code == "onnx.not_image_to_image"


def test_speed_labels() -> None:
    assert [speed_label(s) for s in (0.5, 10, 60)] == ["fast", "balanced", "slow"]


def _install(root: Path, model_id: str, model: Path, task: str = "upscale") -> None:
    folder = root / model_id
    folder.mkdir(parents=True)
    (folder / registry.USER_WEIGHTS).write_bytes(model.read_bytes())
    found = probe(model, threads=1)
    descriptor = {
        "name": "My x2",
        "task": task,
        "speed": "fast",
        "sha256": "0" * 64,
        "size": model.stat().st_size,
        "probe": found.to_dict(),
    }
    (folder / registry.USER_FILE).write_text(json.dumps(descriptor))


def test_added_models_join_the_catalog_and_run_tiled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "models_root", lambda: tmp_path / "models")
    _install(tmp_path / "models", "user-my-x2", _upscaler(tmp_path / "x2.onnx", 2))
    spec = registry.get_spec("user-my-x2")
    assert (spec.arch, spec.scale, spec.task, spec.license) == ("onnx", 2, "upscale", "Your own")
    assert spec in registry.catalog()
    listed = registry.model_to_dict(spec, None)
    assert listed["source"] == "user" and listed["probe"]["scale"] == 2
    assert registry.user_spec("user-../etc") is None

    src = tmp_path / "in.png"
    xyz = pyvips.Image.xyz(90, 70)
    (xyz[0] * 2).bandjoin([xyz[1] * 3, xyz[0] + xyz[1]]).cast("uchar").copy(interpretation="srgb").pngsave(
        str(src)
    )
    out = run_model_on_file(
        src,
        tmp_path / "out.png",
        tmp_path / "canvas.raw",
        backend=OnnxBackend(registry.weights_path(spec), threads=1),
        scale=spec.scale,
        channels=spec.channels,
        settings=TileSettings(tile=32, batch=1, context=8, multiple=spec.multiple),
    )
    assert (out.width, out.height) == (180, 140)
    a = np.asarray(pyvips.Image.new_from_file(str(src)).numpy(), np.int32)
    b = np.asarray(pyvips.Image.new_from_file(str(out.path)).numpy(), np.int32)
    assert np.abs(b[::2, ::2] - a).max() <= 1  # nearest ×2, no seams between tiles


def test_flow_blocks_with_cpu_models_go_to_the_cpu_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from siqe.activities.flows import _with_queues

    monkeypatch.setattr(registry, "models_root", lambda: tmp_path / "models")
    _install(tmp_path / "models", "user-my-x2", _upscaler(tmp_path / "x2.onnx", 2))
    document = {
        "nodes": [
            {"id": "a", "type": "upscale", "params": {"model": "user-my-x2"}},
            {"id": "b", "type": "upscale", "params": {"model": "realesrgan-x4plus"}},
            {"id": "c", "type": "upscale", "params": {"model": "no-such-model"}},
        ],
        "edges": [],
    }
    queues = [n.get("queue") for n in _with_queues(document)["nodes"]]
    assert queues == ["cpu", None, None]
