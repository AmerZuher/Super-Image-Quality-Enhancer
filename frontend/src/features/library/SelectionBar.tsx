import { FolderPlus, MapPinOff, RotateCcw, ShieldAlert, Tag, Trash2, X } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { type Album, type Asset, errorMessage } from "@/lib/api/client";
import {
  useAlbumMembers,
  useDeleteForever,
  useEditTags,
  useQuarantine,
  useRemoveLocation,
  useRestore,
} from "./api";

/** Actions for several selected images at once. */
export function SelectionBar({
  selected,
  albums,
  quarantineView,
  onClear,
}: {
  selected: Asset[];
  albums: Album[];
  quarantineView: boolean;
  onClear: () => void;
}) {
  const ids = selected.map((a) => a.id);
  const tags = useEditTags();
  const members = useAlbumMembers();
  const quarantine = useQuarantine();
  const restore = useRestore();
  const remove = useDeleteForever();
  const location = useRemoveLocation();
  const [tag, setTag] = useState("");
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(timer);
  }, [armed]);
  const manual = albums.filter((a) => a.kind === "manual");
  const withGps = selected.filter((a) => a.gps || a.has_gps).length;
  const addTag = (event: FormEvent) => {
    event.preventDefault();
    if (tag.trim()) tags.mutate({ ids, add: [tag.trim()] });
    setTag("");
  };
  const problem =
    tags.error ?? members.error ?? quarantine.error ?? restore.error ?? remove.error ?? location.error;
  const done = () => onClear();
  return (
    <div
      role="toolbar"
      aria-label="Selected images"
      className="sticky bottom-0 z-10 flex flex-wrap items-center gap-2 border-t border-cyan/40 bg-panel px-3 py-2 shadow-float"
    >
      <span className="text-[12.5px] font-semibold text-fg">{selected.length} selected</span>
      <Button size="sm" variant="ghost" icon={<X />} onClick={onClear}>
        Clear
      </Button>
      <span className="h-4 w-px bg-line-2" aria-hidden="true" />
      {quarantineView ? (
        <>
          <Button
            size="sm"
            icon={<RotateCcw />}
            loading={restore.isPending}
            onClick={() => restore.mutate(ids, { onSuccess: done })}
          >
            Restore
          </Button>
          <Button
            size="sm"
            variant="danger"
            icon={<Trash2 />}
            loading={remove.isPending}
            onClick={() => (armed ? remove.mutate(ids, { onSuccess: done }) : setArmed(true))}
          >
            {armed ? `Delete ${selected.length} for good?` : "Delete permanently"}
          </Button>
        </>
      ) : (
        <>
          <form onSubmit={addTag} className="flex items-center gap-1">
            <input
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              placeholder="Tag"
              aria-label="Tag to add to the selected images"
              maxLength={40}
              className="h-7 w-28 rounded-md border border-line-2 bg-panel-2 px-2 text-[12px] text-fg outline-none focus:border-cyan"
            />
            <Button size="sm" type="submit" icon={<Tag />} disabled={!tag.trim()} loading={tags.isPending}>
              Add tag
            </Button>
          </form>
          {manual.length > 0 && (
            <label className="flex items-center gap-1 text-[12px] text-fg-2">
              <FolderPlus className="size-3.5" aria-hidden="true" />
              <select
                className="h-7 rounded-md border border-line-2 bg-panel-2 px-1.5 text-[12px] text-fg"
                value=""
                onChange={(e) =>
                  e.target.value && members.mutate({ albumId: e.target.value, ids, action: "add" })
                }
                aria-label="Add the selected images to an album"
              >
                <option value="">Add to album…</option>
                {manual.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {withGps > 0 && (
            <Button
              size="sm"
              icon={<MapPinOff />}
              loading={location.isPending}
              onClick={() => location.mutate(ids, { onSuccess: done })}
            >
              Remove location ({withGps})
            </Button>
          )}
          <Button
            size="sm"
            variant="danger"
            icon={<ShieldAlert />}
            loading={quarantine.isPending}
            onClick={() => quarantine.mutate({ ids }, { onSuccess: done })}
          >
            Quarantine
          </Button>
        </>
      )}
      {problem && (
        <p role="alert" className="basis-full text-[12px] text-err">
          {errorMessage(problem).message} {errorMessage(problem).fix}
        </p>
      )}
    </div>
  );
}
