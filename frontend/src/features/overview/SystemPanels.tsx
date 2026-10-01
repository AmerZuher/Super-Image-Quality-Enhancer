import { CheckCircle2, CircleAlert, Cpu, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Chip } from "@/components/ui/Chip";
import { CopyCommand } from "@/components/ui/CopyCommand";
import { Meter } from "@/components/ui/Meter";
import { Panel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";
import type { SystemStatus } from "@/lib/api/client";
import { useEventsStore } from "@/lib/events";
import { formatBytes, relativeTime } from "@/lib/format";
import { apiResources, gpuSummary, onlineWorker } from "@/lib/system";

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-panel-2/60 px-3 py-2">
      <div className="truncate text-[15px] font-semibold text-fg">{value}</div>
      <div className="text-[11.5px] text-muted">{label}</div>
    </div>
  );
}

export function GpuPanel({ system }: { system: SystemStatus | undefined }) {
  const { devices, torch, worker } = gpuSummary(system);
  const gpu = devices[0];

  if (!worker) {
    return (
      <Panel title="GPU" eyebrow="AI hardware">
        <p className="flex items-center gap-2 text-[13px] text-muted">
          <Spinner /> Waiting for the GPU worker to report in…
        </p>
      </Panel>
    );
  }

  if (!gpu && !torch?.cuda) {
    return (
      <Panel title="No GPU in use" eyebrow="AI hardware" actions={<Chip tone="warn">CPU only</Chip>}>
        <p className="mb-3 text-[13px] text-fg-2">
          AI tasks will run on the CPU, which works but is much slower. On a machine with an NVIDIA GPU, start
          the stack with the GPU override:
        </p>
        <CopyCommand
          label="GPU start command"
          command="docker compose -f compose.yaml -f compose.gpu.yaml up -d"
        />
        <p className="mt-2 text-[11.5px] text-muted">
          {torch?.available
            ? `PyTorch ${torch.version} is installed; CUDA is not available to it.`
            : "PyTorch is not installed in the GPU worker."}
        </p>
      </Panel>
    );
  }

  const used = gpu ? gpu.memory_used_bytes : 0;
  const total = gpu ? gpu.memory_total_bytes : 0;
  return (
    <Panel
      title={gpu?.name ?? "CUDA GPU"}
      eyebrow="AI hardware"
      actions={
        <Chip tone="ok" icon={<CheckCircle2 />}>
          Ready
        </Chip>
      }
    >
      {gpu && (
        <Meter
          className="mb-3"
          label="Video memory"
          used={used}
          total={total}
          detail={`${formatBytes(used)} of ${formatBytes(total)}`}
        />
      )}
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Temperature" value={gpu?.temperature_c != null ? `${gpu.temperature_c} °C` : "–"} />
        <Stat
          label="Utilisation"
          value={gpu?.utilization_percent != null ? `${gpu.utilization_percent}%` : "–"}
        />
        <Stat label="CUDA" value={torch?.cuda_version ?? "–"} />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {torch?.compute_capability && <Chip>Compute {torch.compute_capability}</Chip>}
        {torch?.bf16 && <Chip>bfloat16</Chip>}
        {gpu?.driver_version && <Chip>Driver {gpu.driver_version}</Chip>}
        {devices.length > 1 && <Chip tone="cyan">{devices.length} GPUs</Chip>}
      </div>
    </Panel>
  );
}

export function ResourcesPanel({ system }: { system: SystemStatus | undefined }) {
  const resources = apiResources(system);
  if (!resources) {
    return (
      <Panel title="This machine" eyebrow="Resources">
        <p className="text-[13px] text-muted">Loading…</p>
      </Panel>
    );
  }
  const { cpu, memory, disk } = resources;
  const usedMemory = memory.total_bytes - memory.available_bytes;
  const usedDisk = disk.total_bytes - disk.free_bytes;
  return (
    <Panel title="This machine" eyebrow="Resources">
      <div className="grid gap-3.5">
        <Meter
          label={memory.limited_by_container ? "Memory (container limit)" : "Memory"}
          used={usedMemory}
          total={memory.total_bytes}
          detail={`${formatBytes(usedMemory)} of ${formatBytes(memory.total_bytes)}`}
        />
        <Meter
          label="Data volume"
          used={usedDisk}
          total={disk.total_bytes}
          detail={`${formatBytes(disk.free_bytes)} free`}
        />
        <div className="flex items-center gap-2 text-[12.5px] text-fg-2">
          <Cpu className="size-4 text-muted" aria-hidden="true" />
          {cpu.usable_cores < cpu.logical_cores
            ? `${cpu.usable_cores} of ${cpu.logical_cores} CPU cores available`
            : `${cpu.logical_cores} CPU cores`}
        </div>
      </div>
    </Panel>
  );
}

function ServiceRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <li className="flex items-center gap-2.5 py-1.5">
      {ok ? (
        <CheckCircle2 className="size-4 text-ok" aria-hidden="true" />
      ) : (
        <XCircle className="size-4 text-err" aria-hidden="true" />
      )}
      <span className="flex-1 text-[13px] text-fg">{label}</span>
      <span className={ok ? "text-[12px] text-muted" : "text-[12px] text-err"}>{detail}</span>
    </li>
  );
}

export function ServicesPanel({ system }: { system: SystemStatus | undefined }) {
  const live = useEventsStore((s) => s.status === "open");
  const cpu = onlineWorker(system, "cpu");
  const gpu = onlineWorker(system, "gpu");
  if (!system) {
    return (
      <Panel title="Services" eyebrow="Health">
        <p className="text-[13px] text-muted">Loading…</p>
      </Panel>
    );
  }
  return (
    <Panel title="Services" eyebrow="Health">
      <ul className="divide-y divide-line">
        <ServiceRow
          label="Database"
          ok={system.services.database}
          detail={system.services.database ? "Online" : "Offline"}
        />
        <ServiceRow
          label="Job engine"
          ok={system.services.temporal}
          detail={system.services.temporal ? "Online" : "Unreachable"}
        />
        <ServiceRow label="Live updates" ok={live} detail={live ? "Connected" : "Polling"} />
        <ServiceRow
          label="CPU worker"
          ok={Boolean(cpu?.online)}
          detail={
            cpu
              ? cpu.online
                ? `Seen ${relativeTime(cpu.last_seen)}`
                : `Offline since ${relativeTime(cpu.last_seen)}`
              : "Not started"
          }
        />
        <ServiceRow
          label="GPU worker"
          ok={Boolean(gpu?.online)}
          detail={
            gpu
              ? gpu.online
                ? `Seen ${relativeTime(gpu.last_seen)}`
                : `Offline since ${relativeTime(gpu.last_seen)}`
              : "Not started"
          }
        />
      </ul>
    </Panel>
  );
}

export function attentionCount(system: SystemStatus | undefined, live: boolean): number {
  if (!system) return 0;
  const checks = [
    system.services.database,
    system.services.temporal,
    live,
    Boolean(onlineWorker(system, "cpu")?.online),
    Boolean(onlineWorker(system, "gpu")?.online),
  ];
  return checks.filter((ok) => !ok).length;
}

export function AttentionIcon({ count }: { count: number }) {
  return count ? (
    <CircleAlert className="size-5 text-warn" aria-hidden="true" />
  ) : (
    <CheckCircle2 className="size-5 text-ok" aria-hidden="true" />
  );
}
