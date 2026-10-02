import type { Edge, Node } from "@xyflow/react";
import type {
  ForgeAnalysis,
  ForgeBlock,
  ForgeBlockType,
  ForgeFix,
  ForgeGraph,
  ForgeProblem,
  ForgeShape,
} from "@/lib/api/client";

export const NODE_WIDTH = 160;
/** Horizontal distance between blocks in a chain (the templates use it too). */
export const COLUMN = 200;
export const DRAG_TYPE = "application/x-siqe-forge-block";

export interface BlockData extends Record<string, unknown> {
  block: ForgeBlock;
  spec: ForgeBlockType | undefined;
  problems: string[];
  shape: ForgeShape | undefined;
  summary: string;
}

export type BlockNode = Node<BlockData, "block">;

/** 357001 → "357k", 1234567 → "1.23M". */
export function compact(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toPrecision(3)}B`;
  if (n >= 1e6) return `${(n / 1e6).toPrecision(3)}M`;
  if (n >= 1e4) return `${Math.round(n / 1e3)}k`;
  if (n >= 1e3) return `${(n / 1e3).toPrecision(2)}k`;
  return String(n);
}

/** "64 ch", "1 ch ×3", "64 ch ×1/2". */
export function shapeLabel(shape: ForgeShape | undefined): string {
  if (!shape) return "";
  const scale = shape.scale === "1" ? "" : ` ×${shape.scale}`;
  return `${shape.channels} ch${scale}`;
}

function choiceLabel(spec: ForgeBlockType | undefined, name: string, value: unknown): string {
  const param = spec?.params.find((p) => p.name === name);
  const choice = param?.choices?.find((c) => c.value === String(value));
  return choice?.label ?? String(value ?? "");
}

/** One line describing a block's settings, shown on the canvas. */
const filters = (n: unknown) => `${n} filter${Number(n) === 1 ? "" : "s"}`;

export function blockSummary(block: ForgeBlock, spec: ForgeBlockType | undefined): string {
  const p = block.params ?? {};
  const act = (key = "act") => (p[key] && p[key] !== "none" ? ` · ${choiceLabel(spec, key, p[key])}` : "");
  switch (block.type) {
    case "input":
      return p.color === "y" ? "Brightness (Y) only" : "Full colour (RGB)";
    case "output":
      return "The finished image";
    case "conv":
      return `${filters(p.filters)} · ${p.kernel}×${p.kernel}${act()}`;
    case "activation":
      return choiceLabel(spec, "act", p.act);
    case "norm":
      return choiceLabel(spec, "kind", p.kind);
    case "dropout":
      return `Drop ${Math.round(Number(p.p ?? 0) * 100)}% of channels`;
    case "res":
      return `${p.blocks} blocks${Number(p.res_scale ?? 1) !== 1 ? ` · scale ${p.res_scale}` : ""}`;
    case "rdb":
      return `${p.layers} layers · ${p.channels} growth`;
    case "attention":
      return `Reduction ${p.reduction}`;
    case "add":
      return "Sum of its inputs";
    case "concat":
      return "Channels side by side";
    case "d2s":
      return `×${p.factor} from channels`;
    case "upsample":
      return `×${p.factor} · ${choiceLabel(spec, "mode", p.mode)}`;
    case "down":
      return `${filters(p.filters)} · half size${act()}`;
    case "up":
      return `${filters(p.filters)} · double size${act()}`;
    default:
      return spec?.summary ?? "";
  }
}

export function problemsByBlock(problems: ForgeProblem[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const problem of problems) {
    if (!problem.block) continue;
    map.set(problem.block, [...(map.get(problem.block) ?? []), problem.message]);
  }
  return map;
}

export function edgeId(link: { source: string; target: string }): string {
  return `${link.source}->${link.target}`;
}

export function toCanvas(
  graph: ForgeGraph,
  specs: Map<string, ForgeBlockType>,
  analysis: ForgeAnalysis | undefined,
  selected: string | null,
): { nodes: BlockNode[]; edges: Edge[] } {
  const problems = problemsByBlock(analysis?.problems ?? []);
  const nodes: BlockNode[] = (graph.blocks ?? []).map((block) => {
    const spec = specs.get(block.type);
    return {
      id: block.id,
      type: "block",
      position: { x: block.position?.x ?? 0, y: block.position?.y ?? 0 },
      selected: block.id === selected,
      deletable: block.type !== "input",
      data: {
        block,
        spec,
        problems: problems.get(block.id) ?? [],
        shape: analysis?.shapes[block.id],
        summary: blockSummary(block, spec),
      },
    };
  });
  const edges: Edge[] = (graph.links ?? []).map((link) => {
    const shape = analysis?.shapes[link.source];
    const broken = (problems.get(link.target) ?? []).length > 0 && !(problems.get(link.source) ?? []).length;
    return {
      id: edgeId(link),
      source: link.source,
      target: link.target,
      label: shapeLabel(shape) || undefined,
      className: broken ? "forge-edge-err" : "forge-edge",
    };
  });
  return { nodes, edges };
}

/** Back from the canvas: keeps each block's settings, takes positions from the nodes. */
export function fromCanvas(graph: ForgeGraph, nodes: BlockNode[]): ForgeGraph {
  const ids = new Set(nodes.map((n) => n.id));
  return {
    ...graph,
    blocks: nodes.map((n) => ({
      ...n.data.block,
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
    })),
    links: (graph.links ?? []).filter((l) => ids.has(l.source) && ids.has(l.target)),
  };
}

export function newBlockId(type: string, existing: string[]): string {
  const taken = new Set(existing);
  for (let i = 1; ; i++) {
    const id = `${type}${i}`;
    if (!taken.has(id)) return id;
  }
}

export function defaultParams(spec: ForgeBlockType): Record<string, unknown> {
  return Object.fromEntries(spec.params.map((p) => [p.name, p.default]));
}

/** Somewhere free for a new block: right of the selected one, else right of everything. */
export function placeNew(graph: ForgeGraph, selected: string | null): { x: number; y: number } {
  const blocks = graph.blocks ?? [];
  const from = blocks.find((b) => b.id === selected);
  if (from) {
    const x = (from.position?.x ?? 0) + COLUMN;
    let y = from.position?.y ?? 0;
    while (
      blocks.some((b) => Math.abs((b.position?.x ?? 0) - x) < 120 && Math.abs((b.position?.y ?? 0) - y) < 80)
    ) {
      y += 110;
    }
    return { x, y };
  }
  const right = blocks.reduce((m, b) => Math.max(m, b.position?.x ?? 0), -COLUMN);
  return { x: right + COLUMN, y: blocks[0]?.position?.y ?? 120 };
}

function reaches(graph: ForgeGraph, from: string, to: string): boolean {
  const next = new Map<string, string[]>();
  for (const l of graph.links ?? []) next.set(l.source, [...(next.get(l.source) ?? []), l.target]);
  const stack = [from];
  const seen = new Set<string>();
  while (stack.length) {
    const id = stack.pop() as string;
    if (id === to) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...(next.get(id) ?? []));
  }
  return false;
}

/** Why a new link isn't allowed, or null when it is. */
export function connectionProblem(
  link: { source: string | null; target: string | null },
  graph: ForgeGraph,
  specs: Map<string, ForgeBlockType>,
): string | null {
  const { source, target } = link;
  if (!source || !target) return "Drag from a block's right edge to another block's left edge.";
  if (source === target) return "A block can't feed itself.";
  const blocks = graph.blocks ?? [];
  const from = blocks.find((b) => b.id === source);
  const to = blocks.find((b) => b.id === target);
  if (!from || !to) return "That block no longer exists.";
  const fromSpec = specs.get(from.type);
  const toSpec = specs.get(to.type);
  if (fromSpec && !fromSpec.has_output) return `${fromSpec.label} is the end of the model.`;
  if (toSpec && toSpec.inputs === 0) return `${toSpec.label} is where the image comes in; nothing feeds it.`;
  const links = graph.links ?? [];
  if (links.some((l) => l.source === source && l.target === target))
    return "Those blocks are already linked.";
  if (toSpec && toSpec.inputs === 1 && links.some((l) => l.target === target)) {
    return `${toSpec.label} takes one input. Remove its link first, or use Add or Concat to merge.`;
  }
  if (reaches(graph, target, source)) return "That link would make a loop.";
  return null;
}

/** Apply a one-click fix: new settings for one block. */
export function applyFix(graph: ForgeGraph, fix: ForgeFix): ForgeGraph {
  return {
    ...graph,
    blocks: (graph.blocks ?? []).map((b) =>
      b.id === fix.block ? { ...b, params: { ...(b.params ?? {}), ...fix.params } } : b,
    ),
  };
}

/** The largest patch that fits the dataset's crops at this scale, as a multiple the model needs. */
export function suggestedPatch(crop: number, scale: number, multiple: number, wanted = 48): number {
  const fit = Math.floor(crop / Math.max(1, scale));
  const patch = Math.min(wanted, fit);
  return Math.max(multiple, patch - (patch % Math.max(1, multiple)));
}
