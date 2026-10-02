import { clsx } from "clsx";
import { AlertTriangle, CheckCircle2, Copy, MapPin, ShieldAlert, Sparkles } from "lucide-react";
import { type MouseEvent, useEffect, useRef } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Spinner } from "@/components/ui/Spinner";
import type { Asset } from "@/lib/api/client";
import { formatBytes } from "@/lib/format";
import { formatDimensions } from "../studio/format";
import { shapeLabel } from "./rules";

const SHAPE_TEXT = { desktop: "Desktop", phone: "Phone", square: "Square" } as const;

export function selectMode(event: MouseEvent): "one" | "toggle" | "range" {
  if (event.shiftKey) return "range";
  if (event.metaKey || event.ctrlKey) return "toggle";
  return "one";
}

/** Why a copy lost to the one being kept (mirrors siqe.library.duplicates.reason). */
export function lossReason(keep: Asset, other: Asset): string {
  if (other.width * other.height * 1.1 < keep.width * keep.height) return "Lower resolution";
  const round = (x: number | null | undefined) => Math.round((x ?? 0) * 100);
  if (round(other.sharpness) < round(keep.sharpness)) return "Less sharp";
  const lossless = (a: Asset) => ["png", "tiff", "heif"].includes(a.format);
  if (lossless(keep) && !lossless(other)) return "Compressed copy";
  if (other.size_bytes < keep.size_bytes) return "More compressed";
  return "Newer copy";
}

export function Card({
  asset,
  selected,
  onSelect,
  onToggle,
  duplicates,
  verdict,
}: {
  asset: Asset;
  selected: boolean;
  onSelect: (event: MouseEvent) => void;
  onToggle: () => void;
  duplicates?: number;
  verdict?: { keep: boolean; reason?: string };
}) {
  const shape = shapeLabel(asset.width, asset.height);
  const tags = [...asset.tags, ...asset.auto_tags.filter((t) => !asset.tags.includes(t))].slice(0, 3);
  return (
    <li
      className={clsx(
        "group relative overflow-hidden rounded-lg border bg-panel transition [content-visibility:auto] [contain-intrinsic-size:auto_220px]",
        selected ? "border-cyan ring-1 ring-cyan" : "border-line hover:border-line-2",
      )}
      data-testid="library-card"
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={`${asset.original_name}, ${formatDimensions(asset.width, asset.height)}`}
        className="relative block aspect-[4/3] w-full overflow-hidden bg-panel-2"
      >
        {asset.thumb_url ? (
          <img src={asset.thumb_url} alt="" loading="lazy" className="size-full object-cover" />
        ) : asset.status === "failed" ? (
          <span className="grid size-full place-items-center content-center gap-1 text-[11px] text-err">
            <AlertTriangle className="size-4" aria-hidden="true" />
            Couldn't load
          </span>
        ) : (
          <span className="grid size-full place-items-center content-center gap-1 text-[11px] text-muted">
            <Spinner className="size-4" />
            Preparing
          </span>
        )}
        <span className="absolute top-1.5 right-1.5 flex gap-1">
          {asset.parent_id && (
            <span className="flex items-center gap-0.5 rounded bg-panel/85 px-1 py-0.5 font-mono text-[9.5px] font-semibold text-gold backdrop-blur-sm">
              <Sparkles className="size-2.5" aria-hidden="true" />
              AI
            </span>
          )}
          {asset.gps && (
            <span
              className="grid place-items-center rounded bg-panel/85 p-0.5 text-fg backdrop-blur-sm"
              title="Has location"
            >
              <MapPin className="size-3" aria-label="Has location" />
            </span>
          )}
          {duplicates !== undefined && duplicates > 1 && (
            <span className="flex items-center gap-0.5 rounded bg-panel/85 px-1 py-0.5 font-mono text-[9.5px] font-semibold text-warn backdrop-blur-sm">
              <Copy className="size-2.5" aria-hidden="true" />
              DUP ×{duplicates}
            </span>
          )}
        </span>
        <span className="absolute bottom-1.5 left-1.5 flex gap-1">
          {shape && (
            <span className="rounded bg-panel/85 px-1 py-0.5 font-mono text-[9.5px] tracking-wide text-fg uppercase backdrop-blur-sm">
              {SHAPE_TEXT[shape]}
            </span>
          )}
          {asset.score != null && (
            <span
              className="rounded bg-panel/85 px-1 py-0.5 font-mono text-[9.5px] text-gold backdrop-blur-sm"
              title="Match score"
            >
              {asset.score.toFixed(2)}
            </span>
          )}
        </span>
      </button>
      <label
        className={clsx(
          "absolute top-1.5 left-1.5 grid size-5 cursor-pointer place-items-center rounded bg-panel/85 backdrop-blur-sm transition",
          selected ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-within:opacity-100",
        )}
      >
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          aria-label={`Select ${asset.original_name}`}
          className="size-3.5 accent-[var(--cyan)]"
        />
      </label>
      <div className="grid gap-0.5 px-2 py-1.5">
        <span className="truncate text-[12px] font-medium text-fg" title={asset.original_name}>
          {asset.original_name}
        </span>
        <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted">
          <span className="shrink-0 font-mono">{asset.width.toLocaleString()}w</span>
          {tags.length > 0 && <span className="truncate">{tags.join(", ")}</span>}
          {!tags.length && <span className="truncate">{formatBytes(asset.size_bytes)}</span>}
        </span>
        {verdict && (
          <span className="mt-0.5">
            {verdict.keep ? (
              <Chip tone="ok" icon={<CheckCircle2 />}>
                Keep
              </Chip>
            ) : (
              <span className="grid justify-items-start gap-0.5">
                <Chip tone="warn" icon={<ShieldAlert />}>
                  Quarantine
                </Chip>
                <span className="text-[11px] text-fg-2">{verdict.reason}</span>
              </span>
            )}
          </span>
        )}
        {asset.quarantine_reason && (
          <span className="truncate text-[11px] text-fg-2" title={asset.quarantine_reason}>
            {asset.quarantine_reason}
          </span>
        )}
      </div>
    </li>
  );
}

