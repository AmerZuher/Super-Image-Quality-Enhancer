"""Forge datasets: the degradation chain and building crops from images."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import pyvips

from siqe.core.config import get_settings
from siqe.forge import datasets
from siqe.forge.degrade import Degradation, Range, degrade, pair, to_input


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("SIQE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _photo(path: Path, width: int, height: int, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width] / 40.0
    base = (np.sin(x * rng.uniform(0.5, 2)) + np.cos(y * rng.uniform(0.5, 2)))[..., None] * rng.random(3)
    pixels = np.clip((base + 2) * 60 + rng.normal(0, 10, (height, width, 3)), 0, 255).astype(np.uint8)
    pyvips.Image.new_from_memory(pixels, width, height, 3, "uchar").jpegsave(str(path), Q=95)
    return path


def test_degrade_shrinks_by_the_scale_and_respects_off_switches() -> None:
    hr = np.random.default_rng(0).integers(0, 255, (96, 96, 3), dtype=np.uint8)
    off = Degradation(blur_chance=0, noise_chance=0, jpeg_chance=0)
    lr = degrade(hr, 3, off, np.random.default_rng(1))
    assert lr.shape == (32, 32, 3) and lr.dtype == np.uint8
    # Without damage, a flat image stays flat.
    flat = np.full((64, 64, 3), 120, np.uint8)
    assert np.all(degrade(flat, 2, off, np.random.default_rng(2)) == 120)
    noisy = Degradation(blur_chance=0, noise_chance=1, noise=Range(low=20, high=20), jpeg_chance=0)
    assert degrade(flat, 2, noisy, np.random.default_rng(3)).std() > 10


def test_degradation_settings_are_clamped_and_ordered() -> None:
    d = Degradation(blur=Range(low=9, high=-1), jpeg=Range(low=5, high=200))
    assert (d.blur.low, d.blur.high) == (0, 5)
    assert (d.jpeg.low, d.jpeg.high) == (10, 100)


def test_pairs_line_up_and_brightness_models_get_one_channel() -> None:
    crop = np.random.default_rng(0).integers(0, 255, (128, 128, 3), dtype=np.uint8)
    hr, lr = pair(crop, 24, 4, Degradation(), np.random.default_rng(0))
    assert hr.shape == (96, 96, 3) and lr.shape == (24, 24, 3)
    assert to_input(hr, "y").shape == (1, 96, 96)
    assert to_input(lr, "rgb").shape == (3, 24, 24)
    assert to_input(hr, "rgb").min() >= 0 and to_input(hr, "rgb").max() <= 1


def test_build_cuts_crops_and_keeps_a_validation_split(data_dir: Path, tmp_path: Path) -> None:
    images = [(uuid.uuid4(), _photo(tmp_path / f"p{i}.jpg", 800, 600, i)) for i in range(10)]
    images.append((uuid.uuid4(), _photo(tmp_path / "small.jpg", 300, 200, 99)))
    dataset_id = uuid.uuid4()
    seen: list[tuple[int, int]] = []
    settings = datasets.DatasetSettings(crop=128, crops_per_image=3, val_every=5)
    built = datasets.build(dataset_id, images, settings, lambda done, total: seen.append((done, total)))
    assert built.images == 10 and built.skipped == 1 and built.reasons == {"too small": 1}
    assert built.val == 4  # two usable images go to validation, two crops each
    assert built.train == 8 * 3
    train = datasets.crops(dataset_id, "train")
    assert len(train) == built.train
    assert pyvips.Image.new_from_file(str(train[0])).width == 128
    assert seen[-1] == (11, 11)
    # Building again replaces the old crops instead of adding to them.
    again = datasets.build(dataset_id, images, settings)
    assert again.train == built.train and len(datasets.crops(dataset_id, "train")) == built.train
    png = datasets.preview(dataset_id, 2, Degradation(), count=2)
    grid = pyvips.Image.new_from_buffer(png, "")
    assert grid.width == 128 + 8 + 128 and grid.height == 2 * 128 + 8
