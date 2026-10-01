const GiB = 1024 ** 3;
const MiB = 1024 ** 2;

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || Number.isNaN(bytes)) return "–";
  if (bytes >= 1024 * GiB) return `${(bytes / (1024 * GiB)).toFixed(1)} TB`;
  if (bytes >= GiB) return `${(bytes / GiB).toFixed(1)} GB`;
  if (bytes >= MiB) return `${Math.round(bytes / MiB)} MB`;
  return `${Math.max(0, Math.round(bytes / 1024))} KB`;
}

export function formatPercent(fraction: number): string {
  return `${Math.round(Math.max(0, Math.min(1, fraction)) * 100)}%`;
}

export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const seconds = Math.round((now - new Date(iso).getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds} s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}

export function formatDuration(startIso: string | null | undefined, endIso?: string | null): string {
  if (!startIso) return "–";
  const ms = (endIso ? new Date(endIso).getTime() : Date.now()) - new Date(startIso).getTime();
  if (ms < 1000) return `${Math.max(0, ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s % 60)} s`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Severity of a usage fraction, used by meters: under 70% is fine, 70–90% warn, above 90% critical. */
export function usageSeverity(fraction: number): "ok" | "warn" | "err" {
  if (fraction >= 0.9) return "err";
  if (fraction >= 0.7) return "warn";
  return "ok";
}
