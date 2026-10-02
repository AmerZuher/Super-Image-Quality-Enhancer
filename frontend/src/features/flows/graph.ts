import type { Connection, Edge, Node } from "@xyflow/react";
import { describeRule } from "@/features/library/rules";
import type {
  FlowDocument,
  FlowEdge,
  FlowNode,
  FlowNodeType,
  FlowParam,
  FlowRunItem,
  RuleSet,
} from "@/lib/api/client";

/** What a block on the canvas carries: its saved node plus what the editor knows about it. */
export interface BlockData extends Record<string, unknown> {
  node: FlowNode;
  spec?: FlowNodeType;
  problems: string[];
  /** Images that went through this block in the run being shown. */
  count?: number;
  summary: string;
}

export type BlockNode = Node<BlockData, "block">;

export interface SummaryContext {
  models?: { id: string; name: string }[];
  albums?: { id: string; name: string }[];
}

export const NODE_WIDTH = 196;

/** Drag-and-drop type for blocks dragged from the palette onto the canvas. */
export const DRAG_TYPE = "application/x-siqe-block";

export function edgeId(edge: FlowEdge): string {
  return `${edge.source}:${edge.port}->${edge.target}`;
}

export function defaultParams(spec: FlowNodeType): Record<string, unknown> {
  return Object.fromEntries(spec.params.map((p) => [p.name, structuredClone(p.default ?? null)]));
}

function choiceLabel(param: FlowParam, value: unknown): string {
  return param.choices?.find((c) => c.value === value)?.label ?? String(value);
}

/** One line under a block's name saying what it is set to do. */
export function summarize(node: FlowNode, spec: FlowNodeType | undefined, ctx: SummaryContext = {}): string {
  if (!spec) return "Unknown block";
  const p = node.params ?? {};
  const param = (name: string) => spec.params.find((x) => x.name === name);
  switch (spec.type) {
    case "input":
      return "The images you run it on";
    case "condition": {
      const rules = p.rules as RuleSet | undefined;
      const list = rules?.rules ?? [];
      if (list.length === 0) return "No rules yet";
      const joiner = rules?.match === "any" ? " or " : " and ";
      return list.map(describeRule).join(joiner);
    }
    case "resize": {
      const mode = param("mode");
      return `${mode ? choiceLabel(mode, p.mode) : p.mode} · ${p.size} px${p.upscale ? " · may enlarge" : ""}`;
    }
    case "crop":
    case "canvas":
      return `${p.aspect}${spec.type === "canvas" ? ` · ${p.color === "transparent" ? "transparent" : p.color}` : ""}`;
    case "rotate":
      return (
        [p.angle !== "0" ? `${p.angle}°` : null, p.flip !== "none" ? `flip ${p.flip}` : null]
          .filter(Boolean)
          .join(" · ") || "No change"
      );
    case "watermark":
      return p.text ? `“${String(p.text)}”` : "No text yet";
    case "export": {
      const format = param("format");
      const bits = [format ? choiceLabel(format, p.format) : String(p.format)];
      if (p.max_side) bits.push(`≤ ${p.max_side} px`);
      if (p.target_kb) bits.push(`≤ ${p.target_kb} KB`);
      if (p.folder) bits.push(`/${String(p.folder)}`);
      return bits.join(" · ");
    }
    case "tag":
      return ((p.tags as string[] | undefined) ?? []).join(", ") || "No tags yet";
    case "add_to_album": {
      const album = ctx.albums?.find((a) => a.id === p.album);
      return album ? album.name : "Choose an album";
    }
    case "adjust": {
      const ops = (p.ops as { id: string }[] | undefined) ?? [];
      return ops.length ? ops.map((o) => o.id.replace(/_/g, " ")).join(", ") : "No adjustments yet";
    }
    case "trim":
      return `Margin ${p.margin} px`;
    default: {
      if (typeof p.model === "string") {
        return ctx.models?.find((m) => m.id === p.model)?.name ?? p.model;
      }
      return spec.summary;
    }
  }
}

