import { Handle, type NodeProps, Position } from "@xyflow/react";
import { clsx } from "clsx";
import { AlertTriangle } from "lucide-react";
import { memo } from "react";
import { type BlockNode, NODE_WIDTH } from "./graph";

const HANDLE =
  "!size-3 !rounded-full !border-2 !border-line-2 !bg-bg transition hover:!border-cyan hover:!bg-cyan-soft";

/** A layer or block of the model on the Forge canvas; red marks problems. */
export const Block = memo(function Block({ data, selected }: NodeProps<BlockNode>) {
  const { block, spec, problems, summary } = data;
  const io = spec?.category === "io";
  const merge = spec?.category === "merge";
  const broken = problems.length > 0 || !spec;
  return (
    <div
      className={clsx(
        "rounded-[10px] border bg-panel-2 text-left shadow-[0_10px_24px_-14px_rgba(0,0,0,.7)]",
        broken ? "border-err" : "border-line-2",
        selected && !broken && "border-cyan ring-1 ring-cyan",
        selected && broken && "ring-1 ring-err",
      )}
      style={{ width: NODE_WIDTH }}
      data-testid={`forge-block-${block.id}`}
    >
      {(spec?.inputs ?? 1) > 0 && (
        <Handle
          type="target"
          position={Position.Left}
          id="in"
          className={clsx(HANDLE, merge && "!h-6 !rounded-md")}
          style={{ top: 19 }}
        />
      )}
      <div className="flex items-center gap-2 px-2.5 pt-2.5 pb-1">
        <span
          aria-hidden="true"
          className={clsx("size-2 shrink-0", io ? "rounded-full bg-fg-2" : "rounded-[2px] bg-cyan")}
        />
        <b className="min-w-0 flex-1 truncate text-[12px] font-semibold text-fg">
          {block.label || spec?.label || block.type}
        </b>
      </div>
      <p className="truncate px-2.5 pb-2 text-[11px] text-muted">{summary}</p>
      {(spec?.has_output ?? true) && (
        <Handle type="source" position={Position.Right} id="out" className={HANDLE} style={{ top: 19 }} />
      )}
      {broken && (
        <div className="flex items-start gap-1.5 rounded-b-[10px] border-t border-err/40 bg-err-soft px-2.5 py-1.5 text-[10.5px] text-err">
          <AlertTriangle className="mt-px size-3 shrink-0" aria-hidden="true" />
          <span className="line-clamp-3">
            {spec ? problems[0] : "This block type doesn't exist in this version."}
          </span>
        </div>
      )}
    </div>
  );
});
