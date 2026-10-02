"""Forge networks in PyTorch. Skipped without torch; run in the ``ai`` image."""

import types
from typing import Any

import pytest

torch = pytest.importorskip("torch")

from siqe.ai.archs.forge import GraphNet  # noqa: E402
from siqe.forge.codegen import class_name, generate  # noqa: E402
from siqe.forge.graph import ForgeGraph, analyze  # noqa: E402
from siqe.forge.templates import TEMPLATES, TEMPLATES_BY_ID  # noqa: E402


def _net(template: Any) -> tuple[GraphNet, Any]:
    analysis = analyze(ForgeGraph.model_validate(template.graph))
    stats = analysis.stats
    return GraphNet(analysis.plan, stats.scale or 1, 1 if stats.color == "y" else 3), analysis


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_shapes_and_parameter_counts_match_the_analysis(template: Any) -> None:
    net, analysis = _net(template)
    assert sum(p.numel() for p in net.parameters()) == analysis.stats.params
    x = torch.rand(2, net.in_channels, 24, 32)
    y = net(x)
    assert y.shape == (2, net.in_channels, 24 * net.scale, 32 * net.scale)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_generated_code_loads_the_same_weights_and_gives_the_same_output(template: Any) -> None:
    torch.manual_seed(0)
    net, analysis = _net(template)
    net.eval()
    module = types.ModuleType("generated")
    exec(compile(generate(template.name, analysis), "generated.py", "exec"), module.__dict__)
    generated = getattr(module, class_name(template.name))()
    generated.load_state_dict(net.state_dict())  # strict: every key matches
    generated.eval()
    x = torch.rand(1, net.in_channels, 16, 16)
    with torch.no_grad():
        assert torch.allclose(net(x), generated(x), atol=1e-6)


def test_siqe_classic_template_takes_the_original_weights() -> None:
    from siqe.ai.archs.siqe_classic import SiqeClassic

    torch.manual_seed(1)
    original = SiqeClassic().eval()
    net, _ = _net(TEMPLATES_BY_ID["siqe-classic"])
    net.eval()
    names = {
        "entry.": "b_entry.conv.",
        "tail.": "b_tail.conv.",
        "block1.": "b_block1.",
        "block2.": "b_block2.",
    }
    convs = {"c1": "convs.0", "c2": "convs.1", "c3": "convs.2"}
    state = {}
    for key, value in original.state_dict().items():
        for old, new in names.items():
            if key.startswith(old):
                rest = key[len(old) :]
                for c_old, c_new in convs.items():
                    rest = rest.replace(f"{c_old}.", f"{c_new}.")
                state[new + rest] = value
    net.load_state_dict(state)
    y = torch.rand(1, 1, 20, 20)
    with torch.no_grad():
        assert torch.allclose(net(y), original(y), atol=1e-5)


# --------------------------------------------------------------------------- training

TINY = {
    "blocks": [
        {"id": "in", "type": "input", "params": {"color": "rgb"}},
        {"id": "c1", "type": "conv", "params": {"filters": 8, "kernel": "3", "act": "relu"}},
        {"id": "c2", "type": "conv", "params": {"filters": 12, "kernel": "3", "act": "none"}},
        {"id": "up", "type": "d2s", "params": {"factor": "2"}},
        {"id": "out", "type": "output"},
    ],
    "links": [
        {"source": "in", "target": "c1"},
        {"source": "c1", "target": "c2"},
        {"source": "c2", "target": "up"},
        {"source": "up", "target": "out"},
    ],
}


