import { useNavigate, useSearch } from "@tanstack/react-router";
import { clsx } from "clsx";
import {
  AlertTriangle,
  Columns2,
  Crop,
  Diff,
  FileDown,
  ImagePlus,
  SlidersHorizontal,
  SplitSquareHorizontal,
  Square,
  UploadCloud,
} from "lucide-react";
import { type DragEvent, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Kbd } from "@/components/ui/Kbd";
import { Spinner } from "@/components/ui/Spinner";
import { type Asset, errorMessage } from "@/lib/api/client";
import { useAssets, useCatalog, useEdits } from "./api";
import { AdjustPanel } from "./components/AdjustPanel";
import { CropPanel } from "./components/CropPanel";
import { EditStack, HistoryList } from "./components/EditStack";
import { ExportPanel } from "./components/ExportPanel";
import { Filmstrip } from "./components/Filmstrip";
import { Inspector } from "./components/Inspector";
import { Stage } from "./components/Stage";
import { StudioHeader } from "./components/StudioHeader";
import { fromServer, outputSize } from "./doc";
import { formatDimensions } from "./format";
import type { CompareMode } from "./gl/renderer";
import { type Panel, useEditor } from "./store";
import { useUploader } from "./useUploader";

const PANELS: { id: Panel; label: string; icon: ReactNode }[] = [
  { id: "adjust", label: "Adjust", icon: <SlidersHorizontal /> },
  { id: "crop", label: "Crop", icon: <Crop /> },
  { id: "export", label: "Export", icon: <FileDown /> },
];

const MODES: { id: CompareMode; label: string; icon: ReactNode }[] = [
  { id: "after", label: "Edited", icon: <Square /> },
  { id: "split", label: "Split", icon: <SplitSquareHorizontal /> },
  { id: "side", label: "Side by side", icon: <Columns2 /> },
  { id: "diff", label: "Difference", icon: <Diff /> },
];

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable || target.tagName === "TEXTAREA" || target.tagName === "SELECT") return true;
  return (
    target instanceof HTMLInputElement && !["range", "checkbox", "radio", "button"].includes(target.type)
  );
}

function DropOverlay() {
  return (
    <div className="pointer-events-none absolute inset-2 z-40 grid place-items-center rounded-xl border-2 border-dashed border-cyan bg-[var(--overlay)]">
      <div className="flex items-center gap-2 rounded-full bg-panel px-4 py-2 text-[13px] font-medium text-cyan shadow-float">
        <UploadCloud className="size-4" aria-hidden="true" />
        Drop to add images
      </div>
    </div>
  );
}

function EmptyState({
  onPick,
  accept,
  maxMb,
  maxMp,
}: {
  onPick: () => void;
  accept: string;
  maxMb?: number;
  maxMp?: number;
}) {
  return (
    <div className="grid h-full place-items-center p-4 md:p-10">
      <div className="grid max-w-[520px] justify-items-center gap-4 rounded-2xl border border-dashed border-line-2 bg-panel p-8 text-center md:p-12">
        <span className="grid size-14 place-items-center rounded-2xl border border-cyan/40 bg-cyan-soft text-cyan">
          <ImagePlus className="size-7" aria-hidden="true" />
        </span>
        <div className="grid gap-1.5">
          <h2 className="font-display text-[20px] font-medium text-fg">Add images to start editing</h2>
          <p className="text-[13.5px] text-fg-2">
            Drop files anywhere on this page or choose them. Edits never change the original; export a copy
            when you're happy.
          </p>
        </div>
        <Button variant="primary" icon={<ImagePlus />} onClick={onPick}>
          Choose images
        </Button>
        <p className="text-[11.5px] text-muted">
          {accept.replaceAll(".", "").toUpperCase().replaceAll(",", " · ")}
          {maxMb && maxMp ? ` — up to ${maxMb.toLocaleString()} MB and ${maxMp} megapixels each` : ""}
        </p>
      </div>
    </div>
  );
}

function NotReady({ asset }: { asset: Asset }) {
  return (
    <div className="grid place-items-center bg-stage p-6">
      {asset.status === "failed" ? (
        <div className="grid max-w-[420px] gap-2 text-center">
          <p className="flex items-center justify-center gap-2 text-[13.5px] font-medium text-err">
            <AlertTriangle className="size-4" aria-hidden="true" />
            This image couldn't be prepared
          </p>
          <p className="text-[12.5px] text-fg-2">
            {String((asset.error as { message?: string } | null)?.message ?? "The file may be damaged.")}
          </p>
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-full bg-panel px-3 py-1.5 text-[12.5px] text-fg-2 shadow-float">
          <Spinner className="size-3.5" />
          Preparing the preview and zoom tiles
        </div>
      )}
    </div>
  );
}

