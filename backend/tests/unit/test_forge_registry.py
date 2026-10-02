"""Models published from Forge appear in the AI Lab catalog from their descriptor file."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from siqe.ai import registry
from siqe.core.config import get_settings


@pytest.fixture
def models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("SIQE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    registry._forge_cache.clear()
    yield tmp_path / "models"
    get_settings.cache_clear()


def _publish(root: Path, model_id: str, **info: object) -> Path:
    folder = root / model_id
    folder.mkdir(parents=True)
    (folder / registry.FORGE_WEIGHTS).write_bytes(b"weights")
    data = {"name": "My upscaler v1", "scale": 3, "color": "y", "plan": [], "sha256": "ab" * 32, "size": 7}
    data.update(info)
    (folder / registry.FORGE_FILE).write_text(json.dumps(data))
    return folder


def test_published_models_join_the_catalog(models: Path) -> None:
    builtin = len(registry.catalog())
    _publish(models, "forge-my-upscaler-v1", context=15, benchmark={"psnr": 30.1})
    spec = registry.get_spec("forge-my-upscaler-v1")
    assert (spec.arch, spec.task, spec.scale, spec.channels, spec.context) == ("forge", "upscale", 3, "y", 15)
    assert registry.files_present(spec)
    assert len(registry.catalog()) == builtin + 1
    out = registry.model_to_dict(spec, None)
    assert out["source"] == "forge" and out["benchmark"] == {"psnr": 30.1}
    assert registry.model_to_dict(registry.catalog()[0], None)["source"] == "catalog"


def test_restoration_models_and_broken_descriptors(models: Path) -> None:
    _publish(models, "forge-denoiser-v1", scale=1, color="rgb")
    assert registry.get_spec("forge-denoiser-v1").task == "denoise"
    broken = _publish(models, "forge-broken-v1")
    (broken / registry.FORGE_FILE).write_text("{not json")
    with pytest.raises(Exception, match="No model called"):
        registry.get_spec("forge-broken-v1")
    with pytest.raises(Exception, match="No model called"):
        registry.get_spec("forge-../../etc")


def test_removing_the_folder_removes_the_model(models: Path) -> None:
    folder = _publish(models, "forge-gone-v1")
    spec = registry.get_spec("forge-gone-v1")
    registry.remove_files(spec)
    assert not folder.exists()
    assert all(s.id != "forge-gone-v1" for s in registry.catalog())
