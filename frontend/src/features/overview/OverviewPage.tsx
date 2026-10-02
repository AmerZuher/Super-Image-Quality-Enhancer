import { Link } from "@tanstack/react-router";
import { clsx } from "clsx";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { Chip } from "@/components/ui/Chip";
import { JobStateChip } from "@/components/ui/JobStateChip";
import { Panel } from "@/components/ui/Panel";
import { useJobs, useSystem } from "@/lib/api/queries";
import { useEventsStore } from "@/lib/events";
import { relativeTime } from "@/lib/format";
import { isAvailable, WORKSPACES } from "../../app/workspaces";
import { SelfTestPanel } from "./SelfTestPanel";
import { AttentionIcon, attentionCount, GpuPanel, ResourcesPanel, ServicesPanel } from "./SystemPanels";

function RecentJobs() {
  const { data, isLoading } = useJobs();
  const jobs = (data ?? []).slice(0, 6);
  return (
    <Panel
      title="Recent jobs"
      eyebrow="Activity"
      actions={
        <Link to="/jobs" className="flex items-center gap-1 text-[12px] text-cyan hover:underline">
          All jobs <ArrowRight className="size-3.5" aria-hidden="true" />
        </Link>
      }
    >
      {isLoading ? (
        <p className="text-[13px] text-muted">Loading…</p>
      ) : jobs.length === 0 ? (
        <p className="text-[13px] text-muted">
          Nothing has run yet. Jobs you start in any workspace appear here with live progress.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {jobs.map((job) => (
            <li key={job.id} className="flex items-center gap-3 py-2">
              <JobStateChip state={job.state} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] text-fg">{job.title}</div>
                <div className="truncate text-[11.5px] text-muted">{job.message}</div>
              </div>
              <span className="shrink-0 text-[11.5px] text-muted">{relativeTime(job.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function WorkspaceCards() {
  return (
    <section aria-labelledby="ws-heading" className="grid gap-3">
      <h2 id="ws-heading" className="eyebrow">
        Workspaces
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {WORKSPACES.map((w) => (
          <Link
            key={w.id}
            to={w.path}
            className="group grid min-w-0 gap-2 rounded-xl border border-line bg-panel p-4 transition hover:border-line-2"
          >
            <div className="flex items-center justify-between">
              <span
                className={clsx(
                  "grid size-9 place-items-center rounded-[10px]",
                  w.ai ? "bg-gold-soft text-gold" : "bg-cyan-soft text-cyan",
                )}
              >
                <w.icon className="size-[18px]" />
              </span>
              {isAvailable(w) ? (
                <Chip tone="ok" icon={<CheckCircle2 />}>
                  Ready
                </Chip>
              ) : (
                <Chip>Phase {w.phase}</Chip>
              )}
            </div>
            <h3 className="font-display text-[15px] font-medium text-fg">{w.label}</h3>
            <p className="text-[12.5px] text-fg-2">{w.summary}</p>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function OverviewPage() {
  const { data: system } = useSystem();
  const live = useEventsStore((s) => s.status === "open");
  const issues = attentionCount(system, live);
  return (
    <div className="mx-auto grid max-w-[1400px] gap-5 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow mb-1">SIQE Studio {system ? `v${system.version}` : ""}</div>
          <h2 className="flex items-center gap-2.5 font-display text-[22px] font-medium text-fg md:text-[26px]">
            <AttentionIcon count={issues} />
            {!system
              ? "Connecting…"
              : issues === 0
                ? "Everything is running"
                : `${issues} ${issues === 1 ? "thing needs" : "things need"} attention`}
          </h2>
        </div>
        <p className="max-w-[52ch] text-[13px] text-fg-2">
          Studio and AI Lab are ready: edit, upscale, denoise and cut out your images. The other workspaces
          arrive phase by phase; each card below says what's coming.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <GpuPanel system={system} />
        <ResourcesPanel system={system} />
        <ServicesPanel system={system} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SelfTestPanel />
        <RecentJobs />
      </div>

      <WorkspaceCards />
    </div>
  );
}
