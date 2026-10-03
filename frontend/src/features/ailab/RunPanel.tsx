import { Link } from "@tanstack/react-router";
import { clsx } from "clsx";
import {
  AlertTriangle,
  Cpu,
  Download,
  Eraser,
  Focus,
  Maximize2,
  Palette,
  ScanSearch,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Wand2,
  XCircle,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Spinner } from "@/components/ui/Spinner";
import { type AiPlan, type Asset, errorMessage, type Model, type ModelTask } from "@/lib/api/client";
import { useCancelJob, useJobs } from "@/lib/api/queries";
import { formatBytes, relativeTime } from "@/lib/format";
import { formatDimensions } from "../studio/format";
import { usePlan, useRemoveResult, useStartRun } from "./api";
import { ModelControl, RUN_TASKS } from "./Models";
import { strokesFor, useAiLabStore } from "./store";

/** Tasks whose models run on the CPU worker, whatever the device setting. */
const CPU_TASKS: ModelTask[] = ["background", "deblur", "erase"];

const TASK_ICON: Record<ModelTask, ReactNode> = {
  upscale: <Maximize2 />,
  denoise: <Wand2 />,
  deblur: <Focus />,
  colorize: <Palette />,
  erase: <Eraser />,
  background: <Scissors />,
  face: <Sparkles />,
  embed: <ScanSearch />,
};

function runLabel(task: ModelTask, model: Model | undefined): string {
  if (task === "upscale") return model ? `Upscale ×${model.scale}` : "Upscale";
  if (task === "denoise") return "Denoise";
  if (task === "deblur") return "Deblur";
  if (task === "colorize") return "Colorize";
  if (task === "erase") return "Erase painted areas";
  if (task === "background") return "Remove background";
  if (task === "face") return "Restore faces";
  return "Restore faces";
}

function PlanCard({ plan }: { plan: AiPlan }) {
  const rows: [string, ReactNode][] = [
    [
      "Result",
      <span key="r" className="font-mono">
        {formatDimensions(plan.output_width, plan.output_height)}
      </span>,
    ],
    [
      "Size",
      `${plan.output_megapixels} MP · PNG ${plan.bit_depth}-bit${plan.has_alpha ? " with transparency" : ""}`,
    ],
    [
      "Runs on",
      <span key="d" className="flex items-center gap-1">
        <Cpu className="size-3.5 text-muted" aria-hidden="true" />
        {plan.device === "cuda" ? plan.device_name.replace(/^NVIDIA (GeForce )?/, "") : "CPU"}
      </span>,
    ],
  ];
  if (plan.tile) {
    rows.push([
      "Tiles",
      `${plan.tiles} × ${plan.tile} px${plan.batch && plan.batch > 1 ? `, ${plan.batch} at a time` : ""}`,
    ]);
  }
  if (plan.estimated_memory_bytes) {
    rows.push(["GPU memory", `about ${formatBytes(plan.estimated_memory_bytes)} (measured)`]);
  } else if (plan.device === "cuda" && plan.tile) {
    rows.push(["GPU memory", "measured on the first run"]);
  }
  if (plan.restore_faces) rows.push(["Faces", "restored with GFPGAN"]);
  rows.push(["Disk", `up to ${formatBytes(plan.disk_bytes)}`]);
  return (
    <div
      className="grid gap-1.5 rounded-lg border border-line bg-panel-2 p-3 text-[12.5px]"
      data-testid="plan"
    >
      {rows.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-3">
          <span className="text-muted">{label}</span>
          <span className="text-right text-fg">{value}</span>
        </div>
      ))}
      {plan.warnings.map((w) => (
        <p key={w} className="mt-1 flex items-start gap-1.5 text-[12px] text-warn">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          {w}
        </p>
      ))}
    </div>
  );
}

function ActiveRuns({ assetId }: { assetId: string }) {
  const { data: jobs } = useJobs();
  const cancel = useCancelJob();
  const active = (jobs ?? []).filter(
    (j) =>
      j.kind === "ai.run" &&
      (j.params as { asset_id?: string }).asset_id === assetId &&
      (j.state === "queued" || j.state === "running"),
  );
  if (!active.length) return null;
  return (
    <ul className="grid gap-2" aria-label="Runs in progress">
      {active.map((j) => (
        <li
          key={j.id}
          className="grid gap-1.5 rounded-lg border border-gold/35 bg-gold-soft p-2.5"
          data-testid="active-run"
        >
          <div className="flex items-center gap-2 text-[12.5px]">
            <Spinner className="size-3.5 text-gold" />
            <span className="min-w-0 flex-1 truncate text-fg">{j.title}</span>
            <button
              type="button"
              className="text-[11.5px] text-fg-2 underline hover:text-fg"
              onClick={() => cancel.mutate(j.id)}
            >
              Cancel
            </button>
          </div>
          <ProgressBar value={j.progress} tone="gold" label={j.title} />
          <span className="text-[11px] text-muted">{j.message}</span>
        </li>
      ))}
    </ul>
  );
}

