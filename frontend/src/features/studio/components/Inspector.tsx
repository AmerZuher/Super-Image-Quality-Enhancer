import { AlertTriangle, Maximize, Minus, Plus, ScanSearch, X } from "lucide-react";
import type OpenSeadragon from "openseadragon";
import { useEffect, useRef, useState } from "react";
import { Spinner } from "@/components/ui/Spinner";
import type { Asset } from "@/lib/api/client";
import { formatDimensions } from "../format";

/**
 * Full-resolution inspector over the deep-zoom pyramid built at import. It shows the
 * original pixels, so you can judge detail and noise before deciding on edits or AI.
 */
export function Inspector({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<OpenSeadragon.Viewer | null>(null);
  const [zoom, setZoom] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    const element = host.current;
    if (!element || !asset.dzi_url) return;
    void import("openseadragon")
      .then(({ default: OSD }) => {
        if (disposed) return;
        const v = OSD({
          element,
          tileSources: asset.dzi_url ?? undefined,
          showNavigationControl: false,
          showNavigator: true,
          navigatorPosition: "BOTTOM_RIGHT",
          maxZoomPixelRatio: 8,
          visibilityRatio: 0.5,
          gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: true },
          crossOriginPolicy: false,
        });
        const report = () => {
          const viewport = v.viewport;
          // Zoom relative to image pixels: 1 means one image pixel per screen pixel.
          setZoom(viewport.viewportToImageZoom(viewport.getZoom(true)) * window.devicePixelRatio);
        };
        v.addHandler("zoom", report);
        v.addHandler("open", report);
        v.addHandler("open-failed", () => setError("The full-resolution tiles couldn't be loaded."));
        viewer.current = v;
      })
      .catch(() => setError("The inspector couldn't start."));
    return () => {
      disposed = true;
      viewer.current?.destroy();
      viewer.current = null;
    };
  }, [asset.dzi_url]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const zoomBy = (factor: number) => viewer.current?.viewport.zoomBy(factor);
  const actualPixels = () => {
    const v = viewer.current;
    if (!v) return;
    v.viewport.zoomTo(v.viewport.imageToViewportZoom(1 / window.devicePixelRatio));
  };
  const tool =
    "grid size-8 place-items-center rounded-md text-fg-2 transition hover:bg-panel-2 hover:text-fg [&_svg]:size-4";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Inspect ${asset.original_name}`}
      className="fixed inset-0 z-50 grid grid-rows-[auto_minmax(0,1fr)] bg-bg"
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-2">
        <ScanSearch className="size-4 text-cyan" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[13px] font-semibold text-fg">{asset.original_name}</h2>
          <p className="truncate text-[11.5px] text-muted">
            Original pixels, {formatDimensions(asset.width, asset.height)}. Edits appear in exports.
          </p>
        </div>
        <span className="w-14 text-right font-mono text-[11.5px] text-fg-2 tabular-nums" aria-live="polite">
          {zoom ? `${Math.round(zoom * 100)}%` : ""}
        </span>
        <button type="button" className={tool} onClick={() => zoomBy(1 / 1.5)} aria-label="Zoom out">
          <Minus />
        </button>
        <button type="button" className={tool} onClick={() => zoomBy(1.5)} aria-label="Zoom in">
          <Plus />
        </button>
        <button
          type="button"
          className="h-8 rounded-md px-2 text-[12px] text-fg-2 hover:bg-panel-2 hover:text-fg"
          onClick={actualPixels}
        >
          1:1
        </button>
        <button
          type="button"
          className={tool}
          onClick={() => viewer.current?.viewport.goHome()}
          aria-label="Fit to screen"
        >
          <Maximize />
        </button>
        <button type="button" className={tool} onClick={onClose} aria-label="Close the inspector (Esc)">
          <X />
        </button>
      </header>
      <div className="relative min-h-0 bg-stage">
        <div ref={host} className="absolute inset-0" data-testid="inspector" />
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
    </div>
  );
}
