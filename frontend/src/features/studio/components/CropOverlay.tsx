import { clsx } from "clsx";
import { type KeyboardEvent, type PointerEvent, useEffect, useRef, useState } from "react";
import type { CropRect } from "../doc";

type Handle = "move" | "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

const HANDLES: { id: Exclude<Handle, "move">; className: string; label: string }[] = [
  { id: "nw", className: "-top-1.5 -left-1.5 cursor-nwse-resize", label: "Top-left corner" },
  { id: "ne", className: "-top-1.5 -right-1.5 cursor-nesw-resize", label: "Top-right corner" },
  { id: "sw", className: "-bottom-1.5 -left-1.5 cursor-nesw-resize", label: "Bottom-left corner" },
  { id: "se", className: "-right-1.5 -bottom-1.5 cursor-nwse-resize", label: "Bottom-right corner" },
  { id: "n", className: "-top-1.5 left-1/2 -ml-1.5 cursor-ns-resize", label: "Top edge" },
  { id: "s", className: "-bottom-1.5 left-1/2 -ml-1.5 cursor-ns-resize", label: "Bottom edge" },
  { id: "w", className: "top-1/2 -left-1.5 -mt-1.5 cursor-ew-resize", label: "Left edge" },
  { id: "e", className: "top-1/2 -right-1.5 -mt-1.5 cursor-ew-resize", label: "Right edge" },
];

const MIN = 0.02;

function clampRect(r: CropRect): CropRect {
  const w = Math.min(1, Math.max(MIN, r.w));
  const h = Math.min(1, Math.max(MIN, r.h));
  return { x: Math.min(1 - w, Math.max(0, r.x)), y: Math.min(1 - h, Math.max(0, r.y)), w, h };
}

/**
 * Resize a rectangle by dragging one handle by (dx, dy), in normalised image coordinates.
 * `ratio` is the locked w/h ratio in normalised units, or null for free.
 */
export function dragRect(
  start: CropRect,
  handle: Handle,
  dx: number,
  dy: number,
  ratio: number | null,
): CropRect {
  if (handle === "move") return clampRect({ ...start, x: start.x + dx, y: start.y + dy });
  let left = start.x;
  let top = start.y;
  let right = start.x + start.w;
  let bottom = start.y + start.h;
  if (handle.includes("w")) left = Math.min(right - MIN, Math.max(0, left + dx));
  if (handle.includes("e")) right = Math.max(left + MIN, Math.min(1, right + dx));
  if (handle.includes("n")) top = Math.min(bottom - MIN, Math.max(0, top + dy));
  if (handle.includes("s")) bottom = Math.max(top + MIN, Math.min(1, bottom + dy));
  let w = right - left;
  let h = bottom - top;
  if (ratio) {
    const horizontal = handle === "e" || handle === "w";
    const vertical = handle === "n" || handle === "s";
    if (horizontal) h = w / ratio;
    else if (vertical) w = h * ratio;
    else if (w / h > ratio) w = h * ratio;
    else h = w / ratio;
    // Shrink to fit inside the image, keeping the ratio.
    const maxW = handle.includes("w") ? right : vertical ? 1 : 1 - left;
    const maxH = handle.includes("n") ? bottom : horizontal ? 1 : 1 - top;
    const fit = Math.min(1, maxW / w, maxH / h);
    w *= fit;
    h *= fit;
    if (handle.includes("w")) left = right - w;
    if (handle.includes("n")) top = bottom - h;
    if (vertical) left = Math.min(1 - w, Math.max(0, start.x + (start.w - w) / 2));
    if (horizontal) top = Math.min(1 - h, Math.max(0, start.y + (start.h - h) / 2));
  }
  return clampRect({ x: left, y: top, w, h });
}

/** The largest rectangle with this normalised ratio, centred on `around`. */
export function fitRatio(around: CropRect, ratio: number): CropRect {
  const cx = around.x + around.w / 2;
  const cy = around.y + around.h / 2;
  let w = around.w;
  let h = w / ratio;
  if (h > around.h) {
    h = around.h;
    w = h * ratio;
  }
  return clampRect({ x: cx - w / 2, y: cy - h / 2, w, h });
}

export function CropOverlay({
  rect,
  ratio,
  onCommit,
}: {
  rect: CropRect;
  /** Locked w/h ratio in normalised units, or null. */
  ratio: number | null;
  onCommit: (rect: CropRect) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<CropRect | null>(null);
  const drag = useRef<{ handle: Handle; x: number; y: number; start: CropRect } | null>(null);
  const shown = draft ?? rect;

  // biome-ignore lint/correctness/useExhaustiveDependencies: drop the draft once the committed crop arrives
  useEffect(() => setDraft(null), [rect]);

  const begin = (handle: Handle) => (event: PointerEvent) => {
    event.preventDefault();
    event.stopPropagation();
    (event.target as Element).setPointerCapture(event.pointerId);
    drag.current = { handle, x: event.clientX, y: event.clientY, start: shown };
  };
  const move = (event: PointerEvent) => {
    const d = drag.current;
    const box = ref.current?.getBoundingClientRect();
    if (!d || !box) return;
    setDraft(
      dragRect(
        d.start,
        d.handle,
        (event.clientX - d.x) / box.width,
        (event.clientY - d.y) / box.height,
        ratio,
      ),
    );
  };
  const end = () => {
    if (drag.current && draft) onCommit(draft);
    drag.current = null;
  };
  const onKey = (event: KeyboardEvent) => {
    const step = event.shiftKey ? 0.05 : 0.01;
    const delta: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, -step],
      ArrowDown: [0, step],
    };
    const d = delta[event.key];
    if (!d) return;
    event.preventDefault();
    onCommit(dragRect(shown, "move", d[0], d[1], ratio));
  };

  const pct = (v: number) => `${v * 100}%`;
  return (
    <div ref={ref} className="absolute inset-0 overflow-hidden" onPointerMove={move} onPointerUp={end}>
      <button
        type="button"
        aria-label="Crop area. Drag to move, use the arrow keys to nudge."
        onKeyDown={onKey}
        onPointerDown={begin("move")}
        className="absolute cursor-move touch-none border border-cyan bg-transparent p-0 outline-none focus-visible:border-2"
        style={{
          left: pct(shown.x),
          top: pct(shown.y),
          width: pct(shown.w),
          height: pct(shown.h),
          boxShadow: "0 0 0 9999px var(--overlay)",
        }}
      >
        <div className="pointer-events-none absolute inset-0 grid grid-cols-3 grid-rows-3">
          {Array.from({ length: 9 }, (_, i) => (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: static rule-of-thirds grid
              key={i}
              className={clsx("border-fg/25", i % 3 !== 2 && "border-r", i < 6 && "border-b")}
            />
          ))}
        </div>
        {HANDLES.map((h) => (
          <span
            key={h.id}
            aria-hidden="true"
            title={h.label}
            onPointerDown={begin(h.id)}
            className={clsx("absolute size-3 touch-none rounded-[3px] border border-cyan bg-fg", h.className)}
          />
        ))}
      </button>
    </div>
  );
}
