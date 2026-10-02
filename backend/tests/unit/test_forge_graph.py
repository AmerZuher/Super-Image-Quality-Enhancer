"""Forge graphs: shapes, problems with fixes, statistics and generated code (no torch needed)."""

import ast
from itertools import pairwise
from typing import Any

import pytest

from siqe.forge.codegen import class_name, generate
from siqe.forge.graph import ModelGraph, analyze
from siqe.forge.templates import EMPTY, TEMPLATES, TEMPLATES_BY_ID


def _chain(*blocks: tuple[str, str, dict[str, Any]]) -> ModelGraph:
    return ModelGraph.model_validate(
        {
            "blocks": [{"id": i, "type": t, "params": p} for i, t, p in blocks],
            "links": [{"source": a[0], "target": b[0]} for a, b in pairwise(blocks)],
        }
    )


def _apply(graph: ModelGraph, fix: Any) -> ModelGraph:
    data = graph.model_dump()
    for block in data["blocks"]:
        if block["id"] == fix.block:
            block["params"] = fix.params
    return ModelGraph.model_validate(data)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_every_template_is_valid_and_compiles(template: Any) -> None:
    analysis = analyze(ModelGraph.model_validate(template.graph))
    assert analysis.problems == []
    assert analysis.plan and analysis.stats.scale in (1, 2, 3, 4)
    tree = ast.parse(generate(template.name, analysis))
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    assert class_name(template.name) in classes and "DenseBlock" in classes


def test_siqe_classic_matches_the_real_network() -> None:
    stats = analyze(ModelGraph.model_validate(TEMPLATES_BY_ID["siqe-classic"].graph)).stats
    # Counted layer by layer from siqe.ai.archs.siqe_classic: 1,664 + 274,752 + 77,984 + 2,601.
    assert stats.params == 357_001
    assert (stats.scale, stats.color) == (3, "y")


def test_shapes_follow_the_blocks() -> None:
    analysis = analyze(ModelGraph.model_validate(TEMPLATES_BY_ID["unet-denoise"].graph))
    shapes = {k: (v.channels, v.scale) for k, v in analysis.shapes.items()}
    assert shapes["down"] == (64, "1/2")
    assert shapes["join"] == (64, "1")  # 32 from the encoder + 32 from Up
    assert analysis.stats.patch_multiple == 2


def test_depth_to_space_offers_a_fix() -> None:
    graph = _chain(
        ("in", "input", {"color": "rgb"}),
        ("c", "conv", {"filters": 10}),
        ("s", "d2s", {"factor": "2"}),
        ("out", "output", {}),
    )
    analysis = analyze(graph)
    problem = next(p for p in analysis.problems if p.block == "s")
    assert "divisible by 4" in problem.message
    assert problem.fix is not None and problem.fix.params["filters"] == 12  # 3 channels × 2²
    fixed = analyze(_apply(graph, problem.fix))
    assert fixed.problems == [] and fixed.stats.scale == 2


def test_output_channels_must_match_the_input() -> None:
    graph = _chain(("in", "input", {"color": "y"}), ("c", "conv", {"filters": 3}), ("out", "output", {}))
    problem = analyze(graph).problems[0]
    assert "3 channels but the input has 1" in problem.message
    assert analyze(_apply(graph, problem.fix)).problems == []


def test_add_needs_matching_inputs() -> None:
    graph = ModelGraph.model_validate(
        {
            "blocks": [
                {"id": "in", "type": "input"},
                {"id": "a", "type": "conv", "params": {"filters": 8}},
                {"id": "b", "type": "conv", "params": {"filters": 3}},
                {"id": "sum", "type": "add"},
                {"id": "out", "type": "output"},
            ],
            "links": [
                {"source": "in", "target": "a"},
                {"source": "in", "target": "b"},
                {"source": "a", "target": "sum"},
                {"source": "b", "target": "sum"},
                {"source": "sum", "target": "out"},
            ],
        }
    )
    problem = next(p for p in analyze(graph).problems if p.block == "sum")
    assert "same channels" in problem.message and problem.fix is not None
    assert problem.fix.block == "b" and problem.fix.params["filters"] == 8


@pytest.mark.parametrize(
    ("graph", "message"),
    [
        (ModelGraph.model_validate(EMPTY), "Output needs one input"),
        (
            _chain(("in", "input", {}), ("out", "output", {}), ("x", "conv", {})),
            "isn't connected|reaches the Output",
        ),
        (_chain(("c", "conv", {}), ("out", "output", {})), "exactly one Input"),
        (_chain(("in", "input", {}), ("d", "down", {"filters": 3}), ("out", "output", {})), "1/2× the input"),
        (
            _chain(("in", "input", {}), ("c", "conv", {"filters": 2000}), ("out", "output", {})),
            "between 1 and 1024",
        ),
        (_chain(("in", "input", {}), ("z", "zap", {}), ("out", "output", {})), "no zap block"),
    ],
)
def test_problems_are_explained(graph: ModelGraph, message: str) -> None:
    import re

    assert any(re.search(message, p.message) for p in analyze(graph).problems), analyze(graph).problems


def test_loops_are_refused() -> None:
    graph = ModelGraph.model_validate(
        {
            "blocks": [
                {"id": "in", "type": "input"},
                {"id": "a", "type": "add"},
                {"id": "out", "type": "output"},
            ],
            "links": [
                {"source": "in", "target": "a"},
                {"source": "a", "target": "a"},
                {"source": "a", "target": "out"},
                {"source": "out", "target": "a"},
            ],
        }
    )
    assert any("loop" in p.message or "feed itself" in p.message for p in analyze(graph).problems)


def test_code_for_a_broken_graph_lists_the_problems() -> None:
    code = generate("Broken", analyze(ModelGraph.model_validate(EMPTY)))
    assert code.startswith("# Broken can't be turned into code yet")


def test_memory_estimate_grows_with_the_model() -> None:
    small = analyze(ModelGraph.model_validate(TEMPLATES_BY_ID["espcn"].graph)).stats
    big = analyze(ModelGraph.model_validate(TEMPLATES_BY_ID["edsr-lite"].graph)).stats
    assert big.train_memory_mb > small.train_memory_mb > 300
    assert big.params > small.params