/** Loads the edit document for the selected image into the editor, saving the previous one first. */
function useEditorFor(asset: Asset | undefined) {
  const ready = asset?.status === "ready";
  const edits = useEdits(ready ? asset?.id : undefined);
  const loadedId = useEditor((s) => s.assetId);
  const load = useEditor((s) => s.load);
  const flush = useEditor((s) => s.flush);
  useEffect(() => {
    if (!asset || !edits.data || loadedId === asset.id) return;
    let cancelled = false;
    void flush().then(() => {
      if (!cancelled) load(asset.id, fromServer(edits.data));
    });
    return () => {
      cancelled = true;
    };
  }, [asset, edits.data, loadedId, load, flush]);
  return { loaded: Boolean(asset) && loadedId === asset?.id, error: edits.error };
}

function CanvasBar({ asset }: { asset: Asset }) {
  const compare = useEditor((s) => s.compare);
  const setCompare = useEditor((s) => s.setCompare);
  const panel = useEditor((s) => s.panel);
  const geometry = useEditor((s) => s.doc.geometry);
  const [w, h] = outputSize(asset.width, asset.height, geometry);
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-line bg-panel px-3 py-1.5">
      <fieldset className="flex rounded-lg border border-line p-0.5" disabled={panel === "crop"}>
        <legend className="sr-only">Compare</legend>
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            aria-pressed={compare === m.id}
            onClick={() => setCompare(m.id)}
            title={m.label}
            className={clsx(
              "flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] transition disabled:opacity-50 [&_svg]:size-3.5",
              compare === m.id ? "bg-cyan-soft font-medium text-cyan" : "text-fg-2 hover:text-fg",
            )}
          >
            {m.icon}
            <span className="max-sm:sr-only">{m.label}</span>
          </button>
        ))}
      </fieldset>
      <span className="flex-1" />
      <span className="hidden items-center gap-1.5 text-[11.5px] text-muted md:flex">
        Hold <Kbd>\</Kbd> for the original
      </span>
      <span className="font-mono text-[11.5px] text-fg-2" title="Size of the exported image">
        {formatDimensions(w, h)}
      </span>
    </div>
  );
}

