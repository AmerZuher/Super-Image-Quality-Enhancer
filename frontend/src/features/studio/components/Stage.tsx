import { clsx } from "clsx";
import { AlertTriangle, ChevronsLeftRight } from "lucide-react";
import { type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { Spinner } from "@/components/ui/Spinner";
import type { Asset } from "@/lib/api/client";
import { activeOps, cropOrFull, type Geometry, rotatedSize, setCrop } from "../doc";
import { PreviewRenderer, WebGLUnavailableError } from "../gl/renderer";
import { useEditor } from "../store";
import { CropOverlay } from "./CropOverlay";
import { useHistogram } from "./Histogram";

const PAD = 24;

function useBoxSize(ref: RefObject<HTMLElement | null>): [number, number] {
  const [size, setSize] = useState<[number, number]>([0, 0]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setSize([entry.contentRect.width, entry.contentRect.height]);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

async function loadBitmap(url: string, signal: AbortSignal): Promise<ImageBitmap> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`The preview couldn't be loaded (${response.status}).`);
  // Raw sRGB values, unpremultiplied: the shader does all colour work itself.
  return createImageBitmap(await response.blob(), { premultiplyAlpha: "none", colorSpaceConversion: "none" });
}

function Tag({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        "pointer-events-none absolute top-2.5 rounded-md bg-[var(--overlay)] px-2 py-0.5 font-mono text-[10.5px] tracking-wider text-fg uppercase backdrop-blur-sm",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** The live WebGL preview with compare modes and the crop tool. */
export function Stage({ asset }: { asset: Asset }) {
  const doc = useEditor((s) => s.doc);
  const compare = useEditor((s) => s.compare);
  const split = useEditor((s) => s.split);
  const setSplit = useEditor((s) => s.setSplit);
  const holdBefore = useEditor((s) => s.holdBefore);
  const panel = useEditor((s) => s.panel);
  const cropAspect = useEditor((s) => s.cropAspect);
  const update = useEditor((s) => s.update);
  const editorAsset = useEditor((s) => s.assetId);
  const setHistogram = useHistogram((s) => s.set);

  const boxRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderer = useRef<PreviewRenderer | null>(null);
  const [failure, setFailure] = useState<{ message: string; fix?: string } | null>(null);
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [canvasSize, setCanvasSize] = useState<[number, number]>([0, 0]);
  const [epoch, setEpoch] = useState(0);
  const [boxW, boxH] = useBoxSize(boxRef);

  // One renderer per canvas; survives image switches and recovers from a lost GPU context.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    try {
      renderer.current = new PreviewRenderer(canvas);
    } catch (error) {
      setFailure(
        error instanceof WebGLUnavailableError
          ? {
              message: "The live preview needs WebGL 2, which this browser has turned off.",
              fix: "Turn on hardware acceleration in the browser settings. Exports still include every edit.",
            }
          : { message: error instanceof Error ? error.message : String(error) },
      );
      return;
    }
    const lost = (event: Event) => {
      event.preventDefault();
      if (renderer.current) renderer.current.lost = true;
    };
    const restored = () => {
      renderer.current?.restore();
      setEpoch((n) => n + 1);
    };
    canvas.addEventListener("webglcontextlost", lost);
    canvas.addEventListener("webglcontextrestored", restored);
    return () => {
      canvas.removeEventListener("webglcontextlost", lost);
      canvas.removeEventListener("webglcontextrestored", restored);
      renderer.current?.dispose();
      renderer.current = null;
    };
  }, []);

  useEffect(() => {
    const r = renderer.current;
    if (!r || !asset.preview_url) return;
    const controller = new AbortController();
    setLoadedId(null);
    loadBitmap(asset.preview_url, controller.signal)
      .then((bitmap) => {
        if (controller.signal.aborted) {
          bitmap.close();
          return;
        }
        r.setImage(bitmap);
        setLoadedId(asset.id);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setFailure({
            message: error instanceof Error ? error.message : String(error),
            fix: "Reload the page.",
          });
        }
      });
    return () => controller.abort();
  }, [asset.id, asset.preview_url]);

  const cropping = panel === "crop";
  const geometry: Geometry = useMemo(
    () => (cropping ? { ...doc.geometry, crop: null } : doc.geometry),
    [cropping, doc.geometry],
  );
  const ops = useMemo(() => activeOps(doc), [doc]);
  const previewScale = (asset.preview_width ?? asset.width) / asset.width;
  const mode = holdBefore ? "before" : cropping ? "after" : compare;
  // Wait for both the pixels and this image's edit document before drawing.
  const ready = loadedId === asset.id && editorAsset === asset.id;

  useEffect(() => {
    const r = renderer.current;
    if (!ready || !r || epoch < 0) return;
    const frame = requestAnimationFrame(() => {
      setCanvasSize(r.render({ geometry, ops, previewScale, mode, split }));
    });
    return () => cancelAnimationFrame(frame);
  }, [ready, geometry, ops, previewScale, mode, split, epoch]);

  useEffect(() => {
    const r = renderer.current;
    if (!ready || !r) return;
    const timer = setTimeout(
      () => setHistogram(r.histogram({ geometry: doc.geometry, ops, previewScale })),
      120,
    );
    return () => clearTimeout(timer);
  }, [ready, doc.geometry, ops, previewScale, setHistogram]);

  useEffect(() => () => setHistogram(null), [setHistogram]);

  // Fit the canvas inside the stage, keeping its aspect ratio.
  const [cw, ch] = canvasSize;
  const scale = cw && ch ? Math.min((boxW - PAD * 2) / cw, (boxH - PAD * 2) / ch) : 0;
  const width = Math.max(0, Math.floor(cw * scale));
  const height = Math.max(0, Math.floor(ch * scale));

  // Crop ratios are in output pixels; the overlay works in normalised coordinates.
  const [rw, rh] = rotatedSize(asset.width, asset.height, doc.geometry.rotate);
  const normalisedRatio = cropAspect ? cropAspect * (rh / rw) : null;

  return (
    <div
      ref={boxRef}
      className="relative grid min-h-[280px] min-w-0 place-items-center overflow-hidden bg-stage"
    >
      {failure ? (
        <div className="grid max-w-[420px] gap-3 p-6 text-center">
          {asset.preview_url && (
            <img
              src={asset.preview_url}
              alt={asset.original_name}
              className="max-h-[50vh] rounded object-contain"
            />
          )}
          <p className="flex items-start justify-center gap-2 text-[13px] text-warn">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {failure.message}
          </p>
          {failure.fix && <p className="text-[12.5px] text-fg-2">{failure.fix}</p>}
        </div>
      ) : (
        <>
          {!ready && (
            <div className="absolute inset-0 grid place-items-center">
              <div className="flex items-center gap-2 rounded-full bg-panel px-3 py-1.5 text-[12px] text-fg-2 shadow-float">
                <Spinner className="size-3.5" />
                Loading preview
              </div>
            </div>
          )}
          <div
            className={clsx("relative shadow-float", !ready && "invisible", asset.has_alpha && "checker")}
            style={{ width, height }}
          >
            <canvas
              ref={canvasRef}
              data-testid="studio-canvas"
              className="block size-full"
              aria-label={`Preview of ${asset.original_name}`}
              role="img"
            />
            {mode === "split" && (
              <>
                <input
                  type="range"
                  min={0}
                  max={1000}
                  value={Math.round(split * 1000)}
                  onChange={(event) => setSplit(Number(event.target.value) / 1000)}
                  aria-label="Before and after divider"
                  aria-valuetext={`${Math.round(split * 100)}% original`}
                  className="split-range absolute inset-0 z-10 size-full cursor-ew-resize touch-none opacity-0"
                />
                <Tag className="left-2.5">Before</Tag>
                <Tag className="right-2.5">After</Tag>
                <div
                  className="pointer-events-none absolute top-0 bottom-0 w-0.5 -translate-x-1/2 bg-cyan"
                  style={{ left: `${split * 100}%` }}
                >
                  <span className="absolute top-1/2 left-1/2 grid size-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border-2 border-cyan bg-bg text-cyan">
                    <ChevronsLeftRight className="size-4" aria-hidden="true" />
                  </span>
                </div>
              </>
            )}
            {mode === "side" && (
              <>
                <Tag className="left-2.5">Before</Tag>
                <Tag className="left-[calc(50%+10px)]">After</Tag>
                <div className="pointer-events-none absolute top-0 bottom-0 left-1/2 w-0.5 -translate-x-1/2 bg-bg" />
              </>
            )}
            {mode === "diff" && <Tag className="left-2.5">Difference ×4</Tag>}
            {mode === "before" && <Tag className="left-2.5">Before</Tag>}
            {cropping && ready && (
              <CropOverlay
                rect={cropOrFull(doc.geometry)}
                ratio={normalisedRatio}
                onCommit={(rect) => update("Crop", (d) => setCrop(d, rect))}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
