import { clsx } from "clsx";
import { formatPercent, usageSeverity } from "@/lib/format";

const fill = { ok: "bg-cyan", warn: "bg-warn", err: "bg-err" } as const;
// Track is a lighter step of the same hue as the fill, so state reads across the whole bar.
const track = {
  ok: "bg-[var(--cyan-track)]",
  warn: "bg-[var(--warn-track)]",
  err: "bg-[var(--err-track)]",
} as const;

/**
 * Usage meter. The fill colour carries severity (cyan, then warn at 70%, then err at 90%);
 * the label and value stay in text colours.
 */
export function Meter({
  label,
  used,
  total,
  detail,
  className,
}: {
  label: string;
  used: number;
  total: number;
  detail?: string;
  className?: string;
}) {
  const fraction = total > 0 ? Math.min(1, Math.max(0, used / total)) : 0;
  const severity = usageSeverity(fraction);
  return (
    <div className={clsx("grid gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
        <span className="text-fg-2">{label}</span>
        <span className="font-mono text-[11.5px] text-muted tabular-nums">
          {detail ?? formatPercent(fraction)}
        </span>
      </div>
      {/* biome-ignore lint/a11y/useSemanticElements: native <meter> can't take the severity track styling */}
      <div
        className={clsx("h-1.5 overflow-hidden rounded-full", track[severity])}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(fraction * 100)}
        title={`${label}: ${formatPercent(fraction)}`}
      >
        <div
          className={clsx("h-full rounded-full transition-[width]", fill[severity])}
          style={{ width: `${fraction * 100}%` }}
        />
      </div>
    </div>
  );
}
