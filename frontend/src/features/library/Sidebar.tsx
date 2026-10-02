import { clsx } from "clsx";
import {
  AlertTriangle,
  Copy,
  Folder,
  FolderInput,
  Images,
  type LucideIcon,
  Pencil,
  Plus,
  RefreshCw,
  ShieldAlert,
  Wand2,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { Album, ImportStatus, LibraryStatus } from "@/lib/api/client";
import { relativeTime } from "@/lib/format";
import { useImportStatus, useScanImport, type View } from "./api";

export interface Place {
  view: View;
  albumId?: string;
}

function Item({
  icon: Icon,
  label,
  count,
  active,
  tone,
  onClick,
  onEdit,
}: {
  icon: LucideIcon;
  label: string;
  count?: number;
  active: boolean;
  tone?: "warn";
  onClick: () => void;
  onEdit?: () => void;
}) {
  return (
    <li className="group/item relative">
      <button
        type="button"
        onClick={onClick}
        aria-current={active ? "page" : undefined}
        className={clsx(
          "flex w-full items-center gap-2 rounded-md py-1.5 pr-2 pl-2 text-left text-[12.5px] transition [&_svg]:size-3.5",
          onEdit && "pr-8",
          active ? "bg-panel-2 font-medium text-fg" : "text-fg-2 hover:bg-panel-2/60 hover:text-fg",
        )}
      >
        <Icon className={clsx("shrink-0", tone === "warn" && count ? "text-warn" : "text-muted")} />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {count !== undefined && (
          <span
            className={clsx("font-mono text-[11px]", tone === "warn" && count ? "text-warn" : "text-muted")}
          >
            {count.toLocaleString()}
          </span>
        )}
      </button>
      {onEdit && (
        <button
          type="button"
          onClick={onEdit}
          aria-label={`Edit album ${label}`}
          className="absolute top-1/2 right-1 hidden -translate-y-1/2 rounded p-1 text-muted group-hover/item:block hover:text-fg focus-visible:block"
        >
          <Pencil className="size-3" />
        </button>
      )}
    </li>
  );
}

export function Sidebar({
  place,
  onPlace,
  status,
  albums,
  onNewAlbum,
  onEditAlbum,
}: {
  place: Place;
  onPlace: (place: Place) => void;
  status: LibraryStatus | undefined;
  albums: Album[];
  onNewAlbum: () => void;
  onEditAlbum: (album: Album) => void;
}) {
  const counts = status?.counts;
  return (
    <nav aria-label="Library views" className="flex min-h-0 flex-col gap-4 overflow-y-auto p-2.5">
      <ul className="grid gap-0.5">
        <Item
          icon={Images}
          label="All images"
          count={counts?.all}
          active={place.view === "all"}
          onClick={() => onPlace({ view: "all" })}
        />
        <Item
          icon={Copy}
          label="Duplicates"
          count={counts?.duplicates}
          tone="warn"
          active={place.view === "duplicates"}
          onClick={() => onPlace({ view: "duplicates" })}
        />
        <Item
          icon={ShieldAlert}
          label="Quarantine"
          count={counts?.quarantine}
          active={place.view === "quarantine"}
          onClick={() => onPlace({ view: "quarantine" })}
        />
      </ul>
      <div>
        <div className="mb-1 flex items-center justify-between px-2">
          <h3 className="eyebrow">Albums</h3>
          <button
            type="button"
            onClick={onNewAlbum}
            className="rounded p-0.5 text-muted hover:text-cyan"
            aria-label="New album"
            title="New album"
          >
            <Plus className="size-3.5" />
          </button>
        </div>
        <ul className="grid gap-0.5">
          {albums.map((album) => (
            <Item
              key={album.id}
              icon={album.kind === "smart" ? Wand2 : Folder}
              label={album.name}
              count={album.count}
              active={place.view === "album" && place.albumId === album.id}
              onClick={() => onPlace({ view: "album", albumId: album.id })}
              onEdit={() => onEditAlbum(album)}
            />
          ))}
          {!albums.length && <li className="px-2 text-[12px] text-muted">No albums yet.</li>}
        </ul>
      </div>
      <ImportCard />
    </nav>
  );
}

function importLine(status: ImportStatus): string {
  if (status.available === false) return "Folder not found";
  if (!status.last_scan) return status.enabled ? "Not checked yet" : "Automatic checks are off";
  return `Checked ${relativeTime(status.last_scan)}`;
}

function ImportCard() {
  const { data: status } = useImportStatus();
  const scan = useScanImport();
  if (!status) return null;
  return (
    <section
      aria-labelledby="import-folder"
      className="mt-auto grid gap-2 rounded-lg border border-line bg-panel-2 p-2.5"
    >
      <div className="flex items-center gap-2">
        <FolderInput className="size-3.5 text-cyan" aria-hidden="true" />
        <h3 id="import-folder" className="text-[12px] font-semibold text-fg">
          Import folder
        </h3>
      </div>
      <p className="font-mono text-[11px] break-all text-fg-2">{status.folder}</p>
      <p className="text-[11.5px] text-muted">
        {importLine(status)}
        {status.enabled && ` · every ${status.every_seconds} s`}
      </p>
      <dl className="grid grid-cols-3 gap-1 text-center text-[11px]">
        {(
          [
            ["Imported", status.imported],
            ["Waiting", status.waiting],
            ["Failed", status.failed],
          ] as const
        ).map(([label, n]) => (
          <div key={label} className="rounded border border-line px-1 py-1">
            <dt className="text-muted">{label}</dt>
            <dd className={clsx("font-mono", label === "Failed" && n ? "text-err" : "text-fg")}>{n}</dd>
          </div>
        ))}
      </dl>
      {status.failures.length > 0 && (
        <details className="text-[11px]">
          <summary className="flex cursor-pointer items-center gap-1 text-err">
            <AlertTriangle className="size-3" aria-hidden="true" />
            {status.failures.length} couldn't be imported
          </summary>
          <ul className="mt-1 grid gap-1">
            {status.failures.map((f) => (
              <li key={f.path} className="text-fg-2">
                <span className="font-mono break-all text-fg">{f.path}</span>: {f.message}
              </li>
            ))}
          </ul>
        </details>
      )}
      <Button size="sm" icon={<RefreshCw />} loading={scan.isPending} onClick={() => scan.mutate()}>
        Check now
      </Button>
    </section>
  );
}
