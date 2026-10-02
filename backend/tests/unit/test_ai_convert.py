from pathlib import Path

import h5py
import numpy as np
import pytest
from safetensors.numpy import load_file

from siqe.ai.convert import ConversionError, siqe_classic_from_h5
from tests.unit.ai_helpers import write_fake_v10


def test_keras_kernels_become_pytorch_layout(tmp_path: Path) -> None:
    weights = write_fake_v10(tmp_path / "v10.h5")
    siqe_classic_from_h5(tmp_path / "v10.h5", tmp_path / "out.safetensors")
    state = load_file(str(tmp_path / "out.safetensors"))
    assert len(state) == 24
    assert state["entry.weight"].shape == (64, 1, 5, 5)
    assert state["block1.c3.weight"].shape == (64, 192, 3, 3)
    assert state["tail.weight"].shape == (9, 32, 3, 3)
    kernel, bias = weights["conv2d_8"]
    np.testing.assert_array_equal(state["block2.c2.weight"][5, 7], kernel[:, :, 7, 5])
    np.testing.assert_array_equal(state["block2.c2.bias"], bias)


def test_files_that_are_not_v10_are_refused(tmp_path: Path) -> None:
    with h5py.File(tmp_path / "other.h5", "w") as f:
        f.create_group("model_weights").create_group("dense")
    with pytest.raises(ConversionError, match="conv2d"):
        siqe_classic_from_h5(tmp_path / "other.h5", tmp_path / "out.safetensors")
