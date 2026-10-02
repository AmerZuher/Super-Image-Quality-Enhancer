import { clsx } from "clsx";
import { AlertTriangle, ChevronsLeftRight, Maximize, Minus, Plus } from "lucide-react";
import type OpenSeadragon from "openseadragon";
import { type CSSProperties, type PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { Spinner } from "@/components/ui/Spinner";
import type { Asset } from "@/lib/api/client";

export type CompareMode = "split" | "side" | "before" | "after";

type OSDModule = typeof OpenSeadragon;

/** Set once the library has loaded (it is split out of the main bundle). */
let OSD: OSDModule | null = null;

function makeViewer(
  lib: OSDModule,
  element: HTMLElement,
  tileSources: OpenSeadragon.TileSourceOptions[] | string,
) {
  return lib({
    element,
    tileSources: tileSources as never,
    // Clipping the "before" layer needs the canvas drawer.
    drawer: "canvas",
    showNavigationControl: false,
    showNavigator: false,
    maxZoomPixelRatio: 8,
    visibilityRatio: 0.5,
    gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: true },
    crossOriginPolicy: false,
    imageLoaderLimit: 6,
  } as OpenSeadragon.Options);
}

/**
 * Full-resolution before/after viewer over both images' deep-zoom tiles. Both layers are
 * scaled to the same width, so a ×4 result lines up pixel for pixel with its source.
 */
