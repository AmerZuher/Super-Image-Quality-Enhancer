import { AlertTriangle } from "lucide-react";
import { useEffect, useRef } from "react";
import { create } from "zustand";
import type { Histogram as HistogramData } from "../gl/renderer";

/** Latest histogram of the edited preview, published by the canvas. */
export const useHistogram = create<{ data: HistogramData | null; set: (d: HistogramData | null) => void }>(
  (set) => ({ data: null, set: (data) => set({ data }) }),
);

const CHANNELS = [
  ["r", "--hist-r"],
  ["g", "--hist-g"],
  ["b", "--hist-b"],
] as const;

function draw(canvas: HTMLCanvasElement, data: HistogramData): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  // Ignore the clipped end bins when scaling, so a clipped sky doesn't flatten everything else.
  let peak = 1;
  for (const [key] of CHANNELS) for (let i = 1; i < 255; i++) peak = Math.max(peak, data[key][i] ?? 0);
  const style = getComputedStyle(canvas);
  const bin = width / 256;
  ctx.globalCompositeOperation = style.colorScheme === "light" ? "multiply" : "screen";
  for (const [key, token] of CHANNELS) {
    ctx.fillStyle = style.getPropertyValue(token);
    ctx.beginPath();
    ctx.moveTo(0, height);
    for (let i = 0; i < 256; i++) {
      const v = Math.min(1, Math.sqrt((data[key][i] ?? 0) / peak));
      ctx.lineTo(i * bin, height - v * (height - 2));
      ctx.lineTo((i + 1) * bin, height - v * (height - 2));
    }
    ctx.lineTo(width, height);
    ctx.closePath();
    ctx.fill();
  }
  ctx.globalCompositeOperation = "source-over";
}

export function Histogram() {
  const ref = useRef<HTMLCanvasElement>(null);
  const data = useHistogram((s) => s.data);
  useEffect(() => {
    if (ref.current && data) draw(ref.current, data);
  }, [data]);
  const shadows = data?.clipped.shadows ?? 0;
  const highlights = data?.clipped.highlights ?? 0;
  return (
    <figure className="grid gap-1.5">
      <canvas
        ref={ref}
        width={512}
        height={140}
        className="h-[78px] w-full rounded-md border border-line bg-bg"
        role="img"
        aria-label="Histogram of the edited image"
      />
      <figcaption className="flex justify-between gap-2 text-[11px] text-muted">
        <Clip label="Shadows" fraction={shadows} />
        <Clip label="Highlights" fraction={highlights} />
      </figcaption>
    </figure>
  );
}

function Clip({ label, fraction }: { label: string; fraction: number }) {
  if (fraction < 0.005) return <span>{label} not clipped</span>;
  return (
    <span className="flex items-center gap-1 text-warn">
      <AlertTriangle className="size-3" aria-hidden="true" />
      {label} clipped {(fraction * 100).toFixed(fraction < 0.1 ? 1 : 0)}%
    </span>
  );
}
