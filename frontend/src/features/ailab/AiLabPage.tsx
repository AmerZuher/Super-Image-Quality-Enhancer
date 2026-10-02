import { useNavigate, useSearch } from "@tanstack/react-router";
import { clsx } from "clsx";
import {
  AlertTriangle,
  ArrowRight,
  Columns2,
  Eye,
  ImagePlus,
  Library,
  Sparkles,
  SplitSquareHorizontal,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import type { Asset } from "@/lib/api/client";
import { useAssets } from "../studio/api";
import { Filmstrip } from "../studio/components/Filmstrip";
import { formatDimensions } from "../studio/format";
import { useUploader } from "../studio/useUploader";
import { useChildren, useModels } from "./api";
import { type CompareMode, DeepCompare } from "./DeepCompare";
import { ModelLibrary } from "./Models";
import { RunPanel } from "./RunPanel";

type Tab = "run" | "models";

const MODES: { id: CompareMode; label: string; icon: ReactNode }[] = [
  { id: "split", label: "Split", icon: <SplitSquareHorizontal /> },
  { id: "side", label: "Side by side", icon: <Columns2 /> },
  { id: "before", label: "Original", icon: <Eye /> },
  { id: "after", label: "Result", icon: <Sparkles /> },
];

/** Select each new result as soon as it is ready, so a finished run is shown straight away. */
export function useAutoSelect(results: Asset[] | undefined, select: (id: string) => void) {
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!results) return; // not loaded yet: nothing counts as new
    const ready = results.filter((r) => r.status === "ready");
    if (seen.current === null) {
      seen.current = new Set(ready.map((r) => r.id));
      return;
    }
    const fresh = ready.find((r) => !seen.current?.has(r.id));
    for (const r of ready) seen.current.add(r.id);
    if (fresh) select(fresh.id);
  }, [results, select]);
}