export function DeepCompare({
  before,
  after,
  mode,
}: {
  before: Asset;
  after: Asset | null;
  mode: CompareMode;
}) {
  const host = useRef<HTMLDivElement>(null);
  const leftHost = useRef<HTMLDivElement>(null);
  const rightHost = useRef<HTMLDivElement>(null);
  const viewers = useRef<OpenSeadragon.Viewer[]>([]);
  const [split, setSplit] = useState(0.5);
  const splitRef = useRef(0.5);
  const [zoom, setZoom] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const side = mode === "side" && after !== null;

  /** Clip the top ("before") layer to the left of the divider, in screen space. */
  const applyClip = useCallback(() => {
    const v = viewers.current[0];
    if (!v || side || !OSD) return;
    const top = after ? v.world.getItemAt(1) : null;
    if (!top) return;
    const size = top.getContentSize();
    if (mode === "split") {
      const width = v.container.clientWidth;
      const point = v.viewport.pointFromPixel(new OSD.Point(width * splitRef.current, 0), true);
      const x = Math.max(0, Math.min(size.x, top.viewportToImageCoordinates(point).x));
      top.setClip(new OSD.Rect(0, 0, x, size.y));
      top.setOpacity(1);
    } else {
      top.setClip(null as never);
      top.setOpacity(mode === "before" ? 1 : 0);
    }
  }, [after, mode, side]);

  // Viewers are rebuilt only when the images or the layout change; mode changes reuse them.
  // biome-ignore lint/correctness/useExhaustiveDependencies: applyClip is wired through viewer handlers
  useEffect(() => {
    let disposed = false;
    setError(null);
    setZoom(null);
    void import("openseadragon")
      .then(({ default: lib }) => {
        if (disposed) return;
        OSD = lib;
        const report = (v: OpenSeadragon.Viewer, item: number) => () => {
          const image = v.world.getItemAt(item);
          if (image) setZoom(image.viewportToImageZoom(v.viewport.getZoom(true)) * window.devicePixelRatio);
        };
        const fail = () => setError("The zoom tiles couldn't be loaded.");
        if (side && leftHost.current && rightHost.current && after?.dzi_url && before.dzi_url) {
          const left = makeViewer(lib, leftHost.current, before.dzi_url);
          const right = makeViewer(lib, rightHost.current, after.dzi_url);
          let syncing = false;
          const mirror = (from: OpenSeadragon.Viewer, to: OpenSeadragon.Viewer) => () => {
            if (syncing) return;
            syncing = true;
            to.viewport.zoomTo(from.viewport.getZoom(), undefined, true);
            to.viewport.panTo(from.viewport.getCenter(), true);
            syncing = false;
          };
          left.addHandler("viewport-change", mirror(left, right));
          right.addHandler("viewport-change", mirror(right, left));
          right.addHandler("zoom", report(right, 0));
          right.addHandler("open", report(right, 0));
          left.addHandler("open-failed", fail);
          right.addHandler("open-failed", fail);
          viewers.current = [left, right];
        } else if (host.current && before.dzi_url) {
          const layers = after?.dzi_url
            ? [
                { tileSource: after.dzi_url, x: 0, y: 0, width: 1 },
                { tileSource: before.dzi_url, x: 0, y: 0, width: 1 },
              ]
            : before.dzi_url;
          const v = makeViewer(lib, host.current, layers as never);
          v.addHandler("zoom", report(v, 0));
          v.addHandler("open", () => {
            report(v, 0)();
            applyClip();
          });
          v.addHandler("update-viewport", applyClip);
          v.addHandler("open-failed", fail);
          viewers.current = [v];
        }
      })
      .catch(() => setError("The viewer couldn't start."));
    return () => {
      disposed = true;
      for (const v of viewers.current) v.destroy();
      viewers.current = [];
    };
  }, [before.dzi_url, after?.dzi_url, side]);

  useEffect(() => {
    splitRef.current = split;
    applyClip();
    viewers.current[0]?.forceRedraw();
  }, [split, applyClip]);

  const dragging = useRef(false);
  const dragFrom = (event: PointerEvent<HTMLDivElement>) => {
    const box = host.current?.getBoundingClientRect();
    if (box) setSplit(Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)));
  };

  const zoomBy = (factor: number) => {
    for (const v of viewers.current.slice(0, 1)) v.viewport.zoomBy(factor);
  };
  const home = () => {
    for (const v of viewers.current) v.viewport.goHome();
  };
  const actual = () => {
    const v = viewers.current.at(-1);
    const image = v?.world.getItemAt(0);
    if (v && image) v.viewport.zoomTo(image.imageToViewportZoom(1 / window.devicePixelRatio));
  };

  const tool =
    "grid size-8 place-items-center rounded-md bg-[var(--overlay)] text-fg backdrop-blur-sm hover:bg-panel [&_svg]:size-4";
  const checker = after?.has_alpha ? "checker" : "bg-stage";
  return (
    <div className="relative min-h-0 min-w-0">
      {side ? (
        <div className="grid size-full grid-cols-2 gap-0.5 bg-line">
          <div ref={leftHost} className={clsx("relative min-h-0", "bg-stage")} data-testid="compare-before" />
          <div ref={rightHost} className={clsx("relative min-h-0", checker)} data-testid="compare-after" />
        </div>
      ) : (
        <div ref={host} className={clsx("absolute inset-0", checker)} data-testid="compare" />
      )}

      {after && (mode === "split" || side) && (
        <>
          <span className="pointer-events-none absolute top-2.5 left-2.5 rounded-md bg-[var(--overlay)] px-2 py-0.5 font-mono text-[10.5px] tracking-wider text-fg uppercase">
            Before
          </span>
          <span
            className={clsx(
              "pointer-events-none absolute top-2.5 rounded-md bg-[var(--overlay)] px-2 py-0.5 font-mono text-[10.5px] tracking-wider text-gold uppercase",
              side ? "left-[calc(50%+10px)]" : "right-2.5",
            )}
          >
            After
          </span>
        </>
      )}
      {after && mode === "split" && (
        <div
          aria-hidden="true"
          className="absolute top-0 bottom-0 w-6 -translate-x-1/2 cursor-ew-resize touch-none"
          style={{ left: `${split * 100}%` }}
          onPointerDown={(e) => {
            dragging.current = true;
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => dragging.current && dragFrom(e)}
          onPointerUp={() => {
            dragging.current = false;
          }}
        >
          <div className="absolute top-0 bottom-0 left-1/2 w-0.5 -translate-x-1/2 bg-gold" />
          <span className="absolute top-1/2 left-1/2 grid size-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border-2 border-gold bg-bg text-gold">
            <ChevronsLeftRight className="size-4" />
          </span>
        </div>
      )}

      <div className="absolute right-2.5 bottom-2.5 flex items-center gap-1">
        <span className="mr-1 rounded-md bg-[var(--overlay)] px-2 py-1 font-mono text-[11px] text-fg tabular-nums">
          {zoom ? `${Math.round(zoom * 100)}%` : "…"}
        </span>
        <button type="button" className={tool} onClick={() => zoomBy(1 / 1.5)} aria-label="Zoom out">
          <Minus />
        </button>
        <button type="button" className={tool} onClick={() => zoomBy(1.5)} aria-label="Zoom in">
          <Plus />
        </button>
        <button
          type="button"
          className="h-8 rounded-md bg-[var(--overlay)] px-2 text-[12px] text-fg backdrop-blur-sm hover:bg-panel"
          onClick={actual}
          title="Show result pixels at 100%"
        >
          1:1
        </button>
        <button type="button" className={tool} onClick={home} aria-label="Fit to the view">
          <Maximize />
        </button>
      </div>
      {after && mode === "split" && (
        <label className="absolute bottom-2.5 left-2.5 flex items-center gap-2 rounded-md bg-[var(--overlay)] px-2 py-1 text-[11px] text-fg backdrop-blur-sm">
          Divider
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round(split * 100)}
            onChange={(e) => setSplit(Number(e.target.value) / 100)}
            className="range w-28"
            style={{ "--from": "0%", "--to": `${split * 100}%` } as CSSProperties}
          />
        </label>
      )}
      {!zoom && !error && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <Spinner label="Loading tiles" className="size-6 text-cyan" />
        </div>
      )}
      {error && (
        <p className="absolute inset-0 flex items-center justify-center gap-2 text-[13px] text-err">
          <AlertTriangle className="size-4" aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
}
