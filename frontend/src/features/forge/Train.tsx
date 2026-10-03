import { Link } from "@tanstack/react-router";
import { clsx } from "clsx";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileOutput,
  Info,
  Pause,
  Play,
  Sparkles,
  Square,
  Trash2,
  Upload,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { JobStateChip } from "@/components/ui/JobStateChip";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Spinner } from "@/components/ui/Spinner";
import { INPUT } from "@/features/library/RulesEditor";
import { useJob } from "@/features/studio/api";
import {
  errorMessage,
  type ForgeDataset,
  type ForgeProject,
  type ForgeRun,
  type ForgeRunDetail,
  type TrainSettings,
} from "@/lib/api/client";
import { formatBytes, formatDuration, relativeTime } from "@/lib/format";
import {
  downloadOnnx,
  downloadWeights,
  useDeleteRun,
  useExportOnnx,
  usePublish,
  useRunControl,
  useStartTraining,
} from "./api";
import { LineChart } from "./Chart";
import { suggestedPatch } from "./graph";

const FIELD = "grid gap-1 text-[12px] text-fg-2";

/** Pick a dataset and settings, then train this design on the GPU. */
export function TrainForm({
  project,
  datasets,
  onStarted,
  onNewDataset,
}: {
  project: ForgeProject;
  datasets: ForgeDataset[];
  onStarted: (run: ForgeRun) => void;
  onNewDataset: () => void;
}) {
  const start = useStartTraining();
  const ready = datasets.filter((d) => d.state === "succeeded" && d.train_crops > 0);
  const { stats, problems } = project.analysis;
  const [datasetId, setDatasetId] = useState(ready[0]?.id ?? "");
  const dataset = ready.find((d) => d.id === datasetId);
  const scale = stats.scale ?? 1;
  const multiple = stats.patch_multiple;
  const [settings, setSettings] = useState<TrainSettings>({
    steps: 20000,
    batch: 16,
    patch: 48,
    lr: 2e-4,
    loss: "l1",
    val_every: 500,
    seed: 0,
    precision: "auto",
  });

  useEffect(() => {
    if (!datasetId && ready[0]) setDatasetId(ready[0].id);
  }, [datasetId, ready]);
  // Fit the patch to the chosen dataset and this model's scale.
  const crop = dataset?.settings.crop ?? 256;
  useEffect(() => {
    setSettings((s) => ({ ...s, patch: suggestedPatch(crop, scale, multiple, 48) }));
  }, [crop, scale, multiple]);

  const patchProblem =
    settings.patch % multiple
      ? `Use a multiple of ${multiple} px: this model halves the image.`
      : settings.patch * scale > crop
        ? `At ×${scale} a ${settings.patch} px patch needs ${settings.patch * scale} px crops; this dataset has ${crop}.`
        : null;
  const canStart = problems.length === 0 && Boolean(dataset) && !patchProblem;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!dataset) return;
    start.mutate({ projectId: project.id, datasetId: dataset.id, settings }, { onSuccess: onStarted });
  };
  const set = <K extends keyof TrainSettings>(key: K, value: TrainSettings[K]) =>
    setSettings((s) => ({ ...s, [key]: value }));
  const number = (
    key: "steps" | "batch" | "patch" | "val_every" | "seed",
    label: string,
    min: number,
    max: number,
    unit = "",
  ) => (
    <label className={FIELD}>
      <span className="text-fg">{label}</span>
      <span className="flex items-center gap-1.5">
        <input
          type="number"
          className={clsx(INPUT, "w-full min-w-0")}
          min={min}
          max={max}
          value={settings[key]}
          onChange={(e) => e.target.value && set(key, Math.round(Number(e.target.value)))}
        />
        {unit && <span className="text-[11.5px] text-muted">{unit}</span>}
      </span>
    </label>
  );

  return (
    <form
      noValidate
      onSubmit={submit}
      className="grid gap-4"
      aria-label="Train this model"
      data-testid="forge-train-form"
    >
      <div>
        <h2 className="text-[14px] font-semibold text-fg">Train {project.name}</h2>
        <p className="text-[12px] text-fg-2">
          Runs on the GPU in three-minute chunks, so other AI jobs still get their turn. Pause or stop any
          time; the best checkpoint is kept.
        </p>
      </div>
      {problems.length > 0 && (
        <p role="alert" className="flex items-start gap-1.5 text-[12px] text-err">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          Fix the design first: {problems[0]?.message}
        </p>
      )}
      <div className={FIELD}>
        <label htmlFor="forge-train-dataset" className="text-fg">
          Dataset
        </label>
        {ready.length ? (
          <select
            id="forge-train-dataset"
            className={INPUT}
            value={datasetId}
            onChange={(e) => setDatasetId(e.target.value)}
          >
            {ready.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} · {d.train_crops.toLocaleString()} crops of {d.settings.crop} px
              </option>
            ))}
          </select>
        ) : (
          <span className="flex flex-wrap items-center gap-2 text-[12px]">
            No dataset is ready yet.
            <Button size="sm" onClick={onNewDataset}>
              Build one
            </Button>
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {number("steps", "Steps", 10, 2_000_000)}
        {number("batch", "Batch", 1, 256, "patches")}
        {number("patch", "Patch", 8, 256, "px")}
        <label className={FIELD}>
          <span className="text-fg">Learning rate</span>
          <input
            type="number"
            className={clsx(INPUT, "w-full min-w-0")}
            step="any"
            min={0.00001}
            max={0.01}
            value={settings.lr}
            onChange={(e) => e.target.value && set("lr", Number(e.target.value))}
          />
        </label>
        <label className={FIELD}>
          <span className="text-fg">Loss</span>
          <select
            className={INPUT}
            value={settings.loss}
            onChange={(e) => set("loss", e.target.value as TrainSettings["loss"])}
          >
            <option value="l1">L1 (sharpest)</option>
            <option value="charbonnier">Charbonnier</option>
            <option value="mse">MSE (softer)</option>
          </select>
        </label>
        {number("val_every", "Check every", 10, 100_000, "steps")}
        <label className={FIELD}>
          <span className="text-fg">Precision</span>
          <select
            className={clsx(INPUT, "w-full min-w-0")}
            value={settings.precision}
            onChange={(e) => set("precision", e.target.value as TrainSettings["precision"])}
          >
            <option value="auto">Automatic</option>
            <option value="fp32">Full (fp32)</option>
          </select>
        </label>
        {number("seed", "Seed", 0, 2 ** 31 - 1)}
      </div>
      {patchProblem && (
        <p role="alert" className="flex items-start gap-1.5 text-[12px] text-warn">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          {patchProblem}
        </p>
      )}
      <p className="flex items-start gap-1.5 text-[11.5px] text-muted">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        If the GPU runs out of memory the batch is halved and gradients are accumulated, so the result is the
        same, just slower.
      </p>
      {start.error && (
        <p role="alert" className="text-[12px] text-err">
          {errorMessage(start.error).message} {errorMessage(start.error).fix}
        </p>
      )}
      <Button
        type="submit"
        variant="ai"
        icon={<Play />}
        loading={start.isPending}
        disabled={!canStart}
        className="justify-self-start"
      >
        Start training
      </Button>
    </form>
  );
}

