import { describe, expect, it } from "vitest";
import type { ForgeBlockType, ForgeGraph } from "@/lib/api/client";
import {
  applyFix,
  blockSummary,
  compact,
  connectionProblem,
  fromCanvas,
  newBlockId,
  placeNew,
  shapeLabel,
  suggestedPatch,
  toCanvas,
} from "./graph";

function spec(type: string, inputs: number, has_output = true): ForgeBlockType {
  return {
    type,
    label: type.charAt(0).toUpperCase() + type.slice(1),
    category: "layers",
    category_label: "Layers",
    summary: "",
    inputs,
    has_output,
    params: [
      {
        name: "act",
        label: "Activation",
        kind: "choice",
        default: "relu",
        unit: "",
        help: "",
        choices: [
          { value: "none", label: "None" },
          { value: "relu", label: "ReLU" },
        ],
      },
    ],
  };
}

const SPECS = new Map(
  [spec("input", 0), spec("conv", 1), spec("add", 2), spec("output", 1, false)].map((s) => [s.type, s]),
);

function graph(): ForgeGraph {
  return {
    version: 1,
    blocks: [
      { id: "in", type: "input", params: { color: "y" }, position: { x: 0, y: 0 } },
      {
        id: "c1",
        type: "conv",
        params: { filters: 64, kernel: "3", act: "relu" },
        position: { x: 240, y: 0 },
      },
      {
        id: "c2",
        type: "conv",
        params: { filters: 1, kernel: "3", act: "none" },
        position: { x: 480, y: 0 },
      },
      { id: "out", type: "output", params: {}, position: { x: 720, y: 0 } },
    ],
    links: [
      { source: "in", target: "c1" },
      { source: "c1", target: "c2" },
      { source: "c2", target: "out" },
    ],
  };
}

describe("forge graph helpers", () => {
  it("formats counts and shapes", () => {
    expect(compact(357001)).toBe("357k");
    expect(compact(1234)).toBe("1.2k");
    expect(compact(22729)).toBe("23k");
    expect(compact(1_234_567)).toBe("1.23M");
    expect(shapeLabel({ channels: 64, scale: "1" })).toBe("64 ch");
    expect(shapeLabel({ channels: 1, scale: "3" })).toBe("1 ch ×3");
  });

  it("summarises blocks in words", () => {
    const g = graph();
    expect(blockSummary(g.blocks?.[1] as never, SPECS.get("conv"))).toBe("64 filters · 3×3 · ReLU");
    expect(blockSummary(g.blocks?.[2] as never, SPECS.get("conv"))).toBe("1 filter · 3×3");
    expect(blockSummary(g.blocks?.[0] as never, SPECS.get("input"))).toBe("Brightness (Y) only");
  });

  it("refuses links that can't work", () => {
    const g = graph();
    expect(connectionProblem({ source: "c1", target: "c1" }, g, SPECS)).toMatch(/itself/);
    expect(connectionProblem({ source: "out", target: "c1" }, g, SPECS)).toMatch(/end of the model/);
    expect(connectionProblem({ source: "c1", target: "in" }, g, SPECS)).toMatch(/nothing feeds it/);
    expect(connectionProblem({ source: "in", target: "c2" }, g, SPECS)).toMatch(/one input/);
    const looped = { ...g, blocks: [...(g.blocks ?? []), { id: "a", type: "add" }] };
    looped.links = [...(g.links ?? []), { source: "c2", target: "a" }];
    expect(connectionProblem({ source: "a", target: "a" }, looped, SPECS)).toMatch(/itself/);
    expect(connectionProblem({ source: "in", target: "a" }, looped, SPECS)).toBeNull();
    const cyc = { ...looped, links: [...(looped.links ?? []), { source: "a", target: "out" }] };
    expect(connectionProblem({ source: "a", target: "c1" }, cyc, SPECS)).toMatch(/one input|loop/);
  });

  it("detects loops through merge blocks", () => {
    const g: ForgeGraph = {
      version: 1,
      blocks: [
        { id: "a", type: "add" },
        { id: "b", type: "add" },
      ],
      links: [{ source: "a", target: "b" }],
    };
    expect(connectionProblem({ source: "b", target: "a" }, g, SPECS)).toMatch(/loop/);
  });

  it("round-trips through the canvas and applies fixes", () => {
    const g = graph();
    const analysis = {
      graph: g,
      shapes: { in: { channels: 1, scale: "1" }, c1: { channels: 64, scale: "1" } },
      problems: [{ block: "c2", message: "Too few", fix: null }],
      stats: {} as never,
    };
    const { nodes, edges } = toCanvas(g, SPECS, analysis, "c1");
    expect(nodes.find((n) => n.id === "c1")?.selected).toBe(true);
    expect(nodes.find((n) => n.id === "in")?.deletable).toBe(false);
    expect(edges.find((e) => e.id === "c1->c2")?.label).toBe("64 ch");
    expect(edges.find((e) => e.id === "c1->c2")?.className).toBe("forge-edge-err");
    const moved = nodes.map((n) => (n.id === "c1" ? { ...n, position: { x: 250.4, y: 9.6 } } : n));
    const back = fromCanvas(
      g,
      moved.filter((n) => n.id !== "c2"),
    );
    expect(back.blocks?.find((b) => b.id === "c1")?.position).toEqual({ x: 250, y: 10 });
    expect(back.links).toEqual([{ source: "in", target: "c1" }]);
    const fixed = applyFix(g, { label: "", block: "c2", params: { filters: 1 } });
    expect(fixed.blocks?.find((b) => b.id === "c2")?.params?.filters).toBe(1);
  });

  it("names and places new blocks", () => {
    const g = graph();
    expect(newBlockId("conv", ["conv1", "conv2"])).toBe("conv3");
    expect(placeNew(g, "c1")).toEqual({ x: 440, y: 110 });
    expect(placeNew(g, null)).toEqual({ x: 920, y: 0 });
  });

  it("suggests a patch that fits the crops", () => {
    expect(suggestedPatch(256, 3, 1)).toBe(48);
    expect(suggestedPatch(256, 8, 1)).toBe(32);
    expect(suggestedPatch(96, 3, 1)).toBe(32);
    expect(suggestedPatch(256, 1, 4, 50)).toBe(48);
  });
});
