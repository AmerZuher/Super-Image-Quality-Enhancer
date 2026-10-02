import { Folder, Trash2, Wand2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { type Album, errorMessage, type RuleSet } from "@/lib/api/client";
import { useDeleteAlbum, useSaveAlbum } from "./api";
import { INPUT, RulesEditor } from "./RulesEditor";

export interface AlbumDraft {
  id?: string;
  name: string;
  kind: Album["kind"];
  rules: RuleSet;
}

export function AlbumEditor({ draft, onClose }: { draft: AlbumDraft | null; onClose: () => void }) {
  const [state, setState] = useState<AlbumDraft | null>(draft);
  const save = useSaveAlbum();
  const remove = useDeleteAlbum();
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    setState(draft);
    setArmed(false);
    save.reset();
  }, [draft, save.reset]);
  if (!state) return null;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(state, { onSuccess: onClose });
  };
  const editing = Boolean(state.id);
  const problem = save.error ?? remove.error;
  return (
    <Drawer
      open
      onClose={onClose}
      title={editing ? `Edit ${state.name}` : "New album"}
      footer={
        <div className="flex items-center justify-between gap-2">
          {editing ? (
            <Button
              variant="danger"
              size="sm"
              icon={<Trash2 />}
              loading={remove.isPending}
              onClick={() =>
                armed ? remove.mutate(state.id as string, { onSuccess: onClose }) : setArmed(true)
              }
            >
              {armed ? "Delete album?" : "Delete album"}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              type="submit"
              form="album-form"
              loading={save.isPending}
              disabled={!state.name.trim()}
            >
              {editing ? "Save album" : "Create album"}
            </Button>
          </div>
        </div>
      }
    >
      <form id="album-form" onSubmit={submit} className="grid gap-4">
        <label className="grid gap-1 text-[12.5px] text-fg-2">
          Name
          <input
            className={INPUT}
            value={state.name}
            maxLength={120}
            onChange={(e) => setState({ ...state, name: e.target.value })}
            placeholder="Desktop wallpapers"
            // biome-ignore lint/a11y/noAutofocus: the drawer opens to name the album
            autoFocus
          />
        </label>
        {!editing && (
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-[12.5px] text-fg-2">Kind</legend>
            {(
              [
                [
                  "smart",
                  Wand2,
                  "Smart",
                  "Fills itself with every image that matches rules. Nothing is copied.",
                ],
                ["manual", Folder, "Hand-picked", "You add and remove images yourself."],
              ] as const
            ).map(([kind, Icon, label, help]) => (
              <label
                key={kind}
                className="flex cursor-pointer items-start gap-2 rounded-lg border border-line p-2.5 has-[:checked]:border-cyan has-[:checked]:bg-cyan-soft"
              >
                <input
                  type="radio"
                  name="kind"
                  checked={state.kind === kind}
                  onChange={() => setState({ ...state, kind })}
                  className="mt-0.5 accent-[var(--cyan)]"
                />
                <Icon className="mt-0.5 size-4 text-cyan" aria-hidden="true" />
                <span className="grid">
                  <span className="text-[12.5px] font-medium text-fg">{label}</span>
                  <span className="text-[12px] text-fg-2">{help}</span>
                </span>
              </label>
            ))}
          </fieldset>
        )}
        {state.kind === "smart" && (
          <RulesEditor
            value={state.rules}
            onChange={(rules) => setState({ ...state, rules })}
            intro="Include images that match"
          />
        )}
        {problem && (
          <p role="alert" className="text-[12px] text-err">
            {errorMessage(problem).message} {errorMessage(problem).fix}
          </p>
        )}
      </form>
    </Drawer>
  );
}