export function StudioPage() {
  const search = useSearch({ from: "/studio" });
  const navigate = useNavigate({ from: "/studio" });
  const { data: assets, isPending, error } = useAssets();
  const { data: catalog } = useCatalog();
  const panel = useEditor((s) => s.panel);
  const setPanel = useEditor((s) => s.setPanel);
  const inspecting = useEditor((s) => s.inspecting);
  const setInspecting = useEditor((s) => s.setInspecting);
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const filePicker = useRef<HTMLInputElement>(null);

  const list = assets ?? [];
  const asset = list.find((a) => a.id === search.asset) ?? list[0];
  const select = useCallback(
    (id: string) => void navigate({ search: { asset: id }, replace: true }),
    [navigate],
  );
  const onUploaded = useCallback((a: Asset) => select(a.id), [select]);
  const { upload, rejected, clearRejected, accept } = useUploader(onUploaded);
  const { loaded } = useEditorFor(asset);
  const ready = asset?.status === "ready" && loaded;

  // Keyboard: undo/redo, hold \ for the original, [ and ] to move through images, I to inspect.
  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (isTyping(event.target) || useEditor.getState().inspecting) return;
      const mod = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      const editor = useEditor.getState();
      if (mod && key === "z") {
        event.preventDefault();
        if (event.shiftKey) editor.redo();
        else editor.undo();
      } else if (mod && key === "y") {
        event.preventDefault();
        editor.redo();
      } else if (!mod && event.key === "\\") {
        editor.setHoldBefore(true);
      } else if (!mod && (event.key === "[" || event.key === "]") && asset) {
        const index = list.findIndex((a) => a.id === asset.id);
        const next = list[index + (event.key === "]" ? 1 : -1)];
        if (next) select(next.id);
      } else if (!mod && key === "i" && asset?.status === "ready") {
        editor.setInspecting(true);
      }
    };
    const up = (event: KeyboardEvent) => {
      if (event.key === "\\") useEditor.getState().setHoldBefore(false);
    };
    const blur = () => useEditor.getState().setHoldBefore(false);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, [asset, list, select]);

  // Save pending edits when leaving the Studio.
  useEffect(() => () => void useEditor.getState().flush(), []);

  const dragProps = {
    onDragEnter: (event: DragEvent) => {
      if (!event.dataTransfer.types.includes("Files")) return;
      depth.current++;
      setDragging(true);
    },
    onDragLeave: () => {
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    },
    onDragOver: (event: DragEvent) => {
      if (event.dataTransfer.types.includes("Files")) event.preventDefault();
    },
    onDrop: (event: DragEvent) => {
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      if (event.dataTransfer.files.length) upload(event.dataTransfer.files);
    },
  };

  const picker = (
    <input
      ref={filePicker}
      type="file"
      multiple
      accept={accept}
      className="hidden"
      data-testid="empty-file-input"
      onChange={(event) => {
        if (event.target.files?.length) upload(event.target.files);
        event.target.value = "";
      }}
    />
  );

  const rejectedNote = rejected.length > 0 && (
    <div
      role="alert"
      className="flex items-center gap-2 border-b border-warn/40 bg-warn-soft px-3 py-1.5 text-[12px] text-warn"
    >
      <AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">
        Skipped {rejected.length === 1 ? rejected[0] : `${rejected.length} files`}: not a supported image
        type.
      </span>
      <button type="button" onClick={clearRejected} className="underline">
        Dismiss
      </button>
    </div>
  );

  if (isPending) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner label="Loading images" className="size-6 text-cyan" />
      </div>
    );
  }
  if (error) {
    const { message, fix } = errorMessage(error);
    return (
      <div className="grid h-full place-items-center p-6 text-center">
        <p className="flex items-center gap-2 text-[13.5px] text-err">
          <AlertTriangle className="size-4" aria-hidden="true" />
          {message}
        </p>
        {fix && <p className="text-[12.5px] text-fg-2">{fix}</p>}
      </div>
    );
  }
  if (!asset) {
    return (
      <div className="relative h-full" {...dragProps}>
        {rejectedNote}
        {picker}
        <EmptyState
          onPick={() => filePicker.current?.click()}
          accept={accept}
          maxMb={catalog?.max_upload_mb}
          maxMp={catalog?.max_input_megapixels}
        />
        {dragging && <DropOverlay />}
      </div>
    );
  }

  const specs = catalog?.ops ?? [];
  return (
    <div
      className="relative grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)_auto] max-md:h-auto max-md:min-h-full"
      data-testid="studio"
      {...dragProps}
    >
      <StudioHeader asset={asset} onDeleted={() => void navigate({ search: {}, replace: true })} />
      <div>{rejectedNote}</div>
      <div className="grid min-h-0 grid-cols-[220px_minmax(0,1fr)_300px] max-[1100px]:grid-cols-[minmax(0,1fr)_300px] max-md:grid-cols-1">
        <aside className="grid content-start gap-5 overflow-y-auto border-r border-line bg-panel p-3 max-[1100px]:hidden">
          <EditStack specs={specs} size={[asset.width, asset.height]} />
          <HistoryList />
        </aside>
        <div className="grid min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] max-md:h-[60vh]">
          {asset.status === "ready" ? <Stage asset={asset} /> : <NotReady asset={asset} />}
          {asset.status === "ready" && <CanvasBar asset={asset} />}
        </div>
        <aside
          className="flex min-h-0 flex-col border-l border-line bg-panel max-md:border-t max-md:border-l-0"
          aria-label="Tools"
        >
          <div
            role="tablist"
            aria-label="Tools"
            className="flex shrink-0 gap-1 border-b border-line px-2 pt-2"
          >
            {PANELS.map((p) => (
              <button
                key={p.id}
                type="button"
                role="tab"
                id={`tab-${p.id}`}
                aria-selected={panel === p.id}
                aria-controls="tool-panel"
                onClick={() => setPanel(p.id)}
                className={clsx(
                  "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-[12.5px] transition [&_svg]:size-3.5",
                  panel === p.id ? "border-cyan text-fg" : "border-transparent text-muted hover:text-fg",
                )}
              >
                {p.icon}
                {p.label}
              </button>
            ))}
          </div>
          <div
            id="tool-panel"
            role="tabpanel"
            aria-labelledby={`tab-${panel}`}
            className="min-h-0 flex-1 overflow-y-auto p-3"
          >
            {!ready || !catalog ? (
              <p className="text-[12.5px] text-muted">
                {asset.status === "failed"
                  ? "Nothing to edit."
                  : "The tools appear once the preview is ready."}
              </p>
            ) : panel === "adjust" ? (
              <AdjustPanel specs={specs} />
            ) : panel === "crop" ? (
              <CropPanel asset={asset} />
            ) : (
              <ExportPanel key={asset.id} asset={asset} formats={catalog.formats} />
            )}
          </div>
        </aside>
      </div>
      <Filmstrip assets={list} selectedId={asset.id} onSelect={select} onFiles={upload} accept={accept} />
      {dragging && <DropOverlay />}
      {inspecting && asset.status === "ready" && (
        <Inspector asset={asset} onClose={() => setInspecting(false)} />
      )}
    </div>
  );
}
