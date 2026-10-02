import { useNavigate, useSearch } from "@tanstack/react-router";
import { clsx } from "clsx";
import {
  CheckCircle2,
  Copy,
  FolderInput,
  ImagePlus,
  Images,
  ScanSearch,
  SearchX,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { type DragEvent, type MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Drawer } from "@/components/ui/Drawer";
import { Spinner } from "@/components/ui/Spinner";
import type { Album, Asset } from "@/lib/api/client";
import { useModels } from "../ailab/api";
import { ModelControl } from "../ailab/Models";
import { useUploader } from "../studio/useUploader";
import { type AlbumDraft, AlbumEditor } from "./AlbumEditor";
import {
  useAlbums,
  useDeleteForever,
  useImportStatus,
  useKeepAll,
  useLibraryPages,
  useLibraryStatus,
  useResolveDuplicates,
  type View,
} from "./api";
import { DuplicateGroups, Grid, selectMode } from "./Grid";
import { Inspector } from "./Inspector";
import { SelectionBar } from "./SelectionBar";
import { type Place, Sidebar } from "./Sidebar";
import { useLibraryStore } from "./store";
import { Toolbar } from "./Toolbar";

export interface LibrarySearch {
  view?: View;
  album?: string;
  q?: string;
  similar?: string;
}

function useWide(query = "(min-width: 1280px)"): boolean {
  const [wide, setWide] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const on = () => setWide(media.matches);
    media.addEventListener("change", on);
    return () => media.removeEventListener("change", on);
  }, [query]);
  return wide;
}

function SearchSetup() {
  const { data: models } = useModels();
  const { data: status } = useLibraryStatus();
  const model = models?.find((m) => m.id === status?.search_model_id);
  if (!status || !model) return null;
  if (status.search_model === "installed") {
    if (!status.pending) return null;
    return (
      <div
        className="flex items-center gap-2 border-b border-line bg-panel px-3 py-1.5 text-[12px] text-fg-2"
        role="status"
      >
        <Spinner className="size-3.5 text-gold" />
        Analysing {status.pending.toLocaleString()} image{status.pending === 1 ? "" : "s"} for search, tags
        and duplicates
      </div>
    );
  }
  return (
    <div
      className="flex flex-wrap items-center gap-3 border-b border-gold/30 bg-gold-soft px-3 py-2"
      data-testid="search-setup"
    >
      <Sparkles className="size-4 shrink-0 text-gold" aria-hidden="true" />
      <p className="min-w-[240px] flex-1 text-[12.5px] text-fg">
        <strong className="font-semibold">Search by description, find similar and automatic tags</strong> need{" "}
        {model.name} ({model.license}). It runs on the CPU; duplicates and filters work without it.
      </p>
      <ModelControl model={model} compact />
    </div>
  );
}

function Empty({ view, query, onAdd }: { view: View; query: string; onAdd: () => void }) {
  const { data: imports } = useImportStatus();
  if (query) {
    return (
      <div className="grid place-items-center gap-2 py-16 text-center">
        <SearchX className="size-8 text-muted" aria-hidden="true" />
        <p className="text-[14px] font-medium text-fg">Nothing matches “{query}”</p>
        <p className="max-w-[360px] text-[12.5px] text-fg-2">
          Try fewer words, or describe what's in the photo.
        </p>
      </div>
    );
  }
  if (view === "duplicates") {
    return (
      <div className="grid place-items-center gap-2 py-16 text-center">
        <CheckCircle2 className="size-8 text-ok" aria-hidden="true" />
        <p className="text-[14px] font-medium text-fg">No duplicates</p>
        <p className="max-w-[380px] text-[12.5px] text-fg-2">
          New images are compared as they arrive: resized, recompressed and lightly edited copies all count.
        </p>
      </div>
    );
  }
  if (view === "quarantine") {
    return (
      <div className="grid place-items-center gap-2 py-16 text-center">
        <ShieldAlert className="size-8 text-muted" aria-hidden="true" />
        <p className="text-[14px] font-medium text-fg">Quarantine is empty</p>
        <p className="max-w-[380px] text-[12.5px] text-fg-2">
          Images you quarantine wait here, hidden from Studio and AI Lab, until you restore or delete them.
        </p>
      </div>
    );
  }
  return (
    <div className="grid place-items-center gap-3 py-16 text-center">
      <span className="grid size-12 place-items-center rounded-2xl border border-cyan/40 bg-cyan-soft text-cyan">
        <Images className="size-6" aria-hidden="true" />
      </span>
      <p className="font-display text-[19px] font-medium text-fg">
        {view === "album" ? "No images in this album" : "Your library is empty"}
      </p>
      <p className="max-w-[420px] text-[13px] text-fg-2">
        Drop images here, or put them in the import folder
        {imports ? (
          <>
            {" "}
            (<span className="font-mono">{imports.folder}</span>)
          </>
        ) : null}{" "}
        and they'll appear within a minute.
      </p>
      <Button variant="primary" icon={<ImagePlus />} onClick={onAdd}>
        Choose images
      </Button>
    </div>
  );
}