@pytest.fixture
def tiny_run(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    import uuid

    import numpy as np
    import pyvips

    from siqe.core.config import get_settings
    from siqe.forge import datasets, trainer
    from siqe.forge.degrade import Degradation
    from siqe.forge.training import TrainSettings

    monkeypatch.setenv("SIQE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    trainer._crops.clear()
    images = []
    for i in range(6):
        rng = np.random.default_rng(i)
        y, x = np.mgrid[0:400, 0:640] / 25.0
        pixels = ((np.sin(x * rng.uniform(0.5, 2)) + np.cos(y)) * 50 + 128)[..., None] * rng.uniform(
            0.5, 1, 3
        )
        path = tmp_path / f"p{i}.png"
        pyvips.Image.new_from_memory(
            np.clip(pixels + rng.normal(0, 6, pixels.shape), 0, 255).astype(np.uint8).copy(),
            640,
            400,
            3,
            "uchar",
        ).pngsave(str(path))
        images.append((uuid.uuid4(), path))
    dataset_id = uuid.uuid4()
    datasets.build(dataset_id, images, datasets.DatasetSettings(crop=96, crops_per_image=4, val_every=3))
    analysis = analyze(ForgeGraph.model_validate(TINY))

    def make(run_id: str, steps: int, **extra: Any) -> Any:
        return trainer.RunSpec(
            run_id=run_id,
            dataset_id=str(dataset_id),
            plan=analysis.plan,
            scale=2,
            color="rgb",
            settings=TrainSettings(steps=steps, batch=4, patch=24, val_every=20, lr=1e-3, **extra),
            degradation=Degradation(),
        )

    yield make
    get_settings.cache_clear()


def _train(spec: Any, stop_after: int | None = None, **kw: Any) -> Any:
    from siqe.forge import trainer

    seen: list[int] = []
    metrics: list[Any] = []
    result = trainer.train_chunk(
        spec,
        "cpu",
        3600,
        should_stop=lambda: stop_after is not None and len(seen) >= stop_after,
        on_progress=lambda step, message: seen.append(step),
        on_metric=metrics.append,
        **kw,
    )
    return result, metrics


def test_training_saves_checkpoints_scores_and_a_sample(tiny_run: Any) -> None:
    from siqe.forge.training import best_weights, last_checkpoint, sample_path

    result, metrics = _train(tiny_run("run-a", 40))
    assert result.done and result.step == 40 and result.batch == 4
    assert [m.step for m in metrics if m.kind == "val"] == [20, 40]
    assert all(m.loss is not None and m.loss > 0 for m in metrics if m.kind == "train")
    val = [m for m in metrics if m.kind == "val"]
    assert all(10 < (m.psnr or 0) < 60 and m.bicubic_psnr is not None for m in val)
    assert result.best_psnr is not None and result.bicubic_psnr is not None
    for path in (last_checkpoint("run-a"), best_weights("run-a"), sample_path("run-a")):
        assert path.exists()


def test_resuming_continues_exactly(tiny_run: Any) -> None:
    from safetensors.torch import load_file

    from siqe.forge.training import last_checkpoint

    _train(tiny_run("whole", 40))
    first, _ = _train(tiny_run("split", 40), stop_after=13)
    assert first.step == 13 and not first.done
    second, _ = _train(tiny_run("split", 40))
    assert second.step == 40 and second.done
    a = torch.load(last_checkpoint("whole"), weights_only=True)["model"]
    b = torch.load(last_checkpoint("split"), weights_only=True)["model"]
    for key in a:
        assert torch.allclose(a[key], b[key], atol=1e-6), key
    assert load_file(str(last_checkpoint("whole").with_name("best.safetensors"))).keys() == a.keys()


def test_running_out_of_memory_halves_the_batch(tiny_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from siqe.forge import trainer

    real = trainer._loss

    def picky(kind: str, sr: Any, hr: Any) -> Any:
        if sr.shape[0] > 1:
            raise RuntimeError("CUDA out of memory. Tried to allocate 1.00 GiB")
        return real(kind, sr, hr)

    monkeypatch.setattr(trainer, "_loss", picky)
    result, _ = _train(tiny_run("oom", 20))
    assert result.done and (result.batch, result.accumulate) == (1, 4)
    assert any("memory ran out" in n for n in result.notes)


def test_a_diverging_run_stops_with_a_clear_error(tiny_run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from siqe.core.errors import AppError
    from siqe.forge import trainer

    monkeypatch.setattr(trainer, "_loss", lambda kind, sr, hr: (sr * float("nan")).mean())
    with pytest.raises(AppError) as err:
        _train(tiny_run("nan", 50))
    assert err.value.code == "forge.diverged"


def test_publishing_scores_the_model_and_ai_lab_can_load_it(tiny_run: Any) -> None:
    from safetensors.torch import load_file

    from siqe.ai import runtime
    from siqe.forge.publish import benchmark
    from siqe.forge.training import best_weights

    spec = tiny_run("pub", 40)
    _train(spec)
    scores = benchmark(spec, best_weights("pub"), "cpu")
    assert set(scores) >= {"psnr", "ssim", "bicubic_psnr", "gain_db", "ms_per_megapixel"}
    assert scores["ms_per_megapixel"] > 0
    loaded = runtime.load_forge(best_weights("pub"), {"plan": spec.plan, "scale": 2, "color": "rgb"})
    assert (loaded.scale, loaded.in_channels, loaded.half_ok) == (2, 3, False)
    reference = GraphNet(spec.plan, 2, 3)
    reference.load_state_dict(load_file(str(best_weights("pub"))))
    x = torch.rand(1, 3, 20, 20)
    with torch.no_grad():
        assert torch.allclose(loaded.module(x), reference.eval()(x))