const GRID = "grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-2.5 max-sm:grid-cols-2";

export function Grid({
  assets,
  selected,
  onSelect,
  onToggle,
  hasMore,
  loadingMore,
  onMore,
}: {
  assets: Asset[];
  selected: string[];
  onSelect: (id: string, event: MouseEvent) => void;
  onToggle: (id: string) => void;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
}) {
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasMore) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) onMore();
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, onMore]);
  const groupSizes = new Map<string, number>();
  for (const a of assets) {
    if (a.duplicate_group) groupSizes.set(a.duplicate_group, (groupSizes.get(a.duplicate_group) ?? 0) + 1);
  }
  return (
    <>
      <ul className={GRID} aria-label="Images">
        {assets.map((asset) => (
          <Card
            key={asset.id}
            asset={asset}
            selected={selected.includes(asset.id)}
            onSelect={(e) => onSelect(asset.id, e)}
            onToggle={() => onToggle(asset.id)}
            duplicates={asset.duplicate_group ? (groupSizes.get(asset.duplicate_group) ?? 2) : undefined}
          />
        ))}
      </ul>
      <div ref={sentinel} className="grid h-10 place-items-center">
        {loadingMore && <Spinner label="Loading more" className="size-4" />}
      </div>
    </>
  );
}

export function DuplicateGroups({
  assets,
  selected,
  onSelect,
  onToggle,
  onResolve,
  onKeepAll,
  busy,
}: {
  assets: Asset[];
  selected: string[];
  onSelect: (id: string, event: MouseEvent) => void;
  onToggle: (id: string) => void;
  onResolve: (group: string) => void;
  onKeepAll: (group: string) => void;
  busy: boolean;
}) {
  const groups = new Map<string, Asset[]>();
  for (const a of assets) {
    if (!a.duplicate_group) continue;
    groups.set(a.duplicate_group, [...(groups.get(a.duplicate_group) ?? []), a]);
  }
  return (
    <div className="grid gap-4">
      {[...groups.entries()].map(([group, members]) => {
        const ordered = [...members].sort((a, b) => (a.duplicate_rank ?? 0) - (b.duplicate_rank ?? 0));
        const keep = ordered[0];
        if (!keep) return null;
        return (
          <section
            key={group}
            aria-label={`Duplicate group of ${keep.original_name}`}
            className="grid gap-2 rounded-xl border border-line bg-panel p-3"
            data-testid="duplicate-group"
          >
            <header className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 text-[13px] font-semibold text-fg">
                <Copy className="size-4 text-warn" aria-hidden="true" />
                {ordered.length} copies of {keep.original_name}
              </h3>
              <div className="flex gap-1.5">
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => onKeepAll(group)}>
                  Not duplicates
                </Button>
                <Button size="sm" icon={<ShieldAlert />} disabled={busy} onClick={() => onResolve(group)}>
                  Keep best, quarantine {ordered.length - 1}
                </Button>
              </div>
            </header>
            <ul className={GRID}>
              {ordered.map((asset, index) => (
                <Card
                  key={asset.id}
                  asset={asset}
                  selected={selected.includes(asset.id)}
                  onSelect={(e) => onSelect(asset.id, e)}
                  onToggle={() => onToggle(asset.id)}
                  verdict={index === 0 ? { keep: true } : { keep: false, reason: lossReason(keep, asset) }}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