export function LibraryPage() {
  const search = useSearch({ from: "/library" }) as LibrarySearch;
  const navigate = useNavigate({ from: "/library" });
  const view: View = search.view ?? "all";
  const place: Place = { view, albumId: search.album };
  const { rules, sort, order, setRules, setSort, selected, select, setSelected, clear } = useLibraryStore();
  const { data: status } = useLibraryStatus();
  const { data: albums = [] } = useAlbums();
  const pages = useLibraryPages({
    view,
    albumId: search.album,
    q: search.q,
    similarTo: search.similar,
    rules,
    sort,
    order,
  });
  const assets = useMemo(() => pages.data?.pages.flatMap((p) => p.items) ?? [], [pages.data]);
  const first = pages.data?.pages[0];
  const total = first?.total ?? 0;
  const mode = first?.mode ?? "browse";
  const order_ = useMemo(() => assets.map((a) => a.id), [assets]);
  const byId = useMemo(() => new Map(assets.map((a) => [a.id, a])), [assets]);
  const chosen = selected.map((id) => byId.get(id)).filter((a): a is Asset => Boolean(a));
  const single = chosen.length === 1 ? chosen[0] : null;
  const wide = useWide();
  const [draft, setDraft] = useState<AlbumDraft | null>(null);
  const [similarAsset, setSimilarAsset] = useState<Asset | null>(null);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const resolve = useResolveDuplicates();
  const keepAll = useKeepAll();
  const emptyQuarantine = useDeleteForever();
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(timer);
  }, [armed]);

  const go = useCallback(
    (next: Partial<LibrarySearch>, keep: (keyof LibrarySearch)[] = []) => {
      clear();
      void navigate({
        search: (s: LibrarySearch) => {
          const out: LibrarySearch = {};
          for (const key of keep) if (s[key] !== undefined) (out as Record<string, unknown>)[key] = s[key];
          return { ...out, ...next };
        },
      });
    },
    [navigate, clear],
  );
  const onPlace = (p: Place) =>
    go({ view: p.view === "all" ? undefined : p.view, album: p.view === "album" ? p.albumId : undefined });
  const onQuery = useCallback(
    (q: string) => go({ q: q || undefined, similar: undefined }, ["view", "album"]),
    [go],
  );
  const onSimilar = (id: string) => {
    setSimilarAsset(byId.get(id) ?? null);
    go({ similar: id, q: undefined }, ["view", "album"]);
  };
  const { upload, accept, rejected, clearRejected } = useUploader(() => undefined);

  const onSelect = (id: string, event: MouseEvent) => select(id, selectMode(event), order_);
  const onToggle = (id: string) => select(id, "toggle", order_);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest("input, textarea, select, [role=dialog]")) return;
      if (event.key === "Escape") clear();
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "a" && assets.length) {
        event.preventDefault();
        setSelected(order_);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [assets.length, order_, clear, setSelected]);

  const album = view === "album" ? albums.find((a) => a.id === search.album) : undefined;
  const title =
    view === "duplicates"
      ? "Duplicates"
      : view === "quarantine"
        ? "Quarantine"
        : album
          ? album.name
          : "All images";
  const semantic = status?.search_model === "installed";
  const groups = status?.counts.duplicate_groups ?? 0;

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) upload(event.dataTransfer.files);
  };

  const inspector = single ? (
    <Inspector
      asset={single}
      albums={albums}
      onSimilar={onSimilar}
      canSimilar={semantic && Boolean(single.analysed)}
    />
  ) : (
    <LibrarySummary status={status} count={chosen.length} />
  );

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: the page is a drop target for files; "Add images" is the keyboard route
    <div
      className="grid h-full min-h-0 grid-cols-[210px_minmax(0,1fr)_330px] max-xl:grid-cols-[200px_minmax(0,1fr)] max-md:h-auto max-md:min-h-full max-md:grid-cols-1"
      data-testid="library"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)}
      onDrop={onDrop}
    >
      <input
        ref={picker}
        type="file"
        multiple
        accept={accept}
        className="hidden"
        data-testid="library-file-input"
        onChange={(e) => {
          if (e.target.files?.length) upload(e.target.files);
          e.target.value = "";
        }}
      />
      <aside className="flex min-h-0 flex-col border-r border-line bg-panel max-md:hidden">
        <Sidebar
          place={place}
          onPlace={onPlace}
          status={status}
          albums={albums}
          onNewAlbum={() => setDraft({ name: "", kind: "smart", rules: { match: "all", rules: [] } })}
          onEditAlbum={(a: Album) => setDraft({ id: a.id, name: a.name, kind: a.kind, rules: a.rules })}
        />
      </aside>

      <section
        className="relative grid min-h-0 min-w-0 grid-rows-[auto_auto_auto_minmax(0,1fr)_auto]"
        aria-label={title}
      >
        <nav
          aria-label="Library views"
          className="flex gap-1.5 overflow-x-auto border-b border-line bg-panel px-3 py-2 md:hidden"
        >
          {(
            [
              ["all", "All", status?.counts.all],
              ["duplicates", "Duplicates", status?.counts.duplicates],
              ["quarantine", "Quarantine", status?.counts.quarantine],
            ] as const
          ).map(([id, label, n]) => (
            <button
              key={id}
              type="button"
              onClick={() => onPlace({ view: id })}
              aria-current={view === id ? "page" : undefined}
              className={clsx(
                "h-7 shrink-0 rounded-full border px-3 text-[12px]",
                view === id ? "border-cyan bg-cyan-soft text-cyan" : "border-line-2 text-fg-2",
              )}
            >
              {label} {n !== undefined && <span className="font-mono text-[11px]">{n}</span>}
            </button>
          ))}
          {albums.map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => onPlace({ view: "album", albumId: a.id })}
              aria-current={view === "album" && search.album === a.id ? "page" : undefined}
              className={clsx(
                "h-7 shrink-0 rounded-full border px-3 text-[12px]",
                view === "album" && search.album === a.id
                  ? "border-cyan bg-cyan-soft text-cyan"
                  : "border-line-2 text-fg-2",
              )}
            >
              {a.name} <span className="font-mono text-[11px]">{a.count}</span>
            </button>
          ))}
        </nav>
        <SearchSetup />
        <Toolbar
          q={search.q ?? ""}
          onQuery={onQuery}
          semantic={semantic}
          rules={rules}
          onRules={(r) => {
            clear();
            setRules(r);
          }}
          sort={sort}
          order={order}
          onSort={setSort}
          status={status}
          onSaveAlbum={() => setDraft({ name: "", kind: "smart", rules })}
          onAdd={() => picker.current?.click()}
          showFilters={view !== "duplicates"}
        />
        <div className="min-h-0 overflow-y-auto p-3" data-testid="library-results">
          {rejected.length > 0 && (
            <p role="alert" className="mb-2 flex items-center gap-2 text-[12px] text-warn">
              Skipped {rejected.join(", ")}: not a supported image type.
              <button type="button" className="underline" onClick={clearRejected}>
                Dismiss
              </button>
            </p>
          )}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="font-display text-[17px] font-medium text-fg">{title}</h2>
            {!pages.isPending && (
              <span className="font-mono text-[12px] text-muted">{total.toLocaleString()}</span>
            )}
            {mode === "text" && (
              <Chip tone="gold" icon={<Sparkles />}>
                Best matches for “{search.q}”
              </Chip>
            )}
            {mode === "name" && search.q && <Chip tone="cyan">Names and tags matching “{search.q}”</Chip>}
            {search.similar && (
              <span className="inline-flex items-center gap-1 rounded-full border border-gold/45 bg-gold-soft py-0.5 pr-1 pl-2 text-[11.5px] text-gold">
                <ScanSearch className="size-3.5" aria-hidden="true" />
                Similar to {similarAsset?.original_name ?? "the selected image"}
                <button
                  type="button"
                  onClick={() => go({ similar: undefined }, ["view", "album", "q"])}
                  aria-label="Stop showing similar images"
                  className="rounded-full p-0.5 hover:bg-gold/20"
                >
                  <X className="size-3" />
                </button>
              </span>
            )}
            {pages.isFetching && !pages.isFetchingNextPage && <Spinner className="size-3.5 text-muted" />}
            <span className="flex-1" />
            {view === "duplicates" && groups > 0 && (
              <Button
                size="sm"
                icon={<Copy />}
                loading={resolve.isPending}
                onClick={() => resolve.mutate(null)}
              >
                Keep the best of all {groups} group{groups === 1 ? "" : "s"}
              </Button>
            )}
            {view === "quarantine" && total > 0 && (
              <Button
                size="sm"
                variant="danger"
                icon={<Trash2 />}
                loading={emptyQuarantine.isPending}
                onClick={() => (armed ? emptyQuarantine.mutate(order_) : setArmed(true))}
              >
                {armed ? `Delete ${assets.length} for good?` : "Empty quarantine"}
              </Button>
            )}
          </div>
          {view === "quarantine" && total > 0 && (
            <p className="mb-3 text-[12.5px] text-fg-2">
              These images are hidden from Studio and AI Lab. Restore them, or delete them and their files for
              good.
            </p>
          )}
          {pages.isPending ? (
            <div className="grid place-items-center py-16">
              <Spinner label="Loading images" className="size-6 text-cyan" />
            </div>
          ) : pages.isError ? (
            <p role="alert" className="text-[13px] text-err">
              {String((pages.error as Error).message)}
            </p>
          ) : !assets.length ? (
            <Empty view={view} query={search.q ?? ""} onAdd={() => picker.current?.click()} />
          ) : view === "duplicates" ? (
            <DuplicateGroups
              assets={assets}
              selected={selected}
              onSelect={onSelect}
              onToggle={onToggle}
              onResolve={(g) => resolve.mutate([g])}
              onKeepAll={(g) => keepAll.mutate(g)}
              busy={resolve.isPending || keepAll.isPending}
            />
          ) : (
            <Grid
              assets={assets}
              selected={selected}
              onSelect={onSelect}
              onToggle={onToggle}
              hasMore={Boolean(pages.hasNextPage)}
              loadingMore={pages.isFetchingNextPage}
              onMore={() => void pages.fetchNextPage()}
            />
          )}
        </div>
        {chosen.length > 1 && (
          <SelectionBar
            selected={chosen}
            albums={albums}
            quarantineView={view === "quarantine"}
            onClear={clear}
          />
        )}
        {dragging && (
          <div className="pointer-events-none absolute inset-2 grid place-items-center rounded-xl border-2 border-dashed border-cyan bg-cyan-soft">
            <span className="flex items-center gap-2 text-[14px] font-medium text-cyan">
              <FolderInput className="size-5" aria-hidden="true" />
              Drop to add to the library
            </span>
          </div>
        )}
      </section>

      {wide ? (
        <aside
          className="min-h-0 overflow-y-auto border-l border-line bg-panel p-3"
          aria-label="Image details"
        >
          {inspector}
        </aside>
      ) : (
        <Drawer open={Boolean(single)} onClose={clear} title={single?.original_name ?? "Image"}>
          {single && inspector}
        </Drawer>
      )}
      <AlbumEditor draft={draft} onClose={() => setDraft(null)} />
    </div>
  );
}

