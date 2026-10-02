import { clsx } from "clsx";
import {
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  ImagePlus,
  Search,
  SlidersHorizontal,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import type { LibraryStatus, Rule, RuleSet } from "@/lib/api/client";
import type { Sort } from "./api";
import { COLORS, describeRule, hasRule, QUICK_FILTERS, toggleRule } from "./rules";

const SORTS: { id: Sort; label: string }[] = [
  { id: "added", label: "Date added" },
  { id: "taken", label: "Date taken" },
  { id: "name", label: "Name" },
  { id: "size", label: "File size" },
  { id: "resolution", label: "Resolution" },
  { id: "sharpness", label: "Sharpness" },
];

/** Colour family swatches (data colours from tokens.css, not theme accents). */
export const SWATCH: Record<(typeof COLORS)[number], string> = {
  red: "bg-[var(--swatch-red)]",
  orange: "bg-[var(--swatch-orange)]",
  yellow: "bg-[var(--swatch-yellow)]",
  green: "bg-[var(--swatch-green)]",
  teal: "bg-[var(--swatch-teal)]",
  blue: "bg-[var(--swatch-blue)]",
  purple: "bg-[var(--swatch-purple)]",
  pink: "bg-[var(--swatch-pink)]",
  neutral: "bg-[var(--swatch-neutral)]",
};

export function SearchBox({
  value,
  onChange,
  semantic,
}: {
  value: string;
  onChange: (q: string) => void;
  semantic: boolean;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (text === value) return;
    const timer = setTimeout(() => onChange(text), 350);
    return () => clearTimeout(timer);
  }, [text, value, onChange]);
  return (
    <div className="relative min-w-[200px] flex-1">
      {semantic ? (
        <Sparkles
          className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-gold"
          aria-hidden="true"
        />
      ) : (
        <Search
          className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted"
          aria-hidden="true"
        />
      )}
      <input
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onChange(text)}
        placeholder={semantic ? "Describe a photo: “mountain lake at sunrise”" : "Search by name or tag"}
        aria-label={semantic ? "Search by description" : "Search by name or tag"}
        className={clsx(
          "h-9 w-full rounded-lg border bg-panel-2 pr-8 pl-8 text-[13px] text-fg outline-none placeholder:text-muted",
          semantic ? "border-gold/35 focus:border-gold" : "border-line-2 focus:border-cyan",
        )}
      />
      {text && (
        <button
          type="button"
          onClick={() => {
            setText("");
            onChange("");
          }}
          aria-label="Clear search"
          className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-muted hover:text-fg"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  );
}

export function Toolbar({
  q,
  onQuery,
  semantic,
  rules,
  onRules,
  sort,
  order,
  onSort,
  status,
  onSaveAlbum,
  onAdd,
  showFilters,
}: {
  q: string;
  onQuery: (q: string) => void;
  semantic: boolean;
  rules: RuleSet;
  onRules: (rules: RuleSet) => void;
  sort: Sort;
  order: "asc" | "desc";
  onSort: (sort: Sort, order: "asc" | "desc") => void;
  status: LibraryStatus | undefined;
  onSaveAlbum: () => void;
  onAdd: () => void;
  showFilters: boolean;
}) {
  const active = rules.rules ?? [];
  const toggle = (rule: Rule) => onRules(toggleRule(rules, rule));
  const quick = QUICK_FILTERS.map((f) => f.rule);
  const extra = active.filter(
    (r) => !quick.some((q) => q.field === r.field && q.op === r.op && q.value === r.value),
  );
  const tags = (status?.tags ?? []).slice(0, 10);
  const [open, setOpen] = useState(false);
  return (
    <div className="grid gap-2 border-b border-line bg-panel px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <SearchBox value={q} onChange={onQuery} semantic={semantic} />
        <label className="flex items-center gap-1.5 text-[12px] text-fg-2">
          <span className="sr-only">Sort by</span>
          <select
            value={sort}
            onChange={(e) => onSort(e.target.value as Sort, order)}
            className="h-9 rounded-lg border border-line-2 bg-panel-2 px-2 text-[12.5px] text-fg"
            disabled={Boolean(q)}
            title={q ? "Search results are sorted by how well they match" : undefined}
          >
            {SORTS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <Button
          size="md"
          variant="ghost"
          aria-label={
            order === "desc"
              ? "Sorted high to low; switch to low to high"
              : "Sorted low to high; switch to high to low"
          }
          icon={order === "desc" ? <ArrowDownWideNarrow /> : <ArrowUpNarrowWide />}
          onClick={() => onSort(sort, order === "desc" ? "asc" : "desc")}
          disabled={Boolean(q)}
        />
        {showFilters && (
          <Button
            className="md:hidden"
            icon={<SlidersHorizontal />}
            aria-expanded={open}
            aria-controls="library-filters"
            onClick={() => setOpen(!open)}
          >
            Filters{active.length ? ` (${active.length})` : ""}
          </Button>
        )}
        <Button variant="primary" icon={<ImagePlus />} onClick={onAdd}>
          <span className="max-sm:sr-only">Add images</span>
        </Button>
      </div>
      {showFilters && (
        <fieldset
          id="library-filters"
          className={clsx(
            "m-0 min-w-0 flex-wrap items-center gap-1.5 border-0 p-0 md:flex",
            open ? "flex" : "hidden",
          )}
        >
          <legend className="sr-only">Filters</legend>
          {QUICK_FILTERS.map((f) => {
            const on = hasRule(rules, f.rule);
            return (
              <button
                key={f.label}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(f.rule)}
                className={clsx(
                  "h-7 rounded-full border px-2.5 text-[12px] transition",
                  on
                    ? "border-cyan bg-cyan-soft font-medium text-cyan"
                    : "border-line-2 text-fg-2 hover:border-cyan hover:text-fg",
                )}
              >
                {f.label}
              </button>
            );
          })}
          <span className="mx-1 h-4 w-px bg-line-2" aria-hidden="true" />
          {COLORS.map((color) => {
            const rule: Rule = { field: "color", op: "is", value: color };
            const on = hasRule(rules, rule);
            return (
              <button
                key={color}
                type="button"
                aria-pressed={on}
                aria-label={`Mostly ${color}`}
                title={`Mostly ${color}`}
                onClick={() => toggle(rule)}
                className={clsx(
                  "grid size-6 place-items-center rounded-full border transition",
                  on ? "border-cyan ring-2 ring-cyan/40" : "border-line-2 hover:border-fg-2",
                )}
              >
                <span className={clsx("size-3.5 rounded-full", SWATCH[color])} />
              </button>
            );
          })}
          {tags.length > 0 && <span className="mx-1 h-4 w-px bg-line-2" aria-hidden="true" />}
          {tags.map(({ tag, count }) => {
            const rule: Rule = { field: "tag", op: "has", value: tag };
            const on = hasRule(rules, rule);
            return (
              <button
                key={tag}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(rule)}
                className={clsx(
                  "h-7 rounded-full border px-2.5 text-[12px] transition",
                  on
                    ? "border-cyan bg-cyan-soft font-medium text-cyan"
                    : "border-line text-fg-2 hover:border-cyan hover:text-fg",
                )}
              >
                {tag} <span className="font-mono text-[10.5px] text-muted">{count}</span>
              </button>
            );
          })}
          {extra.map((rule) => (
            <span
              key={`${rule.field}:${rule.op}:${String(rule.value)}`}
              className="inline-flex h-7 items-center gap-1 rounded-full border border-cyan bg-cyan-soft pr-1 pl-2.5 text-[12px] text-cyan"
            >
              {describeRule(rule)}
              <button
                type="button"
                onClick={() => toggle(rule)}
                aria-label={`Remove filter ${describeRule(rule)}`}
                className="rounded-full p-0.5 hover:bg-cyan/20"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
          {active.length > 0 && (
            <>
              <Button size="sm" variant="ghost" onClick={() => onRules({ match: "all", rules: [] })}>
                Clear
              </Button>
              <Button size="sm" icon={<Wand2 />} onClick={onSaveAlbum}>
                Save as smart album
              </Button>
            </>
          )}
        </fieldset>
      )}
    </div>
  );
}
