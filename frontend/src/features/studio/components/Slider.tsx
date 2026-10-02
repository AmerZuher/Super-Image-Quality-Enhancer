import { type CSSProperties, useId } from "react";
import type { OpParam } from "@/lib/api/client";
import { formatParam } from "../format";

/** One labelled range input. Double-click the label or value to reset it. */
export function Slider({
  label,
  param,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  param: OpParam;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const pct = (v: number) => `${((v - param.min) / (param.max - param.min)) * 100}%`;
  const changed = value !== param.default;
  const reset = () => onChange(param.default);
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-x-2 py-1">
      <label
        htmlFor={id}
        onDoubleClick={reset}
        className="cursor-default truncate text-[12.5px] text-fg-2 select-none"
        title={`${label}. Double-click to reset.`}
      >
        {label}
      </label>
      <button
        type="button"
        onClick={reset}
        disabled={!changed}
        className="min-w-[52px] rounded px-1 text-right font-mono text-[11px] text-muted tabular-nums enabled:text-fg enabled:hover:bg-panel-2 disabled:cursor-default"
        aria-label={changed ? `Reset ${label}` : undefined}
        title={changed ? "Reset" : undefined}
      >
        {formatParam(param, value)}
      </button>
      <input
        id={id}
        type="range"
        className="range col-span-2"
        min={param.min}
        max={param.max}
        step={param.step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        style={{ "--from": pct(param.default), "--to": pct(value) } as CSSProperties}
      />
    </div>
  );
}