function LibrarySummary({
  status,
  count,
}: {
  status: ReturnType<typeof useLibraryStatus>["data"];
  count: number;
}) {
  if (count > 1) {
    return (
      <div className="grid gap-2 text-[12.5px] text-fg-2">
        <h2 className="text-[14px] font-semibold text-fg">{count} images selected</h2>
        <p>
          Use the bar below the grid to tag them, add them to an album, remove their location or quarantine
          them.
        </p>
      </div>
    );
  }
  return (
    <div className="grid gap-4 text-[12.5px] text-fg-2">
      <div>
        <h2 className="mb-1 text-[14px] font-semibold text-fg">Library</h2>
        <p>
          Select an image to see its details, tags and location. Ctrl-click or Shift-click selects several.
        </p>
      </div>
      {status && (
        <dl className="grid grid-cols-2 gap-2">
          {(
            [
              ["Images", status.counts.all],
              ["Duplicate groups", status.counts.duplicate_groups],
              ["In quarantine", status.counts.quarantine],
              ["Waiting for analysis", status.pending],
            ] as const
          ).map(([label, n]) => (
            <div key={label} className="rounded-lg border border-line bg-panel-2 p-2">
              <dt className="text-[11px] text-muted">{label}</dt>
              <dd className="font-mono text-[16px] text-fg">{n.toLocaleString()}</dd>
            </div>
          ))}
        </dl>
      )}
      {status && status.tags.length > 0 && (
        <section>
          <h3 className="eyebrow mb-1.5">Most common tags</h3>
          <ul className="flex flex-wrap gap-1">
            {status.tags.map((t) => (
              <li key={t.tag} className="rounded-full border border-line px-2 py-0.5 text-[11.5px]">
                {t.tag} <span className="font-mono text-muted">{t.count}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
