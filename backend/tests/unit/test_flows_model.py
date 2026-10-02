"""Flow documents: the node catalog, validation, recipes and conditions."""

from datetime import UTC, datetime
from typing import Any

import pytest

from siqe.flows.catalog import NODES, NODES_BY_TYPE, ParamError, catalog, validate_params
from siqe.flows.document import FlowDocument, check, input_node, steps_after
from siqe.flows.recipes import RECIPES, validated
from siqe.library.rules import RuleSet, matches


def _doc(nodes: list[tuple[str, str, dict[str, Any]]], edges: list[tuple[str, str, str]]) -> FlowDocument:
    return FlowDocument.model_validate(
        {
            "nodes": [{"id": i, "type": t, "params": p} for i, t, p in nodes],
            "edges": [{"source": s, "target": t, "port": port} for s, t, port in edges],
        }
    )


def test_catalog_is_complete_and_serialisable() -> None:
    assert len({n.type for n in NODES}) == len(NODES)
    entries = catalog()
    assert {e["type"] for e in entries} == set(NODES_BY_TYPE)
    for node in NODES:
        if node.type != "add_to_album":  # the album has to be chosen
            validate_params(node, {})  # defaults are valid on their own
    assert all(e["queue"] != "gpu" or e["ai"] for e in entries)


def test_params_are_validated_and_normalised() -> None:
    resize = NODES_BY_TYPE["resize"]
    assert validate_params(resize, {"size": 1024})["size"] == 1024
    with pytest.raises(ParamError, match="between"):
        validate_params(resize, {"size": 5})
    with pytest.raises(ParamError, match="whole number"):
        validate_params(resize, {"size": 10.5})
    with pytest.raises(ParamError, match="no setting"):
        validate_params(resize, {"colour": 3})
    tags = validate_params(NODES_BY_TYPE["tag"], {"tags": [" Trip ", "trip", "Beach"]})
    assert tags["tags"] == ["trip", "beach"]
    with pytest.raises(ParamError, match="#ffffff"):
        validate_params(NODES_BY_TYPE["canvas"], {"color": "red"})
    with pytest.raises(ParamError, match="lossless"):
        validate_params(NODES_BY_TYPE["export"], {"format": "png", "target_kb": 100})
    with pytest.raises(ParamError, match="Adjustments"):
        validate_params(NODES_BY_TYPE["adjust"], {"ops": [{"id": "nope"}]})
    with pytest.raises(ParamError, match="Choose album"):
        validate_params(NODES_BY_TYPE["add_to_album"], {})


def test_a_simple_flow_checks_clean() -> None:
    doc, problems = check(
        _doc(
            [("in", "input", {}), ("r", "resize", {"size": 800}), ("x", "export", {"format": "webp"})],
            [("in", "r", "out"), ("r", "x", "out")],
        )
    )
    assert problems == []
    stored = doc.model_dump()
    assert input_node(stored) == "in"
    assert steps_after(stored, "in") == ["r"]
    export = next(n for n in stored["nodes"] if n["id"] == "x")
    assert export["params"]["quality"] == 90  # defaults filled in


@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        ([("r", "resize", {})], [], "exactly one Images"),
        ([("in", "input", {}), ("r", "resize", {})], [], "Resize has no input"),
        ([("in", "input", {}), ("r", "resize", {})], [("in", "r", "out")], "Finish block"),
        (
            [("in", "input", {}), ("c", "condition", {}), ("x", "export", {})],
            [("in", "c", "out"), ("c", "x", "maybe")],
            "no output 'maybe'",
        ),
        (
            [("in", "input", {}), ("a", "resize", {}), ("b", "rotate", {}), ("x", "export", {})],
            [("in", "a", "out"), ("a", "b", "out"), ("b", "a", "out"), ("b", "x", "out")],
            "loop",
        ),
        ([("in", "input", {}), ("x", "teleport", {})], [("in", "x", "out")], "Unknown block"),
        (
            [("in", "input", {}), ("r", "resize", {}), ("x", "export", {})],
            [("in", "r", "out"), ("r", "in", "out"), ("r", "x", "out")],
            "Nothing can connect into",
        ),
    ],
)
def test_problems_are_reported(
    nodes: list[tuple[str, str, dict[str, Any]]], edges: list[tuple[str, str, str]], message: str
) -> None:
    _, problems = check(_doc(nodes, edges))
    assert any(message in p.message for p in problems), problems


def test_every_recipe_is_a_valid_flow() -> None:
    for recipe in RECIPES:
        doc = validated(recipe)
        assert doc["nodes"][0]["type"] == "input"
        has_ai = any(NODES_BY_TYPE[n["type"]].ai for n in doc["nodes"])
        assert has_ai == recipe.ai, recipe.id


def test_conditions_match_like_smart_albums() -> None:
    facts = {
        "width": 4000,
        "height": 3000,
        "format": "jpeg",
        "color": "blue",
        "tags": ["Lake", "mountain"],
        "sharpness": 0.2,
        "has_gps": True,
        "ai_result": False,
        "duplicate": False,
        "taken_at": datetime(2024, 6, 1, tzinfo=UTC),
        "created_at": datetime(2026, 9, 30, tzinfo=UTC),
        "name": "IMG_0042.jpg",
        "folder": "Trips/2024/a.jpg",
    }
    now = datetime(2026, 10, 2, tzinfo=UTC)

    def ok(*rules: dict[str, Any], match: str = "all") -> bool:
        return matches(RuleSet.model_validate({"match": match, "rules": list(rules)}), facts, now=now)

    assert ok({"field": "orientation", "op": "is", "value": "landscape"})
    assert not ok({"field": "orientation", "op": "is_not", "value": "landscape"})
    assert ok({"field": "aspect", "op": "approx", "value": 1.333})
    assert ok({"field": "tag", "op": "has", "value": "lake"})
    assert ok(
        {"field": "sharpness", "op": "lte", "value": 0.3}, {"field": "has_gps", "op": "is", "value": True}
    )
    assert ok({"field": "taken", "op": "before", "value": "2024-06-01"})
    assert ok({"field": "added_days", "op": "lte", "value": 7})
    assert ok({"field": "name", "op": "contains", "value": "img_"})
    assert ok({"field": "folder", "op": "starts_with", "value": "Trips"})
    assert ok(
        {"field": "width", "op": "lte", "value": 100},
        {"field": "color", "op": "is", "value": "blue"},
        match="any",
    )
    assert not ok(
        {"field": "width", "op": "lte", "value": 100},
        {"field": "color", "op": "is", "value": "red"},
        match="any",
    )
    assert matches(RuleSet(), facts)  # no rules lets everything through
