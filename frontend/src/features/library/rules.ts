import type { Rule, RuleSet } from "@/lib/api/client";

export type RuleField = Rule["field"];
export type RuleOp = Rule["op"];

interface FieldSpec {
  label: string;
  ops: RuleOp[];
  kind: "number" | "boolean" | "text" | "choice" | "date";
  unit?: string;
  choices?: string[];
  placeholder?: string;
}

export const COLORS = [
  "red",
  "orange",
  "yellow",
  "green",
  "teal",
  "blue",
  "purple",
  "pink",
  "neutral",
] as const;

export const FIELDS: Record<RuleField, FieldSpec> = {
  orientation: {
    label: "Orientation",
    ops: ["is", "is_not"],
    kind: "choice",
    choices: ["landscape", "portrait", "square"],
  },
  width: { label: "Width", ops: ["gte", "lte"], kind: "number", unit: "px" },
  height: { label: "Height", ops: ["gte", "lte"], kind: "number", unit: "px" },
  megapixels: { label: "Megapixels", ops: ["gte", "lte"], kind: "number", unit: "MP" },
  aspect: { label: "Aspect ratio (width ÷ height)", ops: ["gte", "lte", "approx"], kind: "number" },
  format: {
    label: "Format",
    ops: ["is", "is_not"],
    kind: "choice",
    choices: ["jpeg", "png", "webp", "heif", "tiff", "gif"],
  },
  color: { label: "Main colour", ops: ["is", "is_not"], kind: "choice", choices: [...COLORS] },
  tag: { label: "Tag", ops: ["has", "is_not"], kind: "text", placeholder: "lake" },
  sharpness: { label: "Sharpness (0 to 1)", ops: ["gte", "lte"], kind: "number" },
  has_gps: { label: "Has location", ops: ["is"], kind: "boolean" },
  ai_result: { label: "Made by AI Lab", ops: ["is"], kind: "boolean" },
  duplicate: { label: "Has duplicates", ops: ["is"], kind: "boolean" },
  taken: { label: "Date taken", ops: ["after", "before"], kind: "date" },
  added_days: { label: "Added in the last", ops: ["lte", "gte"], kind: "number", unit: "days" },
  name: { label: "File name", ops: ["contains"], kind: "text", placeholder: "IMG_" },
  folder: { label: "Import folder", ops: ["starts_with"], kind: "text", placeholder: "Trips/2024" },
};

export const OP_LABELS: Record<RuleOp, string> = {
  is: "is",
  is_not: "is not",
  gte: "at least",
  lte: "at most",
  approx: "about",
  has: "has",
  after: "on or after",
  before: "on or before",
  contains: "contains",
  starts_with: "starts with",
};

export function defaultRule(field: RuleField): Rule {
  const spec = FIELDS[field];
  const value =
    spec.kind === "boolean"
      ? true
      : spec.kind === "number"
        ? field === "aspect"
          ? 1.5
          : field === "sharpness"
            ? 0.3
            : field === "added_days"
              ? 7
              : field === "megapixels"
                ? 12
                : 1920
        : spec.kind === "date"
          ? new Date().toISOString().slice(0, 10)
          : spec.kind === "choice"
            ? (spec.choices?.[0] ?? "")
            : "";
  return { field, op: spec.ops[0] ?? "is", value };
}

/** A short, plain description of one rule, e.g. "Width at least 1,920 px". */
export function describeRule(rule: Rule): string {
  const spec = FIELDS[rule.field];
  if (spec.kind === "boolean") return rule.value ? spec.label : `Not: ${spec.label.toLowerCase()}`;
  if (rule.field === "orientation" || rule.field === "color" || rule.field === "format") {
    const value = String(rule.value);
    const nice = value.charAt(0).toUpperCase() + value.slice(1);
    return rule.op === "is_not" ? `Not ${value}` : nice;
  }
  if (rule.field === "added_days") {
    return rule.op === "lte" ? `Added in the last ${rule.value} days` : `Added over ${rule.value} days ago`;
  }
  const value = typeof rule.value === "number" ? rule.value.toLocaleString() : `“${String(rule.value)}”`;
  return `${spec.label.replace(/ \(.*\)$/, "")} ${OP_LABELS[rule.op]} ${value}${spec.unit ? ` ${spec.unit}` : ""}`;
}

export function sameRule(a: Rule, b: Rule): boolean {
  return a.field === b.field && a.op === b.op && a.value === b.value;
}

/** One-tap filters shown above the grid. */
export const QUICK_FILTERS: { label: string; rule: Rule }[] = [
  { label: "Landscape", rule: { field: "orientation", op: "is", value: "landscape" } },
  { label: "Portrait", rule: { field: "orientation", op: "is", value: "portrait" } },
  { label: "Square", rule: { field: "orientation", op: "is", value: "square" } },
  { label: "Low resolution", rule: { field: "width", op: "lte", value: 1000 } },
  { label: "Blurry", rule: { field: "sharpness", op: "lte", value: 0.3 } },
  { label: "Has location", rule: { field: "has_gps", op: "is", value: true } },
  { label: "AI results", rule: { field: "ai_result", op: "is", value: true } },
];

export function toggleRule(set: RuleSet, rule: Rule): RuleSet {
  const rules = set.rules ?? [];
  const exists = rules.some((r) => sameRule(r, rule));
  const next = exists
    ? rules.filter((r) => !sameRule(r, rule))
    : // One value per single-choice field: picking Portrait replaces Landscape.
      [...rules.filter((r) => !(r.field === rule.field && FIELDS[r.field].kind === "choice")), rule];
  return { match: set.match, rules: next };
}

export function hasRule(set: RuleSet, rule: Rule): boolean {
  return (set.rules ?? []).some((r) => sameRule(r, rule));
}

/** Coarse label for an image's shape, used on cards: what it would suit as a wallpaper. */
export function shapeLabel(width: number, height: number): "desktop" | "phone" | "square" | null {
  if (!width || !height) return null;
  const ratio = width / height;
  if (Math.abs(ratio - 1) <= 0.02) return "square";
  if (ratio > 1) return "desktop";
  return ratio <= 0.6 ? "phone" : null;
}
