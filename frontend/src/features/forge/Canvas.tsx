import "@xyflow/react/dist/base.css";
import {
  applyNodeChanges,
  Background,
  BackgroundVariant,
  type Connection,
  Controls,
  type Edge,
  type EdgeChange,
  type NodeChange,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import { AlertTriangle } from "lucide-react";
import { type DragEvent, useCallback, useEffect, useMemo, useState } from "react";
import type { ForgeAnalysis, ForgeBlockType, ForgeGraph } from "@/lib/api/client";
import { Block } from "./Block";
import { type BlockNode, connectionProblem, DRAG_TYPE, edgeId, fromCanvas, toCanvas } from "./graph";

const NODE_TYPES = { block: Block };

interface CanvasProps {
  graph: ForgeGraph;
  specs: Map<string, ForgeBlockType>;
  analysis: ForgeAnalysis | undefined;
  selected: string | null;
  onChange: (graph: ForgeGraph) => void;
  onSelect: (id: string | null) => void;
  onDropBlock: (type: string, position: { x: number; y: number }) => void;
}

function CanvasInner({ graph, specs, analysis, selected, onChange, onSelect, onDropBlock }: CanvasProps) {
  const flow = useReactFlow();
  const [notice, setNotice] = useState<string | null>(null);
  const { nodes, edges } = useMemo(
    () => toCanvas(graph, specs, analysis, selected),
    [graph, specs, analysis, selected],
  );
  const styledEdges = useMemo<Edge[]>(
    () =>
      edges.map((e) => ({
        ...e,
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
      })),
    [edges],
  );

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 3500);
    return () => clearTimeout(timer);
  }, [notice]);

  const onNodesChange = useCallback(
    (changes: NodeChange<BlockNode>[]) => {
      let touched = false;
      for (const change of changes) {
        if (change.type === "select") {
          if (change.selected) onSelect(change.id);
          else if (change.id === selected) onSelect(null);
        }
        if (change.type === "position" || change.type === "remove") touched = true;
      }
      if (!touched) return;
      const removed = new Set(changes.filter((c) => c.type === "remove").map((c) => c.id));
      const next = applyNodeChanges(
        changes.filter((c) => c.type !== "select"),
        nodes,
      );
      onChange(fromCanvas(graph, next));
      if (selected && removed.has(selected)) onSelect(null);
    },
    [nodes, graph, onChange, onSelect, selected],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const removed = new Set(changes.filter((c) => c.type === "remove").map((c) => c.id));
      if (removed.size === 0) return;
      onChange({ ...graph, links: (graph.links ?? []).filter((l) => !removed.has(edgeId(l))) });
    },
    [graph, onChange],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      const problem = connectionProblem(connection, graph, specs);
      if (problem) {
        setNotice(problem);
        return;
      }
      onChange({
        ...graph,
        links: [...(graph.links ?? []), { source: connection.source, target: connection.target }],
      });
    },
    [graph, specs, onChange],
  );

  const onDrop = (event: DragEvent) => {
    const type = event.dataTransfer.getData(DRAG_TYPE);
    if (!type) return;
    event.preventDefault();
    const position = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    onDropBlock(type, { x: Math.round(position.x - 20), y: Math.round(position.y - 20) });
  };

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: a drop target only; the palette's buttons add blocks from the keyboard
    <div
      className="flow-canvas relative h-full min-h-0"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes(DRAG_TYPE)) {
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
        }
      }}
      onDrop={onDrop}
    >
      <ReactFlow<BlockNode>
        nodes={nodes}
        edges={styledEdges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onPaneClick={() => onSelect(null)}
        deleteKeyCode={["Delete", "Backspace"]}
        fitView
        fitViewOptions={{ padding: 0.1, maxZoom: 1 }}
        minZoom={0.2}
        maxZoom={1.75}
        proOptions={{ hideAttribution: true }}
        aria-label="Model canvas"
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} color="var(--line-2)" />
        <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>
      {notice && (
        <div
          role="status"
          className="pointer-events-none absolute top-3 left-1/2 flex max-w-[90%] -translate-x-1/2 items-center gap-1.5 rounded-lg border border-warn/45 bg-panel px-3 py-1.5 text-[12px] text-warn shadow-float"
        >
          <AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
          {notice}
        </div>
      )}
    </div>
  );
}

export function Canvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}
