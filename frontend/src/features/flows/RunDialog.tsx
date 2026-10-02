import { clsx } from "clsx";
import { FlaskConical, Play } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { useAlbums } from "@/features/library/api";
import { INPUT, RulesEditor } from "@/features/library/RulesEditor";
import { useLibraryStore } from "@/features/library/store";
import { errorMessage, type Flow, type FlowRun, type RuleSet } from "@/lib/api/client";
import { useRunFlow } from "./api";

type SourceKind = "assets" | "album" | "rules" | "all";

export const DRY_RUN_IMAGES = 10;

/** Choose which images a flow runs on, and whether to try it first. */
export function RunDialog({
  flow,
  open,
  onClose,
  onStarted,
  preferSelection,
}: {
  flow: Flow;
  open: boolean;
  onClose: () => void;
  onStarted: (run: FlowRun) => void;
  preferSelection?: boolean;
}) {
  const selection = useLibraryStore((s) => s.selected);
  const { data: albums } = useAlbums();
  const run = useRunFlow();
  const [kind, setKind] = useState<SourceKind>("all");
  const [albumId, setAlbumId] = useState("");
  const [rules, setRules] = useState<RuleSet>({ match: "all", rules: [] });
  const [dryRun, setDryRun] = useState(!flow.last_run);
  const [limit, setLimit] = useState("");

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset when the dialog opens, not on every change
  useEffect(() => {
    if (!open) return;
    setKind(
      selection.length && (preferSelection || kind === "assets")
        ? "assets"
        : kind === "assets"
          ? "all"
          : kind,
    );
    setDryRun(!flow.last_run);
    run.reset();
  }, [open]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const source =
      kind === "assets"
        ? { kind, asset_ids: selection }
        : kind === "album"
          ? { kind, album_id: albumId }
          : kind === "rules"
            ? { kind, rules }
            : { kind };
    run.mutate(
      { id: flow.id, source, dry_run: dryRun, limit: limit ? Number(limit) : null },
      { onSuccess: onStarted },
    );
  };

  const options: { kind: SourceKind; label: string; help: string; disabled?: boolean }[] = [
    {
      kind: "assets",
      label: `The ${selection.length.toLocaleString()} image${selection.length === 1 ? "" : "s"} selected in the Library`,
      help: "Select images in the Library first, then come back here.",
      disabled: selection.length === 0,
    },
    { kind: "album", label: "An album", help: "Every image in it, including smart albums." },
    { kind: "rules", label: "Images that match rules", help: "Like a smart album, just for this run." },
    { kind: "all", label: "Every image in the Library", help: "Quarantined images are left out." },
  ];
  const problem = run.error ? errorMessage(run.error) : null;
  const ready =
    flow.problems.length === 0 &&
    (kind !== "album" || albumId) &&
    (kind !== "rules" || (rules.rules ?? []).length > 0) &&
    (kind !== "assets" || selection.length > 0);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={`Run ${flow.name}`}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={flow.ai ? "ai" : "primary"}
            type="submit"
            form="run-form"
            icon={dryRun ? <FlaskConical /> : <Play />}
            loading={run.isPending}
            disabled={!ready}
          >
            {dryRun ? "Start dry run" : "Run flow"}
          </Button>
        </div>
      }
    >
      <form id="run-form" onSubmit={submit} className="grid gap-4">
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-[12.5px] text-fg-2">Run it on</legend>
          {options.map((option) => (
            <label
              key={option.kind}
              className={clsx(
                "flex cursor-pointer items-start gap-2 rounded-lg border border-line p-2.5",
                "has-[:checked]:border-cyan has-[:checked]:bg-cyan-soft",
                option.disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <input
                type="radio"
                name="source"
                className="mt-0.5 accent-[var(--cyan)]"
                checked={kind === option.kind}
                disabled={option.disabled}
                onChange={() => setKind(option.kind)}
              />
              <span className="grid min-w-0 flex-1 gap-1.5">
                <span className="text-[12.5px] font-medium text-fg">{option.label}</span>
                <span className="text-[12px] text-fg-2">{option.help}</span>
                {option.kind === "album" && kind === "album" && (
                  <select
                    className={INPUT}
                    value={albumId}
                    onChange={(e) => setAlbumId(e.target.value)}
                    aria-label="Album"
                  >
                    <option value="">Choose an album…</option>
                    {(albums ?? []).map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.count.toLocaleString()})
                      </option>
                    ))}
                  </select>
                )}
                {option.kind === "rules" && kind === "rules" && (
                  <RulesEditor value={rules} onChange={setRules} intro="Images that match" />
                )}
              </span>
            </label>
          ))}
        </fieldset>

        <label className="flex items-start gap-2 rounded-lg border border-line p-2.5">
          <input
            type="checkbox"
            className="mt-0.5 accent-[var(--cyan)]"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
          />
          <span className="grid">
            <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-fg">
              <FlaskConical className="size-3.5 text-cyan" aria-hidden="true" />
              Dry run first
            </span>
            <span className="text-[12px] text-fg-2">
              Try it on {DRY_RUN_IMAGES} images. Files are exported to a separate “dry run” folder so you can
              check them; tags, albums, quarantine and saving to the Library are only simulated.
            </span>
          </span>
        </label>

        <label className="grid gap-1 text-[12px] text-fg-2">
          <span className="text-fg">At most this many images</span>
          <input
            type="number"
            min={1}
            className={clsx(INPUT, "w-32")}
            value={limit}
            placeholder={dryRun ? String(DRY_RUN_IMAGES) : "All"}
            onChange={(e) => setLimit(e.target.value)}
          />
        </label>

        {flow.problems.length > 0 && (
          <p role="alert" className="text-[12px] text-err">
            This flow can't run yet: {flow.problems[0]?.message}.
          </p>
        )}
        {problem && (
          <p role="alert" className="text-[12px] text-err">
            {problem.message} {problem.fix}
          </p>
        )}
      </form>
    </Drawer>
  );
}
