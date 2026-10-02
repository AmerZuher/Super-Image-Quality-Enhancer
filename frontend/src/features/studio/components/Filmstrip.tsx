import { clsx } from "clsx";
import { AlertTriangle, ImagePlus, Sparkles, X } from "lucide-react";
import { useRef } from "react";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Spinner } from "@/components/ui/Spinner";
import type { Asset } from "@/lib/api/client";
import { useUploads } from "../uploads";

export function Filmstrip({
  assets,
  selectedId,
  onSelect,
  onFiles,
  accept,
}: {
  assets: Asset[];
  selectedId: string | undefined;
  onSelect: (id: string) => void;
  onFiles: (files: FileList) => void;
  accept: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const items = useUploads((s) => s.items);
  const uploads = items.filter((u) => u.state !== "done");
  const dismiss = useUploads((s) => s.dismiss);
  return (
    <nav
      aria-label="Images"
      className="flex min-w-0 gap-2 overflow-x-auto border-t border-line bg-panel px-3 py-2.5"
    >
      <button
        type="button"
        onClick={() => input.current?.click()}
        className="grid h-[58px] w-[84px] shrink-0 place-items-center content-center gap-0.5 rounded-md border border-dashed border-line-2 text-[11px] text-fg-2 transition hover:border-cyan hover:text-cyan"
      >
        <ImagePlus className="size-4" aria-hidden="true" />
        Add images
      </button>
      <input
        ref={input}
        type="file"
        multiple
        accept={accept}
        className="hidden"
        data-testid="file-input"
        onChange={(event) => {
          if (event.target.files?.length) onFiles(event.target.files);
          event.target.value = "";
        }}
      />
      {uploads.map((u) => (
        <div
          key={u.key}
          className="grid h-[58px] w-[140px] shrink-0 content-center gap-1 rounded-md border border-line bg-panel-2 px-2"
          title={u.error ? `${u.error.message} ${u.error.fix ?? ""}` : u.name}
        >
          <div className="flex items-center gap-1">
            <span className="min-w-0 flex-1 truncate text-[11px] text-fg">{u.name}</span>
            {u.state === "failed" && (
              <button
                type="button"
                onClick={() => dismiss(u.key)}
                className="text-muted hover:text-fg"
                aria-label={`Dismiss ${u.name}`}
              >
                <X className="size-3" />
              </button>
            )}
          </div>
          {u.state === "failed" ? (
            <span className="flex items-center gap-1 truncate text-[10.5px] text-err">
              <AlertTriangle className="size-3 shrink-0" aria-hidden="true" />
              {u.error?.message ?? "Upload failed"}
            </span>
          ) : (
            <>
              <ProgressBar value={u.size ? u.loaded / u.size : 0} label={`Uploading ${u.name}`} />
              <span className="text-[10.5px] text-muted">
                {u.state === "waiting" ? "Waiting" : "Uploading"}
              </span>
            </>
          )}
        </div>
      ))}
      <ul className="flex gap-2">
        {assets.map((asset) => {
          const selected = asset.id === selectedId;
          return (
            <li key={asset.id} className="shrink-0">
              <button
                type="button"
                onClick={() => onSelect(asset.id)}
                aria-current={selected ? "true" : undefined}
                aria-label={`${asset.original_name}${asset.parent_id ? ", AI result" : ""}${asset.status === "ready" ? "" : `, ${asset.status}`}`}
                title={asset.original_name}
                className={clsx(
                  "relative block h-[58px] w-[84px] overflow-hidden rounded-md border bg-panel-2 transition",
                  selected
                    ? "border-cyan ring-1 ring-cyan"
                    : "border-line opacity-80 hover:border-line-2 hover:opacity-100",
                )}
              >
                {asset.parent_id && (
                  <span
                    className="absolute top-1 right-1 z-10 flex items-center gap-0.5 rounded bg-[var(--overlay)] px-1 font-mono text-[9px] font-semibold text-gold backdrop-blur-sm"
                    title={`Made with ${String(asset.derivation?.model_name ?? "an AI model")}`}
                  >
                    <Sparkles className="size-2.5" aria-hidden="true" />
                    AI
                  </span>
                )}
                {asset.thumb_url ? (
                  <img src={asset.thumb_url} alt="" loading="lazy" className="size-full object-cover" />
                ) : asset.status === "failed" ? (
                  <span className="grid size-full place-items-center content-center gap-0.5 text-[10px] text-err">
                    <AlertTriangle className="size-3.5" aria-hidden="true" />
                    Failed
                  </span>
                ) : (
                  <span className="grid size-full place-items-center content-center gap-1 text-[10px] text-muted">
                    <Spinner className="size-3.5" />
                    Preparing
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
