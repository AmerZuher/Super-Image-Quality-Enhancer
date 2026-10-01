import { clsx } from "clsx";

export function ProgressBar({
  value,
  label,
  tone = "cyan",
  className,
}: {
  value: number;
  label: string;
  tone?: "cyan" | "gold";
  className?: string;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div
      className={clsx("h-1.5 overflow-hidden rounded-full bg-[var(--cyan-track)]", className)}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
    >
      <div
        className={clsx(
          "h-full rounded-full transition-[width] duration-300",
          tone === "gold" ? "bg-gold" : "bg-cyan",
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
