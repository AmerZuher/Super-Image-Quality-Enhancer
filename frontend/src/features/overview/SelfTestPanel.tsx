import { Play, Square, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { JobStateChip } from "@/components/ui/JobStateChip";
import { Panel } from "@/components/ui/Panel";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { errorMessage, type Job } from "@/lib/api/client";
import { useCancelJob, useJobs, useStartSelfTest } from "@/lib/api/queries";
import { formatDuration, relativeTime } from "@/lib/format";

interface Benchmark {
  size: number;
  dtype?: string;
  tflops?: number;
  status?: string;
}

interface SelfTestResult {
  cpu?: { imaging?: { libvips: string; blur_megapixels: number; seconds: number } };
  gpu?: { device?: string; device_name?: string; peak_tflops?: number; benchmarks?: Benchmark[] };
}

/**
 * Single-series bar chart: matrix-multiply throughput per matrix size. Bars grow from one
 * baseline, cap at 10px thick with a rounded data end; values sit at the bar tips in text
 * colours, and each row has a hover tooltip.
 */
export function ThroughputChart({ benchmarks, device }: { benchmarks: Benchmark[]; device: string }) {
  const rows = benchmarks.filter((b) => typeof b.tflops === "number");
  if (!rows.length) return null;
  const max = Math.max(...rows.map((b) => b.tflops ?? 0));
  const dtype = rows[0]?.dtype === "float16" ? "FP16" : "FP32";
  return (
    <figure className="grid gap-2">
      <figcaption className="text-[12px] text-muted">
        Matrix-multiply throughput on {device}, {dtype}, in TFLOPS (higher is better)
      </figcaption>
      <ul className="grid gap-1.5">
        {rows.map((b) => (
          <li
            key={b.size}
            className="grid grid-cols-[64px_1fr_76px] items-center gap-3"
            title={`${b.size} × ${b.size}: ${b.tflops?.toFixed(2)} TFLOPS`}
          >
            <span className="font-mono text-[11.5px] text-muted tabular-nums">
              {b.size.toLocaleString()}²
            </span>
            <div className="h-2.5">
              <div
                className="h-full rounded-r-[4px] bg-cyan"
                style={{ width: `${Math.max(2, ((b.tflops ?? 0) / max) * 100)}%` }}
              />
            </div>
            <span className="text-right font-mono text-[11.5px] text-fg-2 tabular-nums">
              {b.tflops?.toFixed(1)}
            </span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

function Results({ job }: { job: Job }) {
  const result = (job.result ?? {}) as SelfTestResult;
  const imaging = result.cpu?.imaging;
  const gpu = result.gpu;
  const device = gpu?.device_name ?? (gpu?.device === "cpu" ? "CPU (PyTorch)" : "no GPU");
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-line bg-panel-2/60 px-3 py-2">
          <div className="text-[15px] font-semibold text-fg">
            {imaging ? `${imaging.blur_megapixels} MP in ${imaging.seconds} s` : "–"}
          </div>
          <div className="text-[11.5px] text-muted">Image engine (libvips {imaging?.libvips ?? "?"})</div>
        </div>
        <div className="rounded-lg border border-line bg-panel-2/60 px-3 py-2">
          <div className="text-[15px] font-semibold text-fg">
            {gpu?.peak_tflops ? `${gpu.peak_tflops.toFixed(1)} TFLOPS` : "Skipped"}
          </div>
          <div className="truncate text-[11.5px] text-muted">Peak compute · {device}</div>
        </div>
      </div>
      {gpu?.benchmarks && <ThroughputChart benchmarks={gpu.benchmarks} device={device} />}
    </div>
  );
}

export function SelfTestPanel() {
  const { data: jobs } = useJobs();
  const start = useStartSelfTest();
  const cancel = useCancelJob();
  const job = (jobs ?? []).find((j) => j.kind === "system.self_test");
  const active = job && (job.state === "queued" || job.state === "running");
  const startError = start.error ? errorMessage(start.error) : null;

  return (
    <Panel
      title="System self-test"
      eyebrow="Pipeline check"
      actions={
        active ? (
          <Button
            size="sm"
            variant="danger"
            icon={<Square />}
            onClick={() => cancel.mutate(job.id)}
            loading={cancel.isPending}
          >
            Cancel
          </Button>
        ) : (
          <Button
            size="sm"
            variant="primary"
            icon={<Play />}
            onClick={() => start.mutate()}
            loading={start.isPending}
          >
            {job ? "Run again" : "Run self-test"}
          </Button>
        )
      }
    >
      <p className="mb-3 text-[13px] text-fg-2">
        Sends a job through the API, the job engine, the CPU worker and the GPU worker, and measures how fast
        your hardware is.
      </p>

      {startError && (
        <div
          className="mb-3 flex gap-2 rounded-lg border border-err/40 bg-err-soft px-3 py-2 text-[12.5px] text-fg-2"
          role="alert"
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-err" aria-hidden="true" />
          <span>
            {startError.message}
            {startError.fix && <span className="block text-muted">{startError.fix}</span>}
          </span>
        </div>
      )}

      {!job && !startError && <p className="text-[12.5px] text-muted">No self-test has run yet.</p>}

      {job && (
        <div className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
            <JobStateChip state={job.state} />
            <span>Started {relativeTime(job.created_at)}</span>
            {job.finished_at && (
              <span>· took {formatDuration(job.started_at ?? job.created_at, job.finished_at)}</span>
            )}
          </div>
          {active && (
            <div className="grid gap-1.5">
              <ProgressBar value={job.progress} label="Self-test progress" />
              <span className="text-[12.5px] text-fg-2">{job.message || "Waiting for a worker…"}</span>
            </div>
          )}
          {job.state === "failed" && (
            <p className="text-[12.5px] text-err">
              {(job.error as { message?: string } | null)?.message ?? job.message}
            </p>
          )}
          {job.state === "succeeded" && <Results job={job} />}
        </div>
      )}
    </Panel>
  );
}
