import { Handle, type NodeProps, Position } from "@xyflow/react";
import { clsx } from "clsx";
import { AlertTriangle, Images } from "lucide-react";
import { memo } from "react";
import type { BlockNode } from "./graph";
import { NODE_WIDTH } from "./graph";

const PORT_LABELS: Record<string, string> = { yes: "Yes", no: "No" };

const HANDLE =
  "!size-3 !rounded-full !border-2 !border-line-2 !bg-bg transition hover:!border-cyan hover:!bg-cyan-soft";

/** A block on the flow canvas. Gold marks blocks that run an AI model; red marks problems. */
export const Block = memo(function Block({ data, selected }: NodeProps<BlockNode>) {
  const { node, spec, problems, count, summary } = data;
  const ai = spec?.ai ?? false;
  const io = spec?.category === "input" || spec?.category === "output";
  const outputs = spec?.outputs ?? ["out"];
  const named = outputs.length > 1;
  const broken = problems.length > 0 || !spec;
  return (
    <div
      className={clsx(
        "rounded-[10px] border bg-panel-2 text-left shadow-[0_10px_24px_-14px_rgba(0,0,0,.7)]",
        broken ? "border-err" : ai ? "border-gold/60" : "border-line-2",
        selected && !broken && (ai ? "ring-1 ring-gold" : "border-cyan ring-1 ring-cyan"),
        selected && broken && "ring-1 ring-err",
      )}
      style={{ width: NODE_WIDTH }}
      data-testid={`block-${node.id}`}
    >
      {(spec?.inputs ?? 1) > 0 && (
        <Handle type="target" position={Position.Left} id="in" className={HANDLE} style={{ top: 19 }} />
      )}
      <div className="flex items-center gap-2 px-2.5 pt-2.5 pb-1">
        <span
          aria-hidden="true"
          className={clsx(
            "size-2 shrink-0",
            io ? "rounded-full bg-fg-2" : "rounded-[2px]",
            !io && (ai ? "bg-gold shadow-[0_0_8px_var(--gold)]" : "bg-cyan"),
          )}
        />
        <b className="min-w-0 flex-1 truncate text-[12px] font-semibold text-fg">
          {node.label || spec?.label || node.type}
        </b>
        {ai && <span className="font-mono text-[9.5px] text-gold">AI</span>}
      </div>
      <div className="px-2.5 pb-2">
        <p className="line-clamp-2 text-[11px] leading-snug text-muted">{summary}</p>
      </div>
      {named && (
        <div className="grid gap-1 px-2.5 pb-2">
          {outputs.map((port) => (
            <div
              key={port}
              className="relative flex h-[18px] items-center justify-end text-[10.5px] text-fg-2"
            >
              {PORT_LABELS[port] ?? port}
              <Handle
                type="source"
                position={Position.Right}
                id={port}
                className={clsx(HANDLE, "!-right-[17px]")}
                style={{ top: 9 }}
              />
            </div>
          ))}
        </div>
      )}
      {!named && outputs.length === 1 && (
        <Handle
          type="source"
          position={Position.Right}
          id={outputs[0]}
          className={HANDLE}
          style={{ top: 19 }}
        />
      )}
      {broken ? (
        <div className="flex items-start gap-1.5 rounded-b-[10px] border-t border-err/40 bg-err-soft px-2.5 py-1.5 text-[10.5px] text-err">
          <AlertTriangle className="mt-px size-3 shrink-0" aria-hidden="true" />
          <span>{spec ? problems[0] : "This block type doesn't exist in this version."}</span>
        </div>
      ) : count !== undefined ? (
        <div className="flex items-center justify-between gap-2 border-t border-line px-2.5 py-1 font-mono text-[10.5px]">
          <span className="flex items-center gap-1 text-muted">
            <Images className="size-3" aria-hidden="true" />
            last run
          </span>
          <b className={clsx("font-medium", ai ? "text-gold" : "text-cyan")}>{count.toLocaleString()}</b>
        </div>
      ) : null}
    </div>
  );
});
