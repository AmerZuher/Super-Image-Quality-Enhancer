import type { OpParam, OpSpec } from "@/lib/api/client";

/** Display a parameter value: signed for ranges that cross zero, with its unit. */
export function formatParam(param: OpParam, value: number): string {
  const decimals = param.step < 0.1 ? 2 : param.step < 1 ? 1 : 0;
  const text = value.toFixed(decimals);
  const signed = param.min < 0 && value > 0 ? `+${text}` : text;
  return param.unit ? `${signed} ${param.unit}` : signed;
}

/** Short summary of an op's values for the edit stack, for example "+0.50 EV" or "120 · 1.0 px". */
export function summarizeOp(spec: OpSpec, params: Record<string, number>): string {
  if (spec.params.length === 0) return "On";
  return spec.params.map((p) => formatParam(p, params[p.name] ?? p.default)).join(" · ");
}

export function formatDimensions(
  width: number | null | undefined,
  height: number | null | undefined,
): string {
  if (!width || !height) return "–";
  return `${width.toLocaleString()} × ${height.toLocaleString()}`;
}

export function megapixels(width: number, height: number): string {
  return `${((width * height) / 1e6).toFixed(1)} MP`;
}

const RATIOS: [number, string][] = [
  [1, "1:1"],
  [3 / 2, "3:2"],
  [2 / 3, "2:3"],
  [4 / 3, "4:3"],
  [3 / 4, "3:4"],
  [16 / 9, "16:9"],
  [9 / 16, "9:16"],
  [5 / 4, "5:4"],
  [4 / 5, "4:5"],
];

/** Name a pixel aspect ratio when it's close to a common one. */
export function aspectName(width: number, height: number): string | null {
  const ratio = width / height;
  for (const [value, name] of RATIOS) if (Math.abs(ratio - value) / value < 0.01) return name;
  return null;
}
