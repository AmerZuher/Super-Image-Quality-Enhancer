import { clsx } from "clsx";
import { FlipHorizontal2, FlipVertical2, RotateCcw, RotateCcwSquare, RotateCwSquare } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { Asset } from "@/lib/api/client";
import { cropOrFull, flipView, outputSize, resetGeometry, rotatedSize, rotateView, setCrop } from "../doc";
import { aspectName, formatDimensions } from "../format";
import { useEditor } from "../store";
import { fitRatio } from "./CropOverlay";

const PRESETS: { label: string; ratio: number | "original" | null }[] = [
  { label: "Free", ratio: null },
  { label: "Original", ratio: "original" },
  { label: "1:1", ratio: 1 },
  { label: "3:2", ratio: 3 / 2 },
  { label: "4:3", ratio: 4 / 3 },
  { label: "16:9", ratio: 16 / 9 },
  { label: "4:5", ratio: 4 / 5 },
  { label: "9:16", ratio: 9 / 16 },
];

export function CropPanel({ asset }: { asset: Asset }) {
  const doc = useEditor((s) => s.doc);
  const update = useEditor((s) => s.update);
  const aspect = useEditor((s) => s.cropAspect);
  const setAspect = useEditor((s) => s.setCropAspect);
  const g = doc.geometry;
  const [rw, rh] = rotatedSize(asset.width, asset.height, g.rotate);
  const [ow, oh] = outputSize(asset.width, asset.height, g);
  const named = aspectName(ow, oh);

  const choose = (ratio: number | "original" | null) => {
    const value = ratio === "original" ? rw / rh : ratio;
    setAspect(value);
    if (value) update("Crop", (d) => setCrop(d, fitRatio(cropOrFull(d.geometry), value * (rh / rw))));
  };
  const rotate = (direction: 1 | -1) => {
    // The locked ratio is in output pixels, so it turns with the image.
    if (aspect) setAspect(1 / aspect);
    update("Rotate", (d) => rotateView(d, direction));
  };
  const flipAspect = () => {
    if (!aspect) return;
    choose(1 / aspect);
  };

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
      <section className="grid gap-2" aria-labelledby="crop-rotate">
        <h3 id="crop-rotate" className="eyebrow">
          Rotate and flip
        </h3>
        <div className="grid grid-cols-2 gap-2">
          <Button icon={<RotateCcwSquare />} onClick={() => rotate(-1)}>
            Left
          </Button>
          <Button icon={<RotateCwSquare />} onClick={() => rotate(1)}>
            Right
          </Button>
          <Button icon={<FlipHorizontal2 />} onClick={() => update("Flip", (d) => flipView(d, "h"))}>
            Flip horizontal
          </Button>
          <Button icon={<FlipVertical2 />} onClick={() => update("Flip", (d) => flipView(d, "v"))}>
            Flip vertical
          </Button>
        </div>
      </section>

      <fieldset className="grid gap-2">
        <legend className="eyebrow mb-2">Aspect ratio</legend>
        <div className="grid grid-cols-4 gap-1.5">
          {PRESETS.map((preset) => {
            const value = preset.ratio === "original" ? rw / rh : preset.ratio;
            const active =
              value === null ? aspect === null : aspect !== null && Math.abs(aspect - value) < 1e-6;
            return (
              <button
                key={preset.label}
                type="button"
                aria-pressed={active}
                onClick={() => choose(preset.ratio)}
                className={clsx(
                  "h-8 rounded-md border text-[12px] transition",
                  active
                    ? "border-cyan bg-cyan-soft font-semibold text-cyan"
                    : "border-line-2 text-fg-2 hover:border-cyan hover:text-fg",
                )}
              >
                {preset.label}
              </button>
            );
          })}
        </div>
        {aspect && Math.abs(aspect - 1) > 1e-6 && (
          <Button size="sm" variant="ghost" onClick={flipAspect} className="justify-self-start">
            Swap to {aspect > 1 ? "portrait" : "landscape"}
          </Button>
        )}
      </fieldset>

      <section className="grid gap-1 rounded-lg border border-line bg-panel-2 p-3 text-[12.5px]">
        <div className="flex justify-between gap-2">
          <span className="text-muted">Output</span>
          <span className="font-mono text-fg tabular-nums">{formatDimensions(ow, oh)}</span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-muted">Shape</span>
          <span className="text-fg">{named ?? `${(ow / oh).toFixed(2)}:1`}</span>
        </div>
        <p className="mt-1 text-[12px] text-fg-2">
          Drag the frame or its handles on the image. Arrow keys nudge it; hold Shift for bigger steps.
        </p>
      </section>

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          icon={<RotateCcw />}
          disabled={!g.crop}
          onClick={() => update("Clear crop", (d) => setCrop(d, null))}
        >
          Clear crop
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!g.crop && g.rotate === 0 && !g.flip_h && !g.flip_v}
          onClick={() => {
            setAspect(null);
            update("Reset geometry", resetGeometry);
          }}
        >
          Reset rotation and crop
        </Button>
      </div>
    </div>
  );
}
