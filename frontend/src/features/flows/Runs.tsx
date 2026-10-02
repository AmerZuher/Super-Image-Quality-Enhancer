import { clsx } from "clsx";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Download,
  FileImage,
  FlaskConical,
  FolderInput,
  MinusCircle,
  XCircle,
} from "lucide-react";
import type { ReactNode } from "react";
import { buttonClasses } from "@/components/ui/Button";
import { Chip, type Tone } from "@/components/ui/Chip";
import { CopyCommand } from "@/components/ui/CopyCommand";
import { JobStateChip } from "@/components/ui/JobStateChip";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Spinner } from "@/components/ui/Spinner";
import type { FlowRun, FlowRunDetail, FlowRunItem } from "@/lib/api/client";
import { formatDuration, relativeTime } from "@/lib/format";

const ITEM_STATE: Record<FlowRunItem["state"], { tone: Tone; label: string; icon: ReactNode }> = {
  pending: { tone: "neutral", label: "Waiting", icon: <CircleDashed /> },
  running: { tone: "cyan", label: "Working", icon: <Spinner className="size-3.5" /> },
  done: { tone: "ok", label: "Done", icon: <CheckCircle2 /> },
  failed: { tone: "err", label: "Failed", icon: <XCircle /> },
  skipped: { tone: "neutral", label: "Stopped early", icon: <MinusCircle /> },
};

function finished(run: FlowRun): number {
  return run.done + run.failed + run.skipped;
}

export function RunSummary({ run }: { run: FlowRun }) {
  return (
    <span className="text-[12px] text-fg-2">
      {finished(run).toLocaleString()} of {run.total.toLocaleString()} finished
      {run.failed > 0 && <span className="text-err"> · {run.failed.toLocaleString()} failed</span>}
      {run.skipped > 0 && <> · {run.skipped.toLocaleString()} stopped early</>}
    </span>
  );
}