function ResultRow({
  result,
  parentId,
  selected,
  onSelect,
}: {
  result: Asset;
  parentId: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const remove = useRemoveResult(parentId);
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  const d = (result.derivation ?? {}) as {
    model_name?: string;
    device_name?: string;
    seconds?: number;
    fallbacks?: string[];
  };
  return (
    <li
      className={clsx(
        "grid grid-cols-[56px_minmax(0,1fr)] gap-2.5 rounded-lg border p-2 transition",
        selected ? "border-gold bg-gold-soft" : "border-line bg-panel-2 hover:border-line-2",
      )}
      data-testid="result"
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={`Compare ${result.original_name}`}
        className="relative h-14 w-14 overflow-hidden rounded-md bg-panel"
      >
        {result.thumb_url ? (
          <img src={result.thumb_url} alt="" className="size-full object-cover" />
        ) : (
          <span className="grid size-full place-items-center">
            <Spinner className="size-4 text-muted" />
          </span>
        )}
      </button>
      <div className="grid min-w-0 gap-0.5">
        <button
          type="button"
          onClick={onSelect}
          className="truncate text-left text-[12.5px] font-medium text-fg hover:underline"
        >
          {result.original_name}
        </button>
        <span className="truncate text-[11px] text-muted">
          <span className="font-mono">{formatDimensions(result.width, result.height)}</span> ·{" "}
          {d.device_name ?? "CPU"}
          {d.seconds != null ? ` · ${Math.round(d.seconds)} s` : ""} · {relativeTime(result.created_at)}
        </span>
        {d.fallbacks && d.fallbacks.length > 0 && (
          <span
            className="flex items-center gap-1 truncate text-[11px] text-warn"
            title={d.fallbacks.join("; ")}
          >
            <AlertTriangle className="size-3 shrink-0" aria-hidden="true" />
            Adjusted to fit memory: {d.fallbacks.at(-1)}
          </span>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <Link
            to="/studio"
            search={{ asset: result.id }}
            className="inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[11.5px] text-fg-2 hover:bg-panel hover:text-fg"
          >
            <SlidersHorizontal className="size-3.5" aria-hidden="true" />
            Edit in Studio
          </Link>
          <a
            href={result.original_url}
            download={result.original_name}
            className="inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[11.5px] text-fg-2 hover:bg-panel hover:text-fg"
          >
            <Download className="size-3.5" aria-hidden="true" />
            PNG
          </a>
          <button
            type="button"
            onClick={() => (armed ? remove.mutate(result.id) : setArmed(true))}
            className={clsx(
              "inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[11.5px]",
              armed ? "text-err" : "text-muted hover:bg-panel hover:text-err",
            )}
            aria-label={armed ? `Confirm deleting ${result.original_name}` : `Delete ${result.original_name}`}
          >
            <Trash2 className="size-3.5" aria-hidden="true" />
            {armed ? "Delete?" : ""}
          </button>
        </div>
      </div>
    </li>
  );
}

export function RunPanel({
  asset,
  models,
  results,
  selectedResult,
  onSelectResult,
  onPaint,
}: {
  asset: Asset;
  models: Model[];
  results: Asset[];
  selectedResult: string | undefined;
  onSelectResult: (id: string) => void;
  /** Picking Erase shows the paint layer, so any compared result is put away. */
  onPaint?: () => void;
}) {
  const task = useAiLabStore((s) => s.task);
  const setTask = useAiLabStore((s) => s.setTask);
  const strokes = useAiLabStore((s) => strokesFor(s, asset.id));
  const [modelId, setModelId] = useState<string | undefined>();
  const [device, setDevice] = useState<"auto" | "cpu">("auto");
  const [faces, setFaces] = useState(false);
  const faceModel = models.find((m) => m.task === "face");
  const forTask = models.filter((m) => m.task === task);
  const installed = forTask.filter((m) => m.status === "installed");
  const chosen =
    installed.find((m) => m.id === modelId) ?? installed.find((m) => m.recommended) ?? installed[0];
  const ready = asset.status === "ready";
  const withFaces = task === "upscale" && faces && faceModel?.status === "installed";
  const painted = task !== "erase" || strokes.length > 0;
  // The plan doesn't depend on the mask, so it shows before anything is painted.
  const request =
    chosen && ready
      ? {
          asset_id: asset.id,
          model_id: chosen.id,
          device,
          restore_faces: withFaces,
          ...(task === "erase" && painted ? { mask: { strokes } } : {}),
        }
      : null;
  const plan = usePlan(request);
  const start = useStartRun();
  const planError = plan.error ? errorMessage(plan.error) : null;
  const runError = start.error ? errorMessage(start.error) : null;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
      <fieldset className="grid gap-2">
        <legend className="eyebrow mb-2">What to do</legend>
        <div className="grid grid-cols-2 gap-1.5">
          {RUN_TASKS.map((t) => (
            <button
              key={t.id}
              type="button"
              aria-pressed={task === t.id}
              onClick={() => {
                setTask(t.id);
                if (t.id === "erase") onPaint?.();
              }}
              className={clsx(
                "grid h-14 place-items-center content-center gap-1 rounded-md border px-1 text-center text-[11.5px] leading-tight transition [&_svg]:size-4",
                task === t.id
                  ? "border-gold bg-gold-soft font-semibold text-gold"
                  : "border-line-2 text-fg-2 hover:border-gold/60",
              )}
            >
              {TASK_ICON[t.id]}
              {t.label}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="grid gap-1.5">
        <legend className="eyebrow mb-2">Model</legend>
        {forTask.map((m) =>
          m.status === "installed" ? (
            <label
              key={m.id}
              className={clsx(
                "flex cursor-pointer items-center gap-2.5 rounded-md border px-2.5 py-2 text-[12.5px] transition has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-gold",
                chosen?.id === m.id ? "border-gold bg-gold-soft" : "border-line hover:border-line-2",
              )}
            >
              <input
                type="radio"
                name="ai-model"
                className="sr-only"
                checked={chosen?.id === m.id}
                onChange={() => setModelId(m.id)}
              />
              <Sparkles
                className={clsx("size-3.5 shrink-0", chosen?.id === m.id ? "text-gold" : "text-muted")}
              />
              <span className="min-w-0 flex-1 truncate text-fg">{m.name}</span>
              <span className="text-[11px] text-muted capitalize">{m.speed}</span>
            </label>
          ) : (
            <div
              key={m.id}
              className="flex items-center gap-2.5 rounded-md border border-dashed border-line px-2.5 py-2 text-[12.5px]"
            >
              <span className="min-w-0 flex-1 truncate text-fg-2">{m.name}</span>
              <ModelControl model={m} compact />
            </div>
          ),
        )}
      </fieldset>

      {task === "upscale" && faceModel && (
        <div className="flex items-center justify-between gap-2 text-[12.5px] text-fg-2">
          {faceModel.status === "installed" ? (
            <label className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={faces}
                onChange={(e) => setFaces(e.target.checked)}
                className="size-4 accent-[var(--gold)]"
              />
              Also restore faces
            </label>
          ) : (
            <>
              <span>Restore faces needs {faceModel.name}</span>
              <ModelControl model={faceModel} compact />
            </>
          )}
        </div>
      )}

      {task === "erase" && !strokes.length && (
        <p className="flex items-start gap-1.5 text-[12px] text-fg-2">
          <Eraser className="mt-0.5 size-3.5 shrink-0 text-gold" aria-hidden="true" />
          Paint over what to remove on the image, then erase it. Each area is filled in from its surroundings;
          small to medium objects work best.
        </p>
      )}

      {!CPU_TASKS.includes(task) && (
        <label className="flex items-center justify-between gap-2 text-[12.5px] text-fg-2">
          Run on
          <select
            value={device}
            onChange={(e) => setDevice(e.target.value as "auto" | "cpu")}
            className="h-8 rounded-md border border-line-2 bg-bg px-2 text-[12.5px] text-fg"
          >
            <option value="auto">GPU when available</option>
            <option value="cpu">CPU only</option>
          </select>
        </label>
      )}

      {plan.data && chosen && <PlanCard plan={plan.data} />}
      {planError && (
        <div role="alert" className="grid gap-0.5 text-[12px]">
          <p className="flex items-start gap-1.5 text-err">
            <XCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {planError.message}
          </p>
          {planError.fix && <p className="text-fg-2">{planError.fix}</p>}
        </div>
      )}

      <Button
        variant="ai"
        icon={TASK_ICON[task]}
        disabled={!chosen || !ready || !painted || Boolean(planError)}
        loading={start.isPending}
        onClick={() => request && painted && start.mutate(request)}
      >
        {chosen ? runLabel(task, chosen) : "Download a model first"}
      </Button>
      {runError && (
        <p role="alert" className="flex items-start gap-1.5 text-[12px] text-err">
          <XCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          {runError.message}
        </p>
      )}

      <ActiveRuns assetId={asset.id} />

      <section aria-labelledby="results-heading" className="grid gap-2">
        <h3 id="results-heading" className="eyebrow">
          Results from this image
        </h3>
        {results.length ? (
          <ul className="grid gap-2">
            {results.map((r) => (
              <ResultRow
                key={r.id}
                result={r}
                parentId={asset.id}
                selected={r.id === selectedResult}
                onSelect={() => onSelectResult(r.id)}
              />
            ))}
          </ul>
        ) : (
          <p className="text-[12px] text-muted">
            Nothing yet. Results become new images in your library; the original stays as it is.
          </p>
        )}
      </section>
    </div>
  );
}