export function toCanvas(
  doc: FlowDocument,
  specs: Map<string, FlowNodeType>,
  options: {
    problems?: Map<string, string[]>;
    counts?: Map<string, number>;
    selected?: string | null;
    ctx?: SummaryContext;
  } = {},
): { nodes: BlockNode[]; edges: Edge[] } {
  const nodes: BlockNode[] = (doc.nodes ?? []).map((node) => {
    const spec = specs.get(node.type);
    return {
      id: node.id,
      type: "block",
      position: { x: node.position?.x ?? 0, y: node.position?.y ?? 0 },
      selected: options.selected === node.id,
      deletable: node.type !== "input",
      data: {
        node,
        spec,
        problems: options.problems?.get(node.id) ?? [],
        count: options.counts?.get(node.id),
        summary: summarize(node, spec, options.ctx),
      },
    };
  });
  const edges: Edge[] = (doc.edges ?? []).map((edge) => ({
    id: edgeId(edge),
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.port,
    targetHandle: "in",
    label: edge.port === "yes" ? "Yes" : edge.port === "no" ? "No" : undefined,
  }));
  return { nodes, edges };
}

export function fromCanvas(nodes: BlockNode[], edges: Edge[]): FlowDocument {
  return {
    version: 1,
    nodes: nodes.map((n) => ({
      ...n.data.node,
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
    })),
    edges: edges.map((e) => ({ source: e.source, target: e.target, port: e.sourceHandle ?? "out" })),
  };
}

export function newNodeId(type: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  for (let n = 1; ; n++) {
    const id = `${type}-${n}`;
    if (!used.has(id)) return id;
  }
}

/** Where to drop a new block: right of the selected one, or right of the rightmost block. */
export function placeNew(doc: FlowDocument, afterId?: string | null): { x: number; y: number } {
  const nodes = doc.nodes ?? [];
  const anchor = nodes.find((n) => n.id === afterId);
  if (anchor?.position) return { x: anchor.position.x + NODE_WIDTH + 48, y: anchor.position.y };
  if (nodes.length === 0) return { x: 0, y: 80 };
  const right = nodes.reduce((a, b) => ((a.position?.x ?? 0) >= (b.position?.x ?? 0) ? a : b));
  return { x: (right.position?.x ?? 0) + NODE_WIDTH + 48, y: right.position?.y ?? 80 };
}

/** Why a connection isn't allowed, or null if it is. */
export function connectionProblem(
  connection: Connection | Edge,
  doc: FlowDocument,
  specs: Map<string, FlowNodeType>,
): string | null {
  const { source, target } = connection;
  if (!source || !target) return "Connect a block's right side to another block's left side.";
  if (source === target) return "A block can't feed itself.";
  const nodes = new Map((doc.nodes ?? []).map((n) => [n.id, n]));
  const targetSpec = specs.get(nodes.get(target)?.type ?? "");
  if (targetSpec && targetSpec.inputs === 0) return "Nothing can feed the Images block.";
  const port = connection.sourceHandle ?? "out";
  const edges = doc.edges ?? [];
  if (edges.some((e) => e.source === source && e.target === target && e.port === port)) {
    return "Those blocks are already connected.";
  }
  // Would it make a loop? Walk forward from the target; reaching the source means yes.
  const next = new Map<string, string[]>();
  for (const e of edges) next.set(e.source, [...(next.get(e.source) ?? []), e.target]);
  const seen = new Set<string>();
  const stack = [target];
  while (stack.length) {
    const id = stack.pop() as string;
    if (id === source) return "That would make a loop; flows run left to right.";
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...(next.get(id) ?? []));
  }
  return null;
}

/** How many images reached each block in a run, from each image's recorded steps. */
export function countsByNode(items: FlowRunItem[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) {
    const seen = new Set<string>();
    for (const step of item.steps) {
      const node = typeof step.node === "string" ? step.node : null;
      if (!node || seen.has(node)) continue;
      seen.add(node);
      counts.set(node, (counts.get(node) ?? 0) + 1);
    }
  }
  return counts;
}

export function problemsByNode(problems: { node?: string | null; message: string }[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const p of problems) {
    if (!p.node) continue;
    map.set(p.node, [...(map.get(p.node) ?? []), p.message]);
  }
  return map;
}

export function sameDocument(a: FlowDocument, b: FlowDocument): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