export function RunList({
  runs,
  current,
  onPick,
}: {
  runs: FlowRun[];
  current: string | undefined;
  onPick: (id: string) => void;
}) {
  if (runs.length === 0) {
    return <p className="text-[12.5px] text-muted">No runs yet. Use Run to try the flow on some images.</p>;
  }
  return (
    <ul className="grid gap-1.5" aria-label="Runs">
      {runs.map((run) => (
        <li key={run.id}>
          <button
            type="button"
            onClick={() => onPick(run.id)}
            aria-current={current === run.id ? "true" : undefined}
            className={clsx(
              "grid w-full gap-1 rounded-lg border px-2.5 py-2 text-left transition",
              current === run.id
                ? "border-cyan bg-cyan-soft"
                : "border-line hover:border-line-2 hover:bg-panel-2",
            )}
          >
            <span className="flex flex-wrap items-center gap-1.5">
              <JobStateChip state={run.state} />
              {run.dry_run && (
                <Chip icon={<FlaskConical />} tone="cyan">
                  Dry run
                </Chip>
              )}
              {run.kind === "watch" && <Chip icon={<FolderInput />}>From folder</Chip>}
              <span className="ml-auto text-[11.5px] text-muted">{relativeTime(run.created_at)}</span>
            </span>
            <RunSummary run={run} />
            {(run.state === "running" || run.state === "queued") && (
              <ProgressBar value={finished(run) / Math.max(1, run.total)} label="Run progress" />
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

function ItemRow({ item, runId }: { item: FlowRunItem; runId: string }) {
  const state = ITEM_STATE[item.state];
  const error = item.error as { message?: string; fix?: string; code?: string } | null;
  const exports = item.outputs.filter((o) => o.kind === "export");
  const others = item.outputs.filter((o) => o.kind !== "export");
  return (
    <li className="grid grid-cols-[48px_1fr] gap-3 px-3 py-2.5" data-testid="run-item">
      {item.thumb_url ? (
        <img
          src={item.thumb_url}
          alt=""
          className="size-12 rounded-md border border-line object-cover"
          loading="lazy"
        />
      ) : (
        <span className="grid size-12 place-items-center rounded-md border border-line text-muted">
          <FileImage className="size-5" aria-hidden="true" />
        </span>
      )}
      <div className="grid min-w-0 gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">{item.name}</span>
          <Chip tone={state.tone} icon={state.icon}>
            {state.label}
          </Chip>
        </div>
        {item.steps.length > 0 && (
          <ol className="flex flex-wrap gap-x-1.5 gap-y-0.5 text-[11px] text-fg-2" aria-label="Steps">
            {item.steps.map((step) => (
              <li
                key={`${String(step.node)}@${String(step.key)}`}
                className="after:ml-1.5 after:text-muted after:content-['→'] last:after:content-none"
              >
                {String(step.label ?? step.node)}
                {typeof step.ms === "number" && <span className="text-muted"> {formatMs(step.ms)}</span>}
                {typeof step.note === "string" && step.note && (
                  <span className="text-muted"> ({step.note})</span>
                )}
              </li>
            ))}
          </ol>
        )}
        {exports.length > 0 && (
          <ul className="flex flex-wrap gap-1.5">
            {exports.map((out) => (
              <li key={String(out.path)}>
                <a
                  href={`/api/flows/runs/${runId}/files/${encodeURI(String(out.path))}`}
                  className="inline-flex items-center gap-1 font-mono text-[11px] text-cyan hover:underline"
                  download
                >
                  <Download className="size-3" aria-hidden="true" />
                  {String(out.path).split("/").slice(-2).join("/")}
                </a>
              </li>
            ))}
          </ul>
        )}
        {others.length > 0 && (
          <span className="text-[11px] text-fg-2">{others.map(describeOutput).join(" · ")}</span>
        )}
        {error && (
          <p className="flex items-start gap-1.5 text-[11.5px] text-err" role="note">
            <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
            <span>
              {error.message}
              {error.fix && <span className="text-fg-2"> {error.fix}</span>}
            </span>
          </p>
        )}
      </div>
    </li>
  );
}

function describeOutput(o: Record<string, unknown>): string {
  switch (o.kind) {
    case "tag":
      return `Tagged ${((o.tags as string[] | undefined) ?? []).join(", ")}`;
    case "album":
      return `Added to ${String(o.album)}`;
    case "asset":
      return o.duplicate ? "Already in the Library" : `Saved to the Library as ${String(o.name)}`;
    case "quarantine":
      return "Moved to quarantine";
    case "dry_run":
      return `${String(o.would)} (simulated)`;
    default:
      return String(o.kind);
  }
}

function formatMs(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function RunDetail({ detail }: { detail: FlowRunDetail }) {
  const { run, items } = detail;
  const going = run.state === "queued" || run.state === "running";
  return (
    <section className="grid gap-3" aria-label="Run results">
      <div className="grid gap-2 rounded-lg border border-line bg-panel-2 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <JobStateChip state={run.state} />
          {run.dry_run && (
            <Chip icon={<FlaskConical />} tone="cyan">
              Dry run
            </Chip>
          )}
          <RunSummary run={run} />
          <span className="ml-auto text-[11.5px] text-muted">
            {run.started_at ? `took ${formatDuration(run.started_at, run.finished_at)}` : "starting…"}
          </span>
        </div>
        {going && <ProgressBar value={finished(run) / Math.max(1, run.total)} label="Run progress" />}
        <div className="grid gap-1 text-[12px] text-fg-2">
          Exported files are in
          <CopyCommand command={detail.output_folder} label="output folder" />
        </div>
        {run.download_url && (
          <a
            href={run.download_url}
            className={buttonClasses("outline", "sm", "justify-self-start")}
            download
          >
            <Download />
            Download exported files (.zip)
          </a>
        )}
      </div>
      <ul className="divide-y divide-line rounded-lg border border-line" aria-label="Images in this run">
        {items.map((item) => (
          <ItemRow key={item.id} item={item} runId={run.id} />
        ))}
      </ul>
      {items.length < run.total && (
        <p className="text-[11.5px] text-muted">Showing the first {items.length.toLocaleString()} images.</p>
      )}
    </section>
  );
}
