import { clsx } from "clsx";
import { Brush, Trash2, Undo2 } from "lucide-react";
import { type PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import type { Asset } from "@/lib/api/client";
import { BRUSHES, type Stroke, strokesFor, useAiLabStore } from "./store";

/** A colour token's current value (canvas can't read CSS variables itself). */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Paint over what to erase. The preview fits the stage; strokes are kept in image units. */
export function EraseCanvas({ asset }: { asset: Asset }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [rect, setRect] = useState({ x: 0, y: 0, w: 0, h: 0 });
  const [drawing, setDrawing] = useState<Stroke | null>(null);
  const strokes = useAiLabStore((s) => strokesFor(s, asset.id));
  const { radius, setRadius, addStroke, undo, clear } = useAiLabStore();

  // Where the image sits inside the stage (object-fit: contain).
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => {
      const { width, height } = el.getBoundingClientRect();
      const scale = Math.min(width / asset.width, height / asset.height);
      const w = asset.width * scale;
      const h = asset.height * scale;
      setRect({ x: (width - w) / 2, y: (height - h) / 2, w, h });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [asset.width, asset.height]);

  const draw = useCallback(() => {
    const c = canvas.current;
    if (!c || !rect.w) return;
    const ratio = window.devicePixelRatio || 1;
    c.width = Math.round(rect.w * ratio);
    c.height = Math.round(rect.h * ratio);
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, rect.w, rect.h);
    ctx.globalAlpha = 0.55;
    const gold = token("--gold");
    if (gold) ctx.strokeStyle = ctx.fillStyle = gold;
    ctx.lineCap = ctx.lineJoin = "round";
    for (const stroke of drawing ? [...strokes, drawing] : strokes) {
      const r = stroke.radius * rect.w;
      const [first, ...rest] = stroke.points;
      if (!first) continue;
      ctx.beginPath();
      ctx.arc(first[0] * rect.w, first[1] * rect.h, r, 0, Math.PI * 2);
      ctx.fill();
      if (rest.length) {
        ctx.lineWidth = r * 2;
        ctx.beginPath();
        ctx.moveTo(first[0] * rect.w, first[1] * rect.h);
        for (const [x, y] of rest) ctx.lineTo(x * rect.w, y * rect.h);
        ctx.stroke();
      }
    }
  }, [rect, strokes, drawing]);
  useEffect(draw, [draw]);

  const point = (e: PointerEvent<HTMLCanvasElement>): [number, number] => {
    const bounds = e.currentTarget.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (e.clientX - bounds.left) / bounds.width)),
      Math.min(1, Math.max(0, (e.clientY - bounds.top) / bounds.height)),
    ];
  };

  return (
    <div className="relative min-h-0 overflow-hidden bg-stage" data-testid="erase-canvas">
      <div ref={box} className="absolute inset-3 bottom-14">
        {rect.w > 0 && (
          <>
            <img
              src={asset.preview_url ?? asset.original_url}
              alt={asset.original_name}
              className="absolute select-none"
              style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
              draggable={false}
            />
            <canvas
              ref={canvas}
              className="absolute cursor-crosshair touch-none"
              style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
              aria-label="Paint over what to erase"
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
                setDrawing({ points: [point(e)], radius });
              }}
              onPointerMove={(e) => {
                if (!drawing) return;
                const p = point(e);
                const last = drawing.points[drawing.points.length - 1];
                // Keep strokes light: a new point every couple of screen pixels is plenty.
                if (last && Math.hypot((p[0] - last[0]) * rect.w, (p[1] - last[1]) * rect.h) < 2) return;
                setDrawing({ ...drawing, points: [...drawing.points, p] });
              }}
              onPointerUp={() => {
                if (drawing) addStroke(asset.id, drawing);
                setDrawing(null);
              }}
              onPointerCancel={() => setDrawing(null)}
            />
          </>
        )}
      </div>
      <div className="absolute inset-x-3 bottom-3 flex flex-wrap items-center justify-center gap-2 rounded-lg border border-line bg-panel/95 px-2 py-1.5 text-[12px] shadow-float">
        <Brush className="size-3.5 text-gold" aria-hidden="true" />
        <span className="text-fg-2 max-sm:sr-only">Paint over what to remove</span>
        <fieldset className="flex rounded-md border border-line p-0.5">
          <legend className="sr-only">Brush size</legend>
          {BRUSHES.map((b) => (
            <button
              key={b.label}
              type="button"
              aria-pressed={radius === b.radius}
              onClick={() => setRadius(b.radius)}
              className={clsx(
                "h-6 rounded px-2 text-[11.5px]",
                radius === b.radius ? "bg-gold-soft font-medium text-gold" : "text-fg-2 hover:text-fg",
              )}
            >
              {b.label}
            </button>
          ))}
        </fieldset>
        <Button size="sm" variant="ghost" icon={<Undo2 />} onClick={undo} disabled={!strokes.length}>
          Undo
        </Button>
        <Button size="sm" variant="ghost" icon={<Trash2 />} onClick={clear} disabled={!strokes.length}>
          Clear
        </Button>
      </div>
    </div>
  );
}
