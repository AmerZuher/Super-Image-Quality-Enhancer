import { Link } from "@tanstack/react-router";
import { clsx } from "clsx";
import {
  CheckCircle2,
  ExternalLink,
  Folder,
  MapPin,
  MapPinOff,
  Plus,
  RotateCcw,
  ScanSearch,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Button, buttonClasses } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { type Album, type Asset, errorMessage } from "@/lib/api/client";
import { formatBytes } from "@/lib/format";
import { formatDimensions, megapixels } from "../studio/format";
import {
  useAlbumMembers,
  useAssetAlbums,
  useDeleteForever,
  useEditTags,
  useQuarantine,
  useRemoveLocation,
  useRestore,
} from "./api";
import { SWATCH } from "./Toolbar";

function osmLink([lat, lon]: number[]): string {
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=14/${lat}/${lon}`;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-2 py-1 text-[12px]">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-fg">{children}</dd>
    </div>
  );
}

function useArmed(): [boolean, (on: boolean) => void] {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(timer);
  }, [armed]);
  return [armed, setArmed];
}

export function TagEditor({ asset }: { asset: Asset }) {
  const edit = useEditTags();
  const [text, setText] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const tag = text.trim();
    if (!tag) return;
    edit.mutate({ ids: [asset.id], add: [tag] });
    setText("");
  };
  const auto = asset.auto_tags.filter((t) => !asset.tags.includes(t));
  return (
    <div className="grid gap-2">
      <ul className="flex flex-wrap gap-1" aria-label="Tags">
        {asset.tags.map((tag) => (
          <li key={tag}>
            <span className="inline-flex items-center gap-1 rounded-full border border-cyan/40 bg-cyan-soft py-0.5 pr-1 pl-2 text-[11.5px] text-cyan">
              {tag}
              <button
                type="button"
                onClick={() => edit.mutate({ ids: [asset.id], remove: [tag] })}
                aria-label={`Remove tag ${tag}`}
                className="rounded-full p-0.5 hover:bg-cyan/20"
              >
                <X className="size-2.5" />
              </button>
            </span>
          </li>
        ))}
        {auto.map((tag) => (
          <li key={tag}>
            <span
              className="inline-flex items-center gap-1 rounded-full border border-gold/40 bg-gold-soft py-0.5 pr-1 pl-1.5 text-[11.5px] text-gold"
              title="Chosen by CLIP"
            >
              <Sparkles className="size-2.5" aria-hidden="true" />
              {tag}
              <button
                type="button"
                onClick={() => edit.mutate({ ids: [asset.id], remove: [tag] })}
                aria-label={`Remove tag ${tag}`}
                className="rounded-full p-0.5 hover:bg-gold/20"
              >
                <X className="size-2.5" />
              </button>
            </span>
          </li>
        ))}
        {!asset.tags.length && !auto.length && <li className="text-[12px] text-muted">No tags yet.</li>}
      </ul>
      <form onSubmit={submit} className="flex gap-1.5">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add a tag"
          aria-label="Add a tag"
          maxLength={40}
          className="h-7 min-w-0 flex-1 rounded-md border border-line-2 bg-panel-2 px-2 text-[12px] text-fg outline-none focus:border-cyan"
        />
        <Button size="sm" type="submit" icon={<Plus />} disabled={!text.trim()} aria-label="Add tag" />
      </form>
    </div>
  );
}

function AlbumPicker({ asset, albums }: { asset: Asset; albums: Album[] }) {
  const manual = albums.filter((a) => a.kind === "manual");
  const { data: memberOf } = useAssetAlbums(asset.id);
  const members = useAlbumMembers();
  if (!manual.length)
    return <p className="text-[12px] text-muted">Make an album to collect images by hand.</p>;
  return (
    <ul className="grid gap-1">
      {manual.map((album) => {
        const inside = memberOf?.includes(album.id) ?? false;
        return (
          <li key={album.id}>
            <label className="flex cursor-pointer items-center gap-2 text-[12px] text-fg-2 hover:text-fg">
              <input
                type="checkbox"
                checked={inside}
                onChange={() =>
                  members.mutate({ albumId: album.id, ids: [asset.id], action: inside ? "remove" : "add" })
                }
                className="accent-[var(--cyan)]"
              />
              <Folder className="size-3.5 text-muted" aria-hidden="true" />
              {album.name}
            </label>
          </li>
        );
      })}
    </ul>
  );
}

export function Inspector({
  asset,
  albums,
  onSimilar,
  canSimilar,
}: {
  asset: Asset;
  albums: Album[];
  onSimilar: (id: string) => void;
  canSimilar: boolean;
}) {
  const quarantine = useQuarantine();
  const restore = useRestore();
  const remove = useDeleteForever();
  const location = useRemoveLocation();
  const [armed, setArmed] = useArmed();
  const exif = asset.exif as Record<string, string | undefined>;
  const camera = [exif.make, exif.model].filter(Boolean).join(" ");
  const exposure = [
    exif.exposure_time && `${exif.exposure_time} s`,
    exif.f_number && `f/${exif.f_number.replace(/^f\//, "")}`,
    exif.iso && `ISO ${exif.iso}`,
    exif.focal_length,
  ]
    .filter(Boolean)
    .join(" · ");
  const quarantined = Boolean(asset.quarantined_at);
  const sharpness = asset.sharpness ?? null;
  const problem = location.error ?? quarantine.error ?? restore.error ?? remove.error;
  return (
    <div className="grid gap-4" data-testid="library-inspector">
      <div className="overflow-hidden rounded-lg border border-line bg-stage">
        {asset.preview_url ? (
          <img
            src={asset.preview_url}
            alt={asset.original_name}
            className="max-h-[260px] w-full object-contain"
          />
        ) : (
          <div className="grid h-40 place-items-center text-[12px] text-muted">No preview yet</div>
        )}
      </div>
      <div>
        <h2 className="text-[14px] font-semibold break-words text-fg">{asset.original_name}</h2>
        <p className="font-mono text-[11.5px] text-muted">
          {formatDimensions(asset.width, asset.height)} · {megapixels(asset.width, asset.height)} ·{" "}
          {asset.format.toUpperCase()} · {formatBytes(asset.size_bytes)}
        </p>
        {quarantined && (
          <Chip tone="warn" icon={<ShieldAlert />} className="mt-1.5">
            In quarantine: {asset.quarantine_reason}
          </Chip>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {!quarantined && (
          <>
            <Link to="/studio" search={{ asset: asset.id }} className={buttonClasses("outline", "sm")}>
              <SlidersHorizontal aria-hidden="true" />
              Edit in Studio
            </Link>
            <Link to="/ai-lab" search={{ asset: asset.id }} className={buttonClasses("ai", "sm")}>
              <Sparkles aria-hidden="true" />
              AI Lab
            </Link>
            <Button
              size="sm"
              icon={<ScanSearch />}
              onClick={() => onSimilar(asset.id)}
              disabled={!canSimilar}
              title={canSimilar ? undefined : "Download CLIP search to find similar images"}
            >
              Find similar
            </Button>
          </>
        )}
      </div>

      <section className="grid gap-1.5">
        <h3 className="eyebrow">Tags</h3>
        <TagEditor asset={asset} />
      </section>

      <section>
        <h3 className="eyebrow mb-1">Details</h3>
        <dl className="divide-y divide-line">
          {asset.taken_at && <Row label="Taken">{new Date(asset.taken_at).toLocaleString()}</Row>}
          {asset.created_at && <Row label="Added">{new Date(asset.created_at).toLocaleString()}</Row>}
          {camera && <Row label="Camera">{camera}</Row>}
          {exif.lens && <Row label="Lens">{exif.lens}</Row>}
          {exposure && <Row label="Exposure">{exposure}</Row>}
          {sharpness !== null && (
            <Row label="Sharpness">
              <span className="flex items-center gap-2">
                <span className="h-1.5 w-20 overflow-hidden rounded-full bg-[var(--cyan-track)]">
                  <span
                    className="block h-full rounded-full bg-cyan"
                    style={{ width: `${Math.round(sharpness * 100)}%` }}
                  />
                </span>
                <span className="font-mono text-[11px]">{sharpness.toFixed(2)}</span>
                {sharpness <= 0.3 && <span className="text-warn">blurry</span>}
              </span>
            </Row>
          )}
          {asset.color && (
            <Row label="Colour">
              <span className="flex items-center gap-1.5 capitalize">
                <span className={clsx("size-3 rounded-full", SWATCH[asset.color as keyof typeof SWATCH])} />
                {asset.color}
              </span>
            </Row>
          )}
          {asset.source?.kind === "folder" && (
            <Row label="Imported from">
              <span className="font-mono text-[11px]">{String(asset.source.path)}</span>
            </Row>
          )}
          {asset.derivation?.kind === "location_removed" && <Row label="Made by">Removing location</Row>}
        </dl>
      </section>

      <section className="grid gap-1.5">
        <h3 className="eyebrow">Location</h3>
        {asset.gps ? (
          <div className="grid gap-2 rounded-lg border border-warn/40 bg-warn-soft p-2.5 text-[12px]">
            <p className="flex items-center gap-1.5 text-warn">
              <MapPin className="size-3.5" aria-hidden="true" />
              Saved where it was taken
            </p>
            <p className="font-mono text-fg">{asset.gps.map((v) => v.toFixed(5)).join(", ")}</p>
            <div className="flex flex-wrap gap-1.5">
              <a
                href={osmLink(asset.gps)}
                target="_blank"
                rel="noreferrer noopener"
                className={buttonClasses("outline", "sm")}
              >
                Open map <ExternalLink className="size-3" aria-hidden="true" />
              </a>
              {!quarantined && (
                <Button
                  size="sm"
                  icon={<MapPinOff />}
                  loading={location.isPending}
                  onClick={() => location.mutate([asset.id])}
                >
                  Remove location
                </Button>
              )}
            </div>
            {location.isSuccess && (
              <p className="flex items-center gap-1 text-ok">
                <CheckCircle2 className="size-3.5" aria-hidden="true" />
                Making a copy without location; the original goes to quarantine.
              </p>
            )}
          </div>
        ) : (
          <p className="flex items-center gap-1.5 text-[12px] text-fg-2">
            <MapPinOff className="size-3.5 text-muted" aria-hidden="true" />
            {asset.has_gps ? "Has GPS data without a usable position." : "No location saved."}
          </p>
        )}
      </section>

      {!quarantined && (
        <section className="grid gap-1.5">
          <h3 className="eyebrow">Albums</h3>
          <AlbumPicker asset={asset} albums={albums} />
        </section>
      )}

      <div className="flex flex-wrap gap-1.5 border-t border-line pt-3">
        {quarantined ? (
          <>
            <Button
              size="sm"
              icon={<RotateCcw />}
              loading={restore.isPending}
              onClick={() => restore.mutate([asset.id])}
            >
              Restore
            </Button>
            <Button
              size="sm"
              variant="danger"
              icon={<Trash2 />}
              loading={remove.isPending}
              onClick={() => (armed ? remove.mutate([asset.id]) : setArmed(true))}
            >
              {armed ? "Delete for good?" : "Delete permanently"}
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="danger"
            icon={<ShieldAlert />}
            loading={quarantine.isPending}
            onClick={() => quarantine.mutate({ ids: [asset.id] })}
          >
            Move to quarantine
          </Button>
        )}
      </div>
      {problem && (
        <p role="alert" className="text-[12px] text-err">
          {errorMessage(problem).message} {errorMessage(problem).fix}
        </p>
      )}
    </div>
  );
}
