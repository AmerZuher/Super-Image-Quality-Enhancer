import type { SystemStatus, Worker } from "./api/client";

export interface GpuDevice {
  index: number;
  name: string;
  memory_total_bytes: number;
  memory_used_bytes: number;
  memory_free_bytes: number;
  utilization_percent: number | null;
  temperature_c: number | null;
  driver_version: string;
}

export interface TorchRuntime {
  available: boolean;
  cuda: boolean;
  version?: string;
  cuda_version?: string | null;
  bf16?: boolean;
  compute_capability?: string;
}

export interface ResourceSnapshot {
  cpu: { logical_cores: number; usable_cores: number; load_percent: number };
  memory: { total_bytes: number; available_bytes: number; limited_by_container: boolean };
  disk: { path: string; total_bytes: number; free_bytes: number; free_ratio: number };
}

export function onlineWorker(system: SystemStatus | undefined, kind: "cpu" | "gpu"): Worker | undefined {
  const candidates = (system?.workers ?? []).filter((w) => w.kind === kind);
  return candidates.find((w) => w.online) ?? candidates[0];
}

export function gpuSummary(system: SystemStatus | undefined): {
  worker?: Worker;
  devices: GpuDevice[];
  torch?: TorchRuntime;
} {
  const worker = onlineWorker(system, "gpu");
  const info = (worker?.info ?? {}) as { gpus?: GpuDevice[]; torch?: TorchRuntime };
  return { worker, devices: info.gpus ?? [], torch: info.torch };
}

export function apiResources(system: SystemStatus | undefined): ResourceSnapshot | undefined {
  return system?.api as ResourceSnapshot | undefined;
}
