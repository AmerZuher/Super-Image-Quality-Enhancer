"""The flow document: nodes, their settings and the edges between them, and its validation.

A document is stored as JSON on the flow and copied onto every run, so editing a flow never
changes a run in progress. Validation returns problems a person can fix ("Export has no
input") rather than raising on the first one, so the editor can mark every bad node.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from siqe.flows.catalog import NODES_BY_TYPE, ParamError, validate_params

MAX_NODES = 60


class Position(BaseModel):
    x: float = 0
    y: float = 0


class Node(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)
    label: str | None = Field(default=None, max_length=80)


class Edge(BaseModel):
    source: str
    target: str
    port: str = "out"


class FlowDocument(BaseModel):
    version: Literal[1] = 1
    nodes: list[Node] = Field(default_factory=list, max_length=MAX_NODES)
    edges: list[Edge] = Field(default_factory=list, max_length=MAX_NODES * 4)


class Problem(BaseModel):
    node: str | None = None
    message: str


def check(doc: FlowDocument) -> tuple[FlowDocument, list[Problem]]:
    """Normalise parameters and list everything that would stop the flow from running."""
    problems: list[Problem] = []
    ids: set[str] = set()
    nodes: list[Node] = []
    for node in doc.nodes:
        if node.id in ids:
            problems.append(Problem(node=node.id, message=f"Two blocks share the id {node.id}"))
            continue
        ids.add(node.id)
        spec = NODES_BY_TYPE.get(node.type)
        if spec is None:
            problems.append(Problem(node=node.id, message=f"Unknown block type '{node.type}'"))
            nodes.append(node)
            continue
        try:
            params = validate_params(spec, node.params)
        except ParamError as exc:
            problems.append(Problem(node=node.id, message=f"{node.label or spec.label}: {exc}"))
            params = node.params
        nodes.append(node.model_copy(update={"params": params}))

    by_id = {n.id: n for n in nodes}
    inputs = [n for n in nodes if n.type == "input"]
    if len(inputs) != 1:
        problems.append(Problem(message="A flow needs exactly one Images block to start from"))

    edges: list[Edge] = []
    incoming: dict[str, int] = {}
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in doc.edges:
        source, target = by_id.get(edge.source), by_id.get(edge.target)
        if source is None or target is None:
            problems.append(Problem(message="A connection points at a block that doesn't exist"))
            continue
        source_spec, target_spec = NODES_BY_TYPE.get(source.type), NODES_BY_TYPE.get(target.type)
        if source_spec is None or target_spec is None:
            continue
        if edge.port not in source_spec.outputs:
            problems.append(
                Problem(node=source.id, message=f"{source_spec.label} has no output '{edge.port}'")
            )
            continue
        if target_spec.inputs == 0:
            problems.append(Problem(node=target.id, message=f"Nothing can connect into {target_spec.label}"))
            continue
        key = (edge.source, edge.target, edge.port)
        if key in seen_edges or edge.source == edge.target:
            continue
        seen_edges.add(key)
        edges.append(edge)
        incoming[edge.target] = incoming.get(edge.target, 0) + 1

    if _has_cycle(nodes, edges):
        problems.append(Problem(message="The connections go round in a loop; a flow must only go forward"))

    reachable = _reachable(inputs[0].id, edges) if len(inputs) == 1 else set()
    for node in nodes:
        spec = NODES_BY_TYPE.get(node.type)
        if spec is None or node.type == "input":
            continue
        if not incoming.get(node.id):
            problems.append(Problem(node=node.id, message=f"{node.label or spec.label} has no input"))
        elif inputs and node.id not in reachable:
            problems.append(Problem(node=node.id, message=f"{node.label or spec.label} can't be reached"))
    finishing = [n for n in nodes if (s := NODES_BY_TYPE.get(n.type)) and s.category == "output"]
    if nodes and not finishing:
        problems.append(
            Problem(message="Add a Finish block (Export, Save to Library, …) so results go somewhere")
        )
    return FlowDocument(nodes=nodes, edges=edges), problems


def _reachable(start: str, edges: list[Edge]) -> set[str]:
    out: dict[str, list[str]] = {}
    for e in edges:
        out.setdefault(e.source, []).append(e.target)
    seen = {start}
    stack = [start]
    while stack:
        for nxt in out.get(stack.pop(), []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _has_cycle(nodes: list[Node], edges: list[Edge]) -> bool:
    out: dict[str, list[str]] = {}
    for e in edges:
        out.setdefault(e.source, []).append(e.target)
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        state[node] = 1
        for nxt in out.get(node, []):
            if state.get(nxt) == 1 or (state.get(nxt) is None and visit(nxt)):
                return True
        state[node] = 2
        return False

    return any(state.get(n.id) is None and visit(n.id) for n in nodes)


def steps_after(doc: dict[str, Any], node_id: str, port: str = "out") -> list[str]:
    """Targets of ``node_id``'s ``port`` in a stored document (plain dict, for workflows)."""
    return [
        e["target"] for e in doc.get("edges", []) if e["source"] == node_id and e.get("port", "out") == port
    ]


def input_node(doc: dict[str, Any]) -> str:
    return str(next(n["id"] for n in doc.get("nodes", []) if n["type"] == "input"))


def node_by_id(doc: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(n for n in doc.get("nodes", []) if n["id"] == node_id)
