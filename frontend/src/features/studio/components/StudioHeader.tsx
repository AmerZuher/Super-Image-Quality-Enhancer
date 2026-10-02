import { Link } from "@tanstack/react-router";
import { clsx } from "clsx";
import {
  AlertTriangle,
  CheckCircle2,
  CloudUpload,
  Download,
  MapPin,
  Redo2,
  RotateCcw,
  ScanSearch,
  Sparkles,
  Trash2,
  Undo2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Kbd } from "@/components/ui/Kbd";
import { Spinner } from "@/components/ui/Spinner";
import type { Asset } from "@/lib/api/client";
import { formatBytes } from "@/lib/format";
import { useDeleteAsset } from "../api";
import { EMPTY_DOC, isEdited } from "../doc";
import { formatDimensions, megapixels } from "../format";
import { useEditor } from "../store";

function SaveStatus() {
  const save = useEditor((s) => s.save);
  const error = useEditor((s) => s.saveError);
  const flush = useEditor((s) => s.flush);
  if (save === "error") {
    return (
      <button
        type="button"
        onClick={() => void flush()}
        title={error ?? undefined}
        className="flex items-center gap-1.5 rounded-full border border-err/45 bg-err-soft px-2 py-0.5 text-[11.5px] font-medium text-err"
      >
        <AlertTriangle className="size-3.5" aria-hidden="true" />
        Not saved, retry
      </button>
    );
  }
  if (save === "saved") {
    return (
      <Chip tone="neutral" icon={<CheckCircle2 />}>
        Saved
      </Chip>
    );
  }
  return (
    <Chip tone="cyan" icon={save === "saving" ? <Spinner className="size-3.5" /> : <CloudUpload />}>
      Saving
    </Chip>
  );
}

function DeleteButton({ asset, onDeleted }: { asset: Asset; onDeleted: () => void }) {
  const remove = useDeleteAsset();
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(timer);
  }, [armed]);
  return (
    <Button
      size="sm"
      variant={armed ? "danger" : "ghost"}
      icon={<Trash2 />}
      loading={remove.isPending}
      onClick={() => {
        if (!armed) return setArmed(true);
        remove.mutate(asset.id, { onSuccess: onDeleted });
      }}
      aria-label={armed ? `Confirm deleting ${asset.original_name}` : `Delete ${asset.original_name}`}
    >
      {armed ? "Click again to delete" : <span className="max-xl:sr-only">Delete</span>}
    </Button>
  );
}

export function StudioHeader({ asset, onDeleted }: { asset: Asset; onDeleted: () => void }) {
  const doc = useEditor((s) => s.doc);
  const canUndo = useEditor((s) => s.past.length > 0);
  const canRedo = useEditor((s) => s.future.length > 0);
  const undo = useEditor((s) => s.undo);
  const redo = useEditor((s) => s.redo);
  const update = useEditor((s) => s.update);
  const setInspecting = useEditor((s) => s.setInspecting);
  const ready = asset.status === "ready";
  return (
    <header className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-panel px-3 py-2">
      <div className="min-w-[min(100%,16rem)] flex-1">
        <h2 className="truncate text-[14px] font-semibold text-fg" title={asset.original_name}>
          {asset.original_name}
        </h2>
        <p className="flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted">
          <span className="font-mono">{formatDimensions(asset.width, asset.height)}</span>
          <span>{megapixels(asset.width, asset.height)}</span>
          <span className="uppercase">{asset.format}</span>
          {asset.bit_depth === 16 && <span>16-bit</span>}
          <span>{formatBytes(asset.size_bytes)}</span>
          {asset.parent_id && (
            <span className="flex items-center gap-1 text-gold">
              <Sparkles className="size-3" aria-hidden="true" />
              {String(asset.derivation?.model_name ?? "AI result")}
            </span>
          )}
          {asset.has_gps && (
            <span className="flex items-center gap-1 text-warn" title="This photo records where it was taken">
              <MapPin className="size-3" aria-hidden="true" />
              Has GPS location
            </span>
          )}
        </p>
      </div>
      {ready && <SaveStatus />}
      <div className="flex items-center gap-1">
        <Button
          size="sm"
          variant="ghost"
          icon={<Undo2 />}
          onClick={undo}
          disabled={!canUndo}
          aria-label="Undo"
          title="Undo (Ctrl+Z)"
        />
        <Button
          size="sm"
          variant="ghost"
          icon={<Redo2 />}
          onClick={redo}
          disabled={!canRedo}
          aria-label="Redo"
          title="Redo (Ctrl+Shift+Z)"
        />
        <Button
          size="sm"
          variant="ghost"
          icon={<RotateCcw />}
          disabled={!isEdited(doc)}
          onClick={() => update("Reset all", () => EMPTY_DOC)}
        >
          <span className="max-xl:sr-only">Reset all</span>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon={<ScanSearch />}
          disabled={!ready}
          onClick={() => setInspecting(true)}
          title="Inspect at full resolution (I)"
        >
          <span className="max-xl:sr-only">Inspect</span>
          <Kbd className="max-xl:hidden">I</Kbd>
        </Button>
        <Link
          to="/ai-lab"
          search={asset.parent_id ? { asset: asset.parent_id, result: asset.id } : { asset: asset.id }}
          className="inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-xs text-gold transition hover:bg-gold-soft"
          title={
            asset.parent_id ? "Compare with the original in AI Lab" : "Upscale, denoise or cut out in AI Lab"
          }
        >
          <Sparkles className="size-4" aria-hidden="true" />
          <span className="max-xl:sr-only">{asset.parent_id ? "Compare" : "AI Lab"}</span>
        </Link>
        <a
          href={asset.original_url}
          download={asset.original_name}
          className={clsx(
            "inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-xs text-fg-2 transition hover:bg-panel-2 hover:text-fg",
          )}
          title="Download the original file"
        >
          <Download className="size-4" aria-hidden="true" />
          <span className="max-xl:sr-only">Original</span>
        </a>
        <DeleteButton asset={asset} onDeleted={onDeleted} />
      </div>
    </header>
  );
}
