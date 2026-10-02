import { describe, expect, it } from "vitest";
import type { FlowDocument, FlowNodeType, FlowRunItem } from "@/lib/api/client";
import {
  connectionProblem,
  countsByNode,
  defaultParams,
  fromCanvas,
  newNodeId,
  placeNew,
  problemsByNode,
  summarize,
  toCanvas,
} from "./graph";

function spec(type: string, extra: Partial<FlowNodeType> = {}): FlowNodeType {
  return {
    type,
    label: type,
    category: "edit",
    category_label: "Edit",
    summary: `${type} summary`,
    inputs: 1,
    outputs: ["out"],
    queue: "cpu",
    ai: false,
    transforms: true,
    writes_library: false,
    params: [],
    ...extra,
  };
}

const SPECS = new Map<string, FlowNodeType>([
  ["input", spec("input", { category: "input", inputs: 0 })],
  ["condition", spec("condition", { category: "condition", outputs: ["yes", "no"] })],
  [
    "resize",
    spec("resize", {
      params: [
        {
          name: "mode",
          label: "Fit",
          kind: "choice",
          default: "longest",
          unit: "",
          help: "",
          optional: false,
          choices: [{ value: "longest", label: "Longest side" }],
        },
        {
          name: "size",
          label: "Size",
          kind: "integer",
          default: 2048,
          unit: "px",
          help: "",
          optional: false,
        },
        {
          name: "upscale",
          label: "Enlarge",
          kind: "boolean",
          default: false,
          unit: "",
          help: "",
          optional: false,
        },
      ],
    }),
  ],
  ["export", spec("export", { category: "output", outputs: [] })],
]);

const DOC: FlowDocument = {
  version: 1,
  nodes: [
    { id: "in", type: "input", params: {}, position: { x: 0, y: 80 } },
    {
      id: "if",
      type: "condition",
      params: { rules: { match: "all", rules: [{ field: "orientation", op: "is", value: "landscape" }] } },
      position: { x: 240, y: 80 },
    },
    {
      id: "small",
      type: "resize",
      params: { mode: "longest", size: 1024, upscale: false },
      position: { x: 480, y: 0 },
    },
    { id: "out", type: "export", params: {}, position: { x: 720, y: 0 } },
  ],
  edges: [
    { source: "in", target: "if", port: "out" },
    { source: "if", target: "small", port: "yes" },
    { source: "small", target: "out", port: "out" },
  ],
};

describe("flow graph", () => {
  it("round-trips a document through the canvas", () => {
    const { nodes, edges } = toCanvas(DOC, SPECS);
    expect(nodes).toHaveLength(4);
    expect(nodes[0]?.deletable).toBe(false);
    expect(edges.find((e) => e.source === "if")).toMatchObject({ sourceHandle: "yes", label: "Yes" });
    expect(fromCanvas(nodes, edges)).toEqual(DOC);
  });

  it("summarises what a block is set to do", () => {
    const [, condition, resize] = DOC.nodes ?? [];
    expect(summarize(condition as never, SPECS.get("condition"))).toBe("Landscape");
    expect(summarize(resize as never, SPECS.get("resize"))).toBe("Longest side · 1024 px");
    expect(summarize({ id: "x", type: "mystery", params: {} }, undefined)).toBe("Unknown block");
  });

  it("refuses loops, self-links, duplicates and feeding the input", () => {
    const at = (source: string, target: string, sourceHandle = "out") => ({
      source,
      target,
      sourceHandle,
      targetHandle: "in",
    });
    expect(connectionProblem(at("out", "in"), DOC, SPECS)).toMatch(/Images block/);
    expect(connectionProblem(at("small", "small"), DOC, SPECS)).toMatch(/itself/);
    expect(connectionProblem(at("small", "if"), DOC, SPECS)).toMatch(/loop/);
    expect(connectionProblem(at("if", "small", "yes"), DOC, SPECS)).toMatch(/already/);
    expect(connectionProblem(at("if", "out", "no"), DOC, SPECS)).toBeNull();
  });

  it("names new blocks uniquely and places them to the right", () => {
    expect(newNodeId("resize", ["resize-1", "resize-2"])).toBe("resize-3");
    expect(placeNew(DOC, "if")).toEqual({ x: 240 + 196 + 48, y: 80 });
    expect(placeNew(DOC).x).toBeGreaterThan(720);
    expect(placeNew({ version: 1, nodes: [], edges: [] })).toEqual({ x: 0, y: 80 });
  });

  it("fills in default settings", () => {
    expect(defaultParams(SPECS.get("resize") as FlowNodeType)).toEqual({
      mode: "longest",
      size: 2048,
      upscale: false,
    });
  });

  it("counts images per block from a run's steps", () => {
    const item = (nodes: string[]) => ({ steps: nodes.map((node) => ({ node })) }) as unknown as FlowRunItem;
    const counts = countsByNode([item(["if", "small", "out"]), item(["if"]), item(["if", "if"])]);
    expect(Object.fromEntries(counts)).toEqual({ if: 3, small: 1, out: 1 });
  });

  it("groups problems by block", () => {
    const map = problemsByNode([
      { node: "small", message: "a" },
      { node: null, message: "global" },
      { node: "small", message: "b" },
    ]);
    expect(map.get("small")).toEqual(["a", "b"]);
    expect(map.size).toBe(1);
  });
});
