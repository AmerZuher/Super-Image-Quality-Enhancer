import { Link, useRouterState } from "@tanstack/react-router";
import { clsx } from "clsx";
import { ArrowUpCircle, Cpu, Search } from "lucide-react";
import { Kbd } from "@/components/ui/Kbd";
import { Spinner } from "@/components/ui/Spinner";
import { useJobs, useSystem, useUpdates } from "@/lib/api/queries";
import { useEventsStore } from "@/lib/events";
import { formatBytes } from "@/lib/format";
import { gpuSummary } from "@/lib/system";
import { useUi } from "@/lib/ui-store";
import { OVERVIEW, workspaceByPath } from "../workspaces";

const EXTRA_TITLES: Record<string, string> = { "/jobs": "Jobs", "/settings": "Settings" };

function useTitle(): string {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  if (pathname === "/") return OVERVIEW.label;
  return workspaceByPath(pathname)?.label ?? EXTRA_TITLES[pathname] ?? "SIQE Studio";
}

function DeviceChip() {
  const { data } = useSystem();
  const { devices, torch, worker } = gpuSummary(data);
  const gpu = devices[0];
  const label = gpu
    ? `${gpu.name.replace(/^NVIDIA (GeForce )?/, "")} · ${formatBytes(gpu.memory_free_bytes)} free`
    : worker?.online
      ? torch?.cuda
        ? "GPU ready"
        : "CPU only"
      : "GPU worker offline";
  const tone = gpu || torch?.cuda ? "text-ok" : worker?.online ? "text-warn" : "text-err";
  return (
    <Link
      to="/"
      className="hidden items-center gap-2 rounded-full border border-line-2 px-2.5 py-1 text-[11.5px] text-fg-2 hover:border-cyan lg:flex"
      title="Hardware status"
    >
      <Cpu className={clsx("size-3.5", tone)} aria-hidden="true" />
      {label}
    </Link>
  );
}

function RunningJobs() {
  const { data } = useJobs();
  const running = (data ?? []).filter((j) => j.state === "running" || j.state === "queued").length;
  if (!running) return null;
  return (
    <Link
      to="/jobs"
      className="flex items-center gap-1.5 rounded-full bg-cyan-soft px-2.5 py-1 text-[11.5px] font-medium text-cyan"
      title="Jobs in progress"
    >
      <Spinner className="size-3.5" />
      {running} running
    </Link>
  );
}

function UpdatesButton() {
  const { data } = useUpdates();
  const open = useUi((s) => s.setUpdatesOpen);
  const available = data?.update_available;
  return (
    <button
      type="button"
      onClick={() => open(true)}
      className={clsx(
        "relative flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition",
        available
          ? "border-cyan/50 bg-cyan-soft text-cyan hover:border-cyan"
          : "border-line-2 text-fg-2 hover:border-cyan hover:text-fg",
      )}
      aria-label={
        available ? `Update available: version ${data?.latest_version}` : "Updates and release notes"
      }
    >
      <ArrowUpCircle className="size-3.5" aria-hidden="true" />
      {available ? `v${data?.latest_version} available` : `v${data?.current_version ?? "…"}`}
      {available && (
        <span
          className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-cyan ring-2 ring-panel"
          aria-hidden="true"
        />
      )}
    </button>
  );
}

function LiveIndicator() {
  const status = useEventsStore((s) => s.status);
  const since = useEventsStore((s) => s.since);
  // Brief reconnects are normal; only mention it once the link has been down for a while.
  if (status === "open" || Date.now() - since < 4000) return null;
  return (
    <span className="hidden items-center gap-1.5 text-[11.5px] text-warn sm:flex" role="status">
      <span className="size-1.5 rounded-full bg-warn" aria-hidden="true" />
      Reconnecting live updates
    </span>
  );
}

export function TopBar() {
  const title = useTitle();
  const openPalette = useUi((s) => s.setPaletteOpen);
  return (
    <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-line bg-panel px-4">
      <h1 className="min-w-0 truncate text-[14px] font-semibold">{title}</h1>
      <button
        type="button"
        onClick={() => openPalette(true)}
        className="ml-auto flex h-8 min-w-0 items-center gap-2 rounded-lg border border-line bg-bg px-2.5 text-muted transition hover:border-line-2 hover:text-fg-2 md:w-[320px]"
        aria-label="Open command palette"
      >
        <Search className="size-3.5 shrink-0" aria-hidden="true" />
        <span className="hidden flex-1 truncate text-left text-[12.5px] md:block">
          Search pages and actions…
        </span>
        <span className="hidden md:inline">
          <Kbd>Ctrl K</Kbd>
        </span>
      </button>
      <LiveIndicator />
      <RunningJobs />
      <DeviceChip />
      <UpdatesButton />
    </header>
  );
}
