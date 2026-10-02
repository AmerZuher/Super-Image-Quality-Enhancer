import { clsx } from "clsx";
import { Crop, Eye, EyeOff, FlipHorizontal2, History, RotateCwSquare, X } from "lucide-react";
import type { ReactNode } from "react";
import type { OpSpec } from "@/lib/api/client";
import { type Doc, outputSize, removeOp, setCrop, setEnabled } from "../doc";
import { aspectName, formatDimensions, summarizeOp } from "../format";
import { useEditor } from "../store";

function geometryRows(doc: Doc, [width, height]: [number, number]) {
  const g = doc.geometry;
  const rows: { key: string; label: string; detail: string; icon: ReactNode; clear?: (d: Doc) => Doc }[] = [];
  if (g.rotate)
    rows.push({ key: "rotate", label: "Rotate", detail: `${g.rotate}°`, icon: <RotateCwSquare /> });
  if (g.flip_h || g.flip_v) {
    rows.push({
      key: "flip",
      label: "Flip",
      detail: [g.flip_h && "horizontal", g.flip_v && "vertical"].filter(Boolean).join(", "),
      icon: <FlipHorizontal2 />,
    });
  }
  if (g.crop) {
    rows.push({
      key: "crop",
      label: "Crop",
      detail: (() => {
        const [w, h] = outputSize(width, height, g);
        const name = aspectName(w, h);
        return name ? `${name} · ${formatDimensions(w, h)}` : formatDimensions(w, h);
      })(),
      icon: <Crop />,
      clear: (d) => setCrop(d, null),
    });
  }
  return rows;
}

/** Everything applied to the image, in the order it's applied, with on/off and remove. */
export function EditStack({ specs, size }: { specs: OpSpec[]; size: [number, number] }) {
  const doc = useEditor((s) => s.doc);
  const update = useEditor((s) => s.update);
  const geometry = geometryRows(doc, size);
  const empty = geometry.length === 0 && doc.ops.length === 0;
  return (
    <section aria-labelledby="stack-heading" className="grid gap-2">
      <h2 id="stack-heading" className="eyebrow">
        Edit stack
      </h2>
      {empty ? (
        <p className="text-[12px] text-muted">
          No edits yet. Move a slider on the right to start; the original is never changed.
        </p>
      ) : (
        <ol className="grid gap-1" data-testid="edit-stack">
          {geometry.map((row) => (
            <li
              key={row.key}
              className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2 rounded-md border border-line bg-panel-2 py-1 pr-1 pl-2 text-[12px] [&>svg]:size-3.5 [&>svg]:text-cyan"
            >
              {row.icon}
              <span className="truncate text-fg">{row.label}</span>
              {row.clear ? (
                <button
                  type="button"
                  onClick={() => update(`Remove ${row.label.toLowerCase()}`, row.clear as (d: Doc) => Doc)}
                  className="grid size-6 place-items-center rounded text-muted hover:bg-raised hover:text-fg"
                  aria-label={`Remove ${row.label.toLowerCase()}`}
                  title="Remove"
                >
                  <X className="size-3.5" />
                </button>
              ) : (
                <span className="size-6" />
              )}
              <span className="col-start-2 col-end-4 truncate font-mono text-[10.5px] text-muted">
                {row.detail}
              </span>
            </li>
          ))}
          {doc.ops.map((e) => {
            const spec = specs.find((s) => s.id === e.id);
            if (!spec) return null;
            return (
              <li
                key={e.id}
                className={clsx(
                  "grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-x-2 rounded-md border border-line bg-panel-2 py-1 pr-1 pl-2 text-[12px]",
                  !e.enabled && "opacity-55",
                )}
              >
                <span className={clsx("size-1.5 rounded-full", e.enabled ? "bg-cyan" : "bg-line-2")} />
                <span className="truncate text-fg">{spec.label}</span>
                <button
                  type="button"
                  onClick={() =>
                    update(e.enabled ? `Hide ${spec.label}` : `Show ${spec.label}`, (d) =>
                      setEnabled(d, e.id, !e.enabled),
                    )
                  }
                  className="grid size-6 place-items-center rounded text-muted hover:bg-raised hover:text-fg"
                  aria-label={e.enabled ? `Turn off ${spec.label}` : `Turn on ${spec.label}`}
                  aria-pressed={!e.enabled}
                  title={e.enabled ? "Turn off" : "Turn on"}
                >
                  {e.enabled ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
                </button>
                <button
                  type="button"
                  onClick={() => update(`Remove ${spec.label}`, (d) => removeOp(d, e.id))}
                  className="grid size-6 place-items-center rounded text-muted hover:bg-raised hover:text-fg"
                  aria-label={`Remove ${spec.label}`}
                  title="Remove"
                >
                  <X className="size-3.5" />
                </button>
                <span className="col-start-2 col-end-5 truncate font-mono text-[10.5px] text-muted">
                  {summarizeOp(spec, e.params)}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

export function HistoryList() {
  const past = useEditor((s) => s.past);
  const future = useEditor((s) => s.future);
  const undo = useEditor((s) => s.undo);
  const redo = useEditor((s) => s.redo);
  const jump = (steps: number) => {
    for (let i = 0; i < Math.abs(steps); i++) (steps < 0 ? undo : redo)();
  };
  const rows = [
    { label: "Opened", offset: -past.length },
    ...past.map((step, i) => ({ label: step.label, offset: i + 1 - past.length })),
    ...future.map((step, i) => ({ label: step.label, offset: i + 1 })),
  ];
  return (
    <section aria-labelledby="history-heading" className="grid gap-2">
      <h2 id="history-heading" className="eyebrow flex items-center gap-1.5">
        <History className="size-3" aria-hidden="true" />
        History
      </h2>
      <ol className="grid max-h-[220px] gap-px overflow-y-auto text-[12px]">
        {rows.map((row, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: history steps have no stable id
          <li key={i}>
            <button
              type="button"
              onClick={() => jump(row.offset)}
              aria-current={row.offset === 0 ? "step" : undefined}
              className={clsx(
                "w-full truncate rounded px-2 py-1 text-left transition hover:bg-panel-2",
                row.offset === 0
                  ? "bg-cyan-soft text-fg"
                  : row.offset > 0
                    ? "text-muted line-through"
                    : "text-fg-2",
              )}
            >
              {row.label}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
