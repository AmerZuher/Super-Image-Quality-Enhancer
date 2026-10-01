import { clsx } from "clsx";
import type { ReactNode } from "react";

export type Tone = "neutral" | "cyan" | "gold" | "ok" | "warn" | "err";

const tones: Record<Tone, string> = {
  neutral: "border-line-2 text-fg-2 bg-transparent",
  cyan: "border-cyan/40 text-cyan bg-cyan-soft",
  gold: "border-gold/45 text-gold bg-gold-soft",
  ok: "border-ok/40 text-ok bg-ok-soft",
  warn: "border-warn/40 text-warn bg-warn-soft",
  err: "border-err/45 text-err bg-err-soft",
};

export function Chip({
  tone = "neutral",
  icon,
  children,
  className,
}: {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11.5px] font-medium [&_svg]:size-3.5",
        tones[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}