export function AiLabPage() {
  const search = useSearch({ from: "/ai-lab" });
  const navigate = useNavigate({ from: "/ai-lab" });
  const { data: assets, isPending } = useAssets();
  const { data: models } = useModels();
  const [tab, setTab] = useState<Tab>("run");
  const [mode, setMode] = useState<CompareMode>("split");
  const filePicker = useRef<HTMLInputElement>(null);

  const list = assets ?? [];
  const asset = list.find((a) => a.id === search.asset) ?? list.find((a) => !a.parent_id) ?? list[0];
  const { data: children } = useChildren(asset?.id);
  const results = children ?? [];
  const result = results.find((r) => r.id === search.result && r.status === "ready");

  const select = useCallback(
    (id: string) => void navigate({ search: { asset: id }, replace: true }),
    [navigate],
  );
  const selectResult = useCallback(
    (id: string) =>
      void navigate({
        search: (s: { asset?: string; result?: string }) => ({ ...s, result: id }),
        replace: true,
      }),
    [navigate],
  );
  useAutoSelect(children, selectResult);
  const { upload, rejected, clearRejected, accept } = useUploader((a) => select(a.id));

  if (isPending) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner label="Loading images" className="size-6 text-gold" />
      </div>
    );
  }

  const picker = (
    <input
      ref={filePicker}
      type="file"
      multiple
      accept={accept}
      className="hidden"
      data-testid="ailab-file-input"
      onChange={(e) => {
        if (e.target.files?.length) upload(e.target.files);
        e.target.value = "";
      }}
    />
  );

  const installedCount = (models ?? []).filter((m) => m.status === "installed").length;

  return (
    <div
      className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] max-md:h-auto max-md:min-h-full"
      data-testid="ailab"
    >
      {rejected.length > 0 && (
        <div
          role="alert"
          className="flex items-center gap-2 border-b border-warn/40 bg-warn-soft px-3 py-1.5 text-[12px] text-warn"
        >
          <AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">
            Skipped {rejected.join(", ")}: not a supported image type.
          </span>
          <button type="button" onClick={clearRejected} className="underline">
            Dismiss
          </button>
        </div>
      )}
      {!rejected.length && <div />}
      <div className="grid min-h-0 grid-cols-[minmax(0,1fr)_340px] max-lg:grid-cols-1">
        <div className="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] max-lg:h-[62vh]">
          <header className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-panel px-3 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-2 text-[13px]">
              {asset ? (
                <>
                  <span className="truncate font-semibold text-fg" title={asset.original_name}>
                    {asset.original_name}
                  </span>
                  <span className="shrink-0 font-mono text-[11.5px] text-muted">
                    {formatDimensions(asset.width, asset.height)}
                  </span>
                  {result && (
                    <>
                      <ArrowRight className="size-3.5 shrink-0 text-gold" aria-hidden="true" />
                      <span className="truncate text-gold" title={result.original_name}>
                        {result.original_name}
                      </span>
                      <span className="shrink-0 font-mono text-[11.5px] text-muted">
                        {formatDimensions(result.width, result.height)}
                      </span>
                    </>
                  )}
                </>
              ) : (
                <span className="text-fg-2">No image selected</span>
              )}
            </div>
            <fieldset className="flex rounded-lg border border-line p-0.5" disabled={!result}>
              <legend className="sr-only">Compare</legend>
              {MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  aria-pressed={mode === m.id}
                  onClick={() => setMode(m.id)}
                  title={m.label}
                  className={clsx(
                    "flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] transition disabled:opacity-50 [&_svg]:size-3.5",
                    mode === m.id && result
                      ? "bg-gold-soft font-medium text-gold"
                      : "text-fg-2 hover:text-fg",
                  )}
                >
                  {m.icon}
                  <span className="max-xl:sr-only">{m.label}</span>
                </button>
              ))}
            </fieldset>
          </header>
          {asset?.status === "ready" ? (
            <DeepCompare
              key={`${asset.id}:${result?.id ?? ""}`}
              before={asset}
              after={result ?? null}
              mode={result ? mode : "before"}
            />
          ) : asset ? (
            <div className="grid place-items-center bg-stage text-[12.5px] text-fg-2">
              <span className="flex items-center gap-2">
                <Spinner className="size-3.5" /> Preparing the image
              </span>
            </div>
          ) : (
            <div className="grid place-items-center bg-stage p-6">
              {picker}
              <div className="grid max-w-[440px] justify-items-center gap-3 text-center">
                <span className="grid size-12 place-items-center rounded-2xl border border-gold/40 bg-gold-soft text-gold">
                  <Sparkles className="size-6" aria-hidden="true" />
                </span>
                <h2 className="font-display text-[19px] font-medium text-fg">
                  Add an image to try the models
                </h2>
                <p className="text-[13px] text-fg-2">
                  Upscale, denoise or cut out the subject. Results become new images; your original never
                  changes.
                </p>
                <Button variant="primary" icon={<ImagePlus />} onClick={() => filePicker.current?.click()}>
                  Choose images
                </Button>
              </div>
            </div>
          )}
        </div>
        <aside
          className="flex min-h-0 flex-col border-l border-line bg-panel max-lg:border-t max-lg:border-l-0"
          aria-label="AI tools"
        >
          <div
            role="tablist"
            aria-label="AI tools"
            className="flex shrink-0 gap-1 border-b border-line px-2 pt-2"
          >
            {(
              [
                ["run", "Run", <Sparkles key="r" />],
                ["models", `Models (${installedCount})`, <Library key="m" />],
              ] as const
            ).map(([id, label, icon]) => (
              <button
                key={id}
                type="button"
                role="tab"
                id={`ai-tab-${id}`}
                aria-selected={tab === id}
                aria-controls="ai-panel"
                onClick={() => setTab(id)}
                className={clsx(
                  "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-[12.5px] transition [&_svg]:size-3.5",
                  tab === id ? "border-gold text-fg" : "border-transparent text-muted hover:text-fg",
                )}
              >
                {icon}
                {label}
              </button>
            ))}
          </div>
          <div
            id="ai-panel"
            role="tabpanel"
            aria-labelledby={`ai-tab-${tab}`}
            className="min-h-0 flex-1 overflow-y-auto p-3"
          >
            {!models ? (
              <Spinner label="Loading models" className="size-5 text-gold" />
            ) : tab === "models" ? (
              <ModelLibrary models={models} />
            ) : asset ? (
              <RunPanel
                key={asset.id}
                asset={asset}
                models={models}
                results={results}
                selectedResult={result?.id}
                onSelectResult={selectResult}
              />
            ) : (
              <p className="text-[12.5px] text-muted">Add an image first.</p>
            )}
          </div>
        </aside>
      </div>
      <Filmstrip assets={list} selectedId={asset?.id} onSelect={select} onFiles={upload} accept={accept} />
    </div>
  );
}
