import { type PointerEvent, useEffect, useMemo, useRef, useState } from "react";

export interface Point {
  x: number;
  y: number;
}

const HEIGHT = 180;
const PAD = { top: 12, right: 64, bottom: 24, left: 44 };

/** Round, readable ticks covering [min, max]. */
export function ticks(min: number, max: number, count = 4): number[] {
  if (!(max > min)) return [min];
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step)
    out.push(Number(v.toPrecision(10)));
  return out;
}

/** Ticks for a log scale: 1, 2 and 5 times powers of ten (just the powers if that is too many). */
export function logTicks(min: number, max: number): number[] {
  if (!(min > 0) || !(max > min)) return ticks(min, max);
  const out: number[] = [];
  for (let k = Math.floor(Math.log10(min)); k <= Math.ceil(Math.log10(max)); k++) {
    for (const m of [1, 2, 5]) {
      const v = Number((m * 10 ** k).toPrecision(6));
      if (v >= min && v <= max) out.push(v);
    }
  }
  const powers = out.filter((v) => Number.isInteger(Math.log10(v)));
  if (out.length > 6 && powers.length >= 2) return powers;
  return out.length >= 2 ? out : ticks(min, max);
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(480);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(
      ([entry]) => entry && setWidth(Math.max(240, Math.round(entry.contentRect.width))),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/**
 * One series over training steps, with an optional labelled reference line (bicubic). A crosshair
 * and tooltip follow the pointer; the caller provides a table view for the same numbers.
 */
export function LineChart({
  title,
  points,
  format,
  xMax,
  markers = false,
  reference,
  emptyText,
  log = false,
}: {
  title: string;
  points: Point[];
  format: (y: number) => string;
  xMax: number;
  markers?: boolean;
  reference?: { y: number; label: string };
  emptyText: string;
  /** Logarithmic y axis, for values that fall by orders of magnitude (loss). */
  log?: boolean;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;

  const t = (v: number) => (log ? Math.log10(Math.max(v, 1e-12)) : v);
  const { yMin, yMax } = useMemo(() => {
    const tf = (v: number) => (log ? Math.log10(Math.max(v, 1e-12)) : v);
    const ys = points.map((p) => tf(p.y)).concat(reference ? [tf(reference.y)] : []);
    if (ys.length === 0) return { yMin: 0, yMax: 1 };
    let lo = Math.min(...ys);
    let hi = Math.max(...ys);
    if (hi - lo < 1e-9) {
      lo -= Math.abs(lo) * 0.05 || 1;
      hi += Math.abs(hi) * 0.05 || 1;
    }
    const pad = (hi - lo) * 0.08;
    return { yMin: lo - pad, yMax: hi + pad };
  }, [points, reference, log]);
  const yTicks = log ? logTicks(10 ** yMin, 10 ** yMax) : ticks(yMin, yMax);

  const x = (v: number) => PAD.left + (v / Math.max(1, xMax)) * plotW;
  const y = (v: number) => PAD.top + (1 - (t(v) - yMin) / (yMax - yMin)) * plotH;
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(p.x).toFixed(1)},${y(p.y).toFixed(1)}`).join("");
  const last = points[points.length - 1] ?? { x: 0, y: 0 };
  const shown = hover !== null ? points[hover] : undefined;

  const onMove = (event: PointerEvent<SVGSVGElement>) => {
    if (points.length === 0) return;
    const box = event.currentTarget.getBoundingClientRect();
    const step = ((event.clientX - box.left - PAD.left) / plotW) * xMax;
    let best = 0;
    for (let i = 1; i < points.length; i++) {
      if (Math.abs((points[i] as Point).x - step) < Math.abs((points[best] as Point).x - step)) best = i;
    }
    setHover(best);
  };

  return (
    <figure className="grid min-w-0 gap-1.5">
      <figcaption className="text-[12.5px] font-semibold text-fg">{title}</figcaption>
      <div ref={ref} className="relative min-w-0">
        {points.length === 0 ? (
          <div
            className="grid place-items-center rounded-lg border border-dashed border-line text-[12px] text-muted"
            style={{ height: HEIGHT }}
          >
            {emptyText}
          </div>
        ) : (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={`${title}: ${points.length} points, latest ${format(last.y)} at step ${last.x.toLocaleString()}`}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
            className="block touch-none"
          >
            {yTicks.map((tick) => (
              <g key={tick}>
                <line
                  x1={PAD.left}
                  x2={PAD.left + plotW}
                  y1={y(tick)}
                  y2={y(tick)}
                  stroke="var(--line)"
                  strokeWidth={1}
                />
                <text
                  x={PAD.left - 6}
                  y={y(tick)}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={10.5}
                  fill="var(--muted)"
                  className="tabular-nums"
                >
                  {format(tick)}
                </text>
              </g>
            ))}
            {ticks(0, xMax, 4).map((t) => (
              <text
                key={t}
                x={x(t)}
                y={HEIGHT - 6}
                textAnchor="middle"
                fontSize={10.5}
                fill="var(--muted)"
                className="tabular-nums"
              >
                {t >= 1000 ? `${t / 1000}k` : t}
              </text>
            ))}
            {reference && (
              <g>
                <line
                  x1={PAD.left}
                  x2={PAD.left + plotW}
                  y1={y(reference.y)}
                  y2={y(reference.y)}
                  stroke="var(--muted)"
                  strokeWidth={1}
                />
                <text x={PAD.left + 4} y={y(reference.y) - 5} fontSize={10.5} fill="var(--fg-2)">
                  {reference.label}
                </text>
              </g>
            )}
            <path
              d={path}
              fill="none"
              stroke="var(--gold)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {markers &&
              points.map((p) => (
                <circle
                  key={p.x}
                  cx={x(p.x)}
                  cy={y(p.y)}
                  r={4}
                  fill="var(--gold)"
                  stroke="var(--panel)"
                  strokeWidth={2}
                />
              ))}
            {!markers && (
              <circle
                cx={x(last.x)}
                cy={y(last.y)}
                r={4}
                fill="var(--gold)"
                stroke="var(--panel)"
                strokeWidth={2}
              />
            )}
            <text
              x={x(last.x) + 8}
              y={y(last.y)}
              dy="0.32em"
              fontSize={11}
              fill="var(--fg)"
              className="tabular-nums"
            >
              {format(last.y)}
            </text>
            {shown && (
              <g pointerEvents="none">
                <line
                  x1={x(shown.x)}
                  x2={x(shown.x)}
                  y1={PAD.top}
                  y2={PAD.top + plotH}
                  stroke="var(--line-2)"
                  strokeWidth={1}
                />
                <circle
                  cx={x(shown.x)}
                  cy={y(shown.y)}
                  r={5}
                  fill="var(--gold)"
                  stroke="var(--panel)"
                  strokeWidth={2}
                />
              </g>
            )}
          </svg>
        )}
        {shown && (
          <div
            className="pointer-events-none absolute top-1 rounded-md border border-line bg-panel px-2 py-1 text-[11.5px] shadow-float"
            style={{ left: Math.min(Math.max(0, x(shown.x) - 60), width - 130) }}
            role="status"
          >
            <div className="text-muted">Step {shown.x.toLocaleString()}</div>
            <div className="font-semibold text-fg tabular-nums">{format(shown.y)}</div>
          </div>
        )}
      </div>
    </figure>
  );
}