function runLabel(run: ForgeRun): string {
  if (run.state === "running" && run.paused) return "Paused";
  return "";
}

export function RunList({
  runs,
  current,
  onPick,
}: {
  runs: ForgeRun[];
  current: string | undefined;
  onPick: (id: string) => void;
}) {
  if (runs.length === 0) return <p className="text-[12px] text-muted">No training runs yet.</p>;
  return (
    <ul className="grid gap-1" aria-label="Training runs">
      {runs.map((run) => (
        <li key={run.id}>
          <button
            type="button"
            onClick={() => onPick(run.id)}
            aria-current={current === run.id ? "page" : undefined}
            className={clsx(
              "grid w-full gap-1 rounded-lg border px-2.5 py-2 text-left transition",
              current === run.id
                ? "border-cyan bg-cyan-soft"
                : "border-transparent hover:border-line-2 hover:bg-panel-2",
            )}
          >
            <span className="flex flex-wrap items-center gap-1.5">
              {runLabel(run) ? <Chip icon={<Pause />}>Paused</Chip> : <JobStateChip state={run.state} />}
              {run.model_id && (
                <Chip tone="gold" icon={<Sparkles />}>
                  In AI Lab
                </Chip>
              )}
              <span className="text-[11px] text-muted">{relativeTime(run.created_at)}</span>
            </span>
            <span className="font-mono text-[11px] text-fg-2">
              {run.step.toLocaleString()} / {run.total_steps.toLocaleString()} steps
              {run.best_psnr !== null && ` · ${run.best_psnr.toFixed(2)} dB`}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <dt className="text-[11.5px] text-muted">{label}</dt>
      <dd className="text-[15px] font-semibold text-fg">{value}</dd>
      {sub && <dd className="text-[11px] text-muted">{sub}</dd>}
    </div>
  );
}

function PublishPanel({ run }: { run: ForgeRun }) {
  const publish = usePublish();
  const [name, setName] = useState(run.project_name);
  const [summary, setSummary] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const { data: job } = useJob(jobId);
  const [downloading, setDownloading] = useState(false);
  const busy = job && (job.state === "queued" || job.state === "running");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    publish.mutate(
      { id: run.id, name: name.trim() || run.project_name, summary },
      { onSuccess: (j) => setJobId(j.id) },
    );
  };

  return (
    <section className="grid gap-3 rounded-xl border border-line p-3" aria-label="Publish">
      <div>
        <h3 className="text-[13px] font-semibold text-fg">Publish to AI Lab</h3>
        <p className="text-[12px] text-fg-2">
          Scores the best checkpoint on your held-out crops against bicubic, then adds it to AI Lab as a new
          version you can run on any image, in Studio, AI Lab and Flows.
        </p>
      </div>
      {run.model_id && (
        <p className="flex flex-wrap items-center gap-2 text-[12px] text-fg-2">
          <Chip tone="gold" icon={<Sparkles />}>
            Published
          </Chip>
          <span className="font-mono">{run.model_id}</span>
          <Link to="/ai-lab" className="text-cyan hover:underline">
            Open AI Lab
          </Link>
        </p>
      )}
      <form onSubmit={submit} className="grid gap-2 sm:grid-cols-[1fr_1.5fr_auto] sm:items-end">
        <label className={FIELD}>
          <span className="text-fg">Name in AI Lab</span>
          <input className={INPUT} value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className={FIELD}>
          <span className="text-fg">Description (optional)</span>
          <input
            className={INPUT}
            value={summary}
            maxLength={300}
            placeholder="Filled in from the benchmark"
            onChange={(e) => setSummary(e.target.value)}
          />
        </label>
        <Button
          type="submit"
          variant="ai"
          icon={<Upload />}
          loading={publish.isPending || Boolean(busy)}
          disabled={run.best_step === null}
        >
          {run.model_id ? "Publish again" : "Publish"}
        </Button>
      </form>
      {busy && (
        <p className="flex items-center gap-2 text-[12px] text-fg-2">
          <Spinner className="size-3.5" />
          {job?.message || "Waiting for the GPU"}
        </p>
      )}
      {job?.state === "succeeded" && (
        <p className="flex items-center gap-1.5 text-[12px] text-ok" role="status">
          <CheckCircle2 className="size-3.5" aria-hidden="true" />
          {job.message}
        </p>
      )}
      {(publish.error || job?.state === "failed") && (
        <p role="alert" className="flex items-start gap-1.5 text-[12px] text-err">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          {publish.error
            ? `${errorMessage(publish.error).message} ${errorMessage(publish.error).fix ?? ""}`
            : job?.message}
        </p>
      )}
      <Button
        size="sm"
        variant="ghost"
        icon={<Download />}
        className="justify-self-start"
        disabled={run.best_step === null}
        loading={downloading}
        onClick={async () => {
          setDownloading(true);
          try {
            await downloadWeights(run);
          } finally {
            setDownloading(false);
          }
        }}
        title="Weights for the generated code (safetensors)"
      >
        Download weights
      </Button>
      <OnnxExport run={run} />
    </section>
  );
}

interface OnnxInfo {
  step: number;
  size: number;
  max_difference: number;
  multiple: number;
}

/** Export the best checkpoint to ONNX (checked against PyTorch on the AI worker) and download it. */
function OnnxExport({ run }: { run: ForgeRun }) {
  const exporter = useExportOnnx();
  const [jobId, setJobId] = useState<string | null>(null);
  const { data: job } = useJob(jobId);
  const [downloading, setDownloading] = useState(false);
  const busy = exporter.isPending || job?.state === "queued" || job?.state === "running";
  const info = run.onnx as OnnxInfo | null | undefined;
  const stale = info && run.best_step !== null && info.step !== run.best_step;
  const failure = exporter.error
    ? errorMessage(exporter.error)
    : job?.state === "failed"
      ? { message: job.message, fix: undefined }
      : null;

  return (
    <div className="grid gap-2 border-t border-line pt-3" data-testid="onnx-export">
      <div>
        <h4 className="text-[12.5px] font-semibold text-fg">ONNX</h4>
        <p className="text-[12px] text-fg-2">
          One file for ONNX Runtime and other tools: input <span className="font-mono">input</span>, N ×{" "}
          {run.color === "y" ? 1 : 3} × H × W with values 0 to 1
          {info && info.multiple > 1 ? `, sides in steps of ${info.multiple}` : ""}. It is checked against
          PyTorch before it's offered.
        </p>
      </div>
      {info && (
        <p className="flex flex-wrap items-center gap-2 text-[12px] text-fg-2" role="status">
          <Chip tone="ok" icon={<CheckCircle2 />}>
            Matches PyTorch
          </Chip>
          <span>
            Step {info.step.toLocaleString()} · {formatBytes(info.size)} · largest difference{" "}
            <span className="font-mono">{info.max_difference.toExponential(1)}</span>
          </span>
          {stale && (
            <span className="flex items-center gap-1 text-warn">
              <AlertTriangle className="size-3.5" aria-hidden="true" />
              Older than the best checkpoint (step {run.best_step?.toLocaleString()})
            </span>
          )}
        </p>
      )}
      {busy && (
        <p className="flex items-center gap-2 text-[12px] text-fg-2">
          <Spinner className="size-3.5" />
          {job?.message || "Waiting for the AI worker"}
        </p>
      )}
      {failure && (
        <p role="alert" className="flex items-start gap-1.5 text-[12px] text-err">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          {failure.message} {failure.fix ?? ""}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          icon={<FileOutput />}
          disabled={run.best_step === null}
          loading={busy}
          onClick={() => exporter.mutate(run.id, { onSuccess: (j) => setJobId(j.id) })}
        >
          {info ? "Export again" : "Export to ONNX"}
        </Button>
        {info && (
          <Button
            size="sm"
            variant="ghost"
            icon={<Download />}
            loading={downloading}
            onClick={async () => {
              setDownloading(true);
              try {
                await downloadOnnx(run);
              } finally {
                setDownloading(false);
              }
            }}
          >
            Download ONNX
          </Button>
        )}
      </div>
    </div>
  );
}

/** One run: progress, controls, live charts, the latest sample, and publishing. */
export function RunDetail({ detail }: { detail: ForgeRunDetail }) {
  const { run, metrics } = detail;
  const control = useRunControl();
  const remove = useDeleteRun();
  const [armed, setArmed] = useState(false);
  const live = run.state === "queued" || run.state === "running";
  const train = useMemo(
    () =>
      metrics
        .filter((m) => m.kind === "train" && m.loss !== null)
        .map((m) => ({ x: m.step, y: m.loss as number })),
    [metrics],
  );
  const val = useMemo(
    () =>
      metrics
        .filter((m) => m.kind === "val" && m.psnr !== null)
        .map((m) => ({ x: m.step, y: m.psnr as number })),
    [metrics],
  );
  const valRows = metrics.filter((m) => m.kind === "val");
  const gain = run.best_psnr !== null && run.bicubic_psnr !== null ? run.best_psnr - run.bicubic_psnr : null;
  const act = (action: "pause" | "resume" | "stop") => control.mutate({ id: run.id, action });

  return (
    <div className="grid gap-4" data-testid="forge-run">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="font-display text-[16px] font-medium">
          {run.project_name} <span className="font-mono text-[13px] text-fg-2">×{run.scale}</span>
        </h2>
        {live && run.paused ? <Chip icon={<Pause />}>Paused</Chip> : <JobStateChip state={run.state} />}
        <span className="text-[11.5px] text-muted">
          {run.started_at ? `${formatDuration(run.started_at, run.finished_at)}` : "Waiting for the GPU"}
          {run.device && ` · ${run.device}`}
        </span>
        <span className="flex-1" />
        {live && (
          <>
            {run.paused ? (
              <Button size="sm" icon={<Play />} onClick={() => act("resume")} loading={control.isPending}>
                Resume
              </Button>
            ) : (
              <Button size="sm" icon={<Pause />} onClick={() => act("pause")} loading={control.isPending}>
                Pause
              </Button>
            )}
            <Button
              size="sm"
              icon={<Square />}
              onClick={() => act("stop")}
              disabled={control.isPending}
              title="Finish now and keep the best checkpoint"
            >
              Stop
            </Button>
          </>
        )}
        {!live && (
          <Button
            size="sm"
            variant="danger"
            icon={<Trash2 />}
            loading={remove.isPending}
            onBlur={() => setArmed(false)}
            onClick={() => (armed ? remove.mutate(run.id) : setArmed(true))}
            aria-label={armed ? "Confirm deleting this run" : "Delete this run"}
          >
            <span className={clsx(!armed && "max-md:sr-only")}>{armed ? "Delete run?" : "Delete"}</span>
          </Button>
        )}
      </header>
      {control.error && (
        <p role="alert" className="text-[12px] text-err">
          {errorMessage(control.error).message}
        </p>
      )}
      <div className="grid gap-1.5">
        <ProgressBar value={run.step / Math.max(1, run.total_steps)} tone="gold" label="Training progress" />
        <span className="font-mono text-[11.5px] text-fg-2">
          Step {run.step.toLocaleString()} of {run.total_steps.toLocaleString()}
        </span>
      </div>
      {run.error && (
        <p
          role="alert"
          className="flex items-start gap-1.5 rounded-lg border border-err/45 bg-err-soft p-2.5 text-[12px] text-err"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          {String(run.error.message ?? "Training stopped with an error.")}
        </p>
      )}
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="Best PSNR"
          value={run.best_psnr !== null ? `${run.best_psnr.toFixed(2)} dB` : "—"}
          sub={run.best_step !== null ? `at step ${run.best_step.toLocaleString()}` : "after the first check"}
        />
        <Stat
          label="Versus bicubic"
          value={gain !== null ? `${gain >= 0 ? "+" : ""}${gain.toFixed(2)} dB` : "—"}
          sub={run.bicubic_psnr !== null ? `bicubic ${run.bicubic_psnr.toFixed(2)} dB` : undefined}
        />
        <Stat label="Best SSIM" value={run.best_ssim !== null ? run.best_ssim.toFixed(4) : "—"} />
        <Stat
          label="Batch"
          value={String(run.batch)}
          sub={run.accumulate > 1 ? `× ${run.accumulate} accumulated (memory)` : undefined}
        />
      </dl>
      {run.notes.length > 0 && (
        <ul className="grid gap-1 text-[12px] text-fg-2" aria-label="Notes">
          {run.notes.map((note) => (
            <li key={note} className="flex items-start gap-1.5">
              <Info className="mt-0.5 size-3.5 shrink-0 text-cyan" aria-hidden="true" />
              {note}
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <LineChart
          title="Training loss (log scale)"
          points={train}
          log
          xMax={run.total_steps}
          format={(v) => (v < 0.01 ? v.toExponential(1) : v.toFixed(3))}
          emptyText={live ? "The first points arrive within a minute" : "No training points"}
        />
        <LineChart
          title="PSNR on held-out crops (dB)"
          points={val}
          xMax={run.total_steps}
          markers
          format={(v) => v.toFixed(2)}
          reference={
            run.bicubic_psnr !== null
              ? { y: run.bicubic_psnr, label: `bicubic ${run.bicubic_psnr.toFixed(2)}` }
              : undefined
          }
          emptyText={`First check at step ${(run.settings?.val_every ?? 500).toLocaleString()}`}
        />
      </div>
      {valRows.length > 0 && (
        <details className="text-[12px]">
          <summary className="cursor-pointer text-fg-2 hover:text-fg">Checks as a table</summary>
          <table className="mt-2 w-full max-w-[420px] text-left tabular-nums">
            <thead className="text-muted">
              <tr>
                <th className="py-1 font-normal">Step</th>
                <th className="py-1 text-right font-normal">PSNR (dB)</th>
                <th className="py-1 text-right font-normal">SSIM</th>
              </tr>
            </thead>
            <tbody>
              {valRows.map((m) => (
                <tr key={m.step} className="border-t border-line">
                  <td className="py-1">{m.step.toLocaleString()}</td>
                  <td className="py-1 text-right">{m.psnr?.toFixed(2) ?? "—"}</td>
                  <td className="py-1 text-right">{m.ssim?.toFixed(4) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {run.sample_url && (
        <figure className="grid gap-1.5">
          <figcaption className="text-[12.5px] font-semibold text-fg">
            Best checkpoint on a held-out crop: bicubic, this model, the original
          </figcaption>
          <img
            src={`${run.sample_url}?step=${run.best_step ?? 0}`}
            alt={`Bicubic, the model at step ${run.best_step ?? 0}, and the original, side by side`}
            className="w-full max-w-[720px] rounded-lg border border-line [image-rendering:pixelated]"
            data-testid="forge-sample"
          />
        </figure>
      )}
      {run.best_step !== null && <PublishPanel key={run.id} run={run} />}
    </div>
  );
}
