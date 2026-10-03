import { clsx } from "clsx";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  ExternalLink,
  RotateCcw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { ForgeIcon } from "@/components/ui/Logo";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { errorMessage, type Model, type ModelTask } from "@/lib/api/client";
import { useCancelJob } from "@/lib/api/queries";
import { formatBytes } from "@/lib/format";
import { useJob } from "../studio/api";
import { useInstallModel, useRemoveModel } from "./api";

export const TASKS: { id: ModelTask; label: string }[] = [
  { id: "upscale", label: "Upscale" },
  { id: "denoise", label: "Denoise" },
  { id: "deblur", label: "Deblur" },
  { id: "colorize", label: "Colorize" },
  { id: "erase", label: "Erase objects" },
  { id: "background", label: "Remove background" },
  { id: "face", label: "Restore faces" },
  { id: "embed", label: "Library search and tags" },
];

/** Tasks AI Lab can run on an image (the search model only powers the Library). */
export const RUN_TASKS = TASKS.filter((t) => t.id !== "embed");

const SPEED: Record<Model["speed"], string> = { fast: "Fast", balanced: "Balanced", slow: "Slow" };

/** Download, progress, installed state or retry for one model. */
export function ModelControl({ model, compact = false }: { model: Model; compact?: boolean }) {
  const install = useInstallModel();
  const remove = useRemoveModel();
  const cancel = useCancelJob();
  const { data: job } = useJob(model.status === "downloading" ? model.job_id : null);
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(timer);
  }, [armed]);

  if (model.status === "downloading") {
    return (
      <div className="grid min-w-[140px] gap-1" data-testid={`downloading-${model.id}`}>
        <ProgressBar value={job?.progress ?? 0} label={`Downloading ${model.name}`} />
        <div className="flex items-center justify-between gap-2 text-[11px] text-muted">
          <span>{job?.message ?? "Starting"}</span>
          {job && (
            <button
              type="button"
              className="text-fg-2 underline hover:text-fg"
              onClick={() => cancel.mutate(job.id)}
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    );
  }
  if (model.status === "installed") {
    return (
      <div className="flex items-center gap-1.5">
        <Chip tone="ok" icon={<CheckCircle2 />}>
          Installed
        </Chip>
        {!compact && (
          <Button
            size="sm"
            variant={armed ? "danger" : "ghost"}
            icon={<Trash2 />}
            loading={remove.isPending}
            aria-label={armed ? `Confirm removing ${model.name}` : `Remove ${model.name}`}
            onClick={() => (armed ? remove.mutate(model.id) : setArmed(true))}
          >
            {armed ? "Remove?" : undefined}
          </Button>
        )}
      </div>
    );
  }
  const failed = model.status === "failed";
  const problem = install.error ? errorMessage(install.error) : null;
  return (
    <div className="grid justify-items-end gap-1">
      <Button
        size="sm"
        icon={failed ? <RotateCcw /> : <Download />}
        loading={install.isPending}
        onClick={() => install.mutate(model.id)}
        aria-label={`${failed ? "Retry downloading" : "Download"} ${model.name}`}
      >
        {failed ? "Retry" : `Download ${formatBytes(model.size_bytes)}`}
      </Button>
      {(failed || problem) && (
        <span className="flex max-w-[220px] items-start gap-1 text-right text-[11px] text-err">
          <AlertTriangle className="mt-px size-3 shrink-0" aria-hidden="true" />
          {problem?.message ??
            String((model.error as { message?: string } | null)?.message ?? "Download failed")}
        </span>
      )}
    </div>
  );
}

interface Benchmark {
  psnr: number;
  gain_db: number;
}

function benchmarkOf(model: Model): Benchmark | null {
  const b = model.benchmark as Partial<Benchmark> | null | undefined;
  return typeof b?.psnr === "number" && typeof b.gain_db === "number" ? (b as Benchmark) : null;
}

export function ModelCard({ model }: { model: Model }) {
  const bench = benchmarkOf(model);
  return (
    <li
      className={clsx(
        "grid gap-2 rounded-lg border bg-panel-2 p-3",
        model.status === "installed" ? "border-gold/35" : "border-line",
      )}
      data-testid={`model-${model.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-gold" aria-hidden="true" />
          <div className="min-w-0">
            <h4 className="truncate text-[13px] font-semibold text-fg">{model.name}</h4>
            <p className="text-[12px] text-fg-2">{model.summary}</p>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
          {model.scale > 1 && <span className="font-mono text-fg-2">×{model.scale}</span>}
          <span>{SPEED[model.speed]}</span>
          {model.license_url ? (
            <a
              href={model.license_url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-0.5 hover:text-fg hover:underline"
            >
              {model.license}
              <ExternalLink className="size-2.5" aria-hidden="true" />
            </a>
          ) : (
            <span>{model.license}</span>
          )}
          {model.source === "forge" && (
            <Chip tone="gold" icon={<ForgeIcon className="size-3" />}>
              Trained in Forge
            </Chip>
          )}
          {bench && (
            <span className="font-mono text-fg-2" title="Measured on held-out crops when it was published">
              {bench.psnr.toFixed(2)} dB ({bench.gain_db >= 0 ? "+" : ""}
              {bench.gain_db.toFixed(2)} vs bicubic)
            </span>
          )}
          {model.tags.includes("yours") && <Chip tone="gold">Your model</Chip>}
          {model.recommended && <Chip tone="gold">Recommended</Chip>}
        </div>
        <ModelControl model={model} />
      </div>
    </li>
  );
}

export function ModelLibrary({ models }: { models: Model[] }) {
  const installed = models.filter((m) => m.status === "installed").reduce((n, m) => n + m.size_bytes, 0);
  return (
    <div className="grid gap-5">
      <p className="text-[12px] text-fg-2">
        Models download once from their authors' GitHub releases and are checked against a published checksum.
        Every model here allows commercial use. Installed: {formatBytes(installed)}.
      </p>
      {TASKS.map((task) => {
        const list = models.filter((m) => m.task === task.id);
        if (!list.length) return null;
        return (
          <section key={task.id} aria-labelledby={`models-${task.id}`} className="grid gap-2">
            <h3 id={`models-${task.id}`} className="eyebrow">
              {task.label}
            </h3>
            <ul className="grid gap-2">
              {list.map((m) => (
                <ModelCard key={m.id} model={m} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
