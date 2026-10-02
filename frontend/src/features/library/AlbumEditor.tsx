import { Folder, Plus, Trash2, Wand2, X } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { type Album, errorMessage, type Rule, type RuleSet } from "@/lib/api/client";
import { useDeleteAlbum, useSaveAlbum } from "./api";
import { defaultRule, describeRule, FIELDS, OP_LABELS, type RuleField, type RuleOp } from "./rules";

export interface AlbumDraft {
  id?: string;
  name: string;
  kind: Album["kind"];
  rules: RuleSet;
}

const INPUT =
  "h-8 rounded-md border border-line-2 bg-panel-2 px-2 text-[12.5px] text-fg outline-none focus:border-cyan";

function ValueInput({ rule, onChange }: { rule: Rule; onChange: (value: Rule["value"]) => void }) {
  const spec = FIELDS[rule.field];
  if (spec.kind === "boolean") {
    return (
      <select
        className={INPUT}
        value={rule.value ? "yes" : "no"}
        onChange={(e) => onChange(e.target.value === "yes")}
        aria-label="Value"
      >
        <option value="yes">Yes</option>
        <option value="no">No</option>
      </select>
    );
  }
  if (spec.kind === "choice") {
    return (
      <select
        className={INPUT}
        value={String(rule.value)}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Value"
      >
        {spec.choices?.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    );
  }
  if (spec.kind === "number") {
    return (
      <span className="flex items-center gap-1">
        <input
          type="number"
          className={`${INPUT} w-24`}
          value={Number(rule.value)}
          step={rule.field === "sharpness" || rule.field === "aspect" ? 0.05 : 1}
          onChange={(e) => onChange(Number(e.target.value))}
          aria-label="Value"
        />
        {spec.unit && <span className="text-[11.5px] text-muted">{spec.unit}</span>}
      </span>
    );
  }
  return (
    <input
      type={spec.kind === "date" ? "date" : "text"}
      className={`${INPUT} w-36`}
      value={String(rule.value)}
      placeholder={spec.placeholder}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Value"
    />
  );
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
  const rules = state.rules.rules ?? [];
  const setRules = (next: Rule[]) => setState({ ...state, rules: { ...state.rules, rules: next } });
  const update = (index: number, rule: Rule) => setRules(rules.map((r, i) => (i === index ? rule : r)));
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
          <section className="grid gap-2" aria-label="Rules">
            <div className="flex items-center gap-2 text-[12.5px] text-fg-2">
              Include images that match
              <select
                className={INPUT}
                value={state.rules.match}
                onChange={(e) =>
                  setState({ ...state, rules: { ...state.rules, match: e.target.value as "all" | "any" } })
                }
                aria-label="Match"
              >
                <option value="all">all rules</option>
                <option value="any">any rule</option>
              </select>
            </div>
            <ul className="grid gap-2">
              {rules.map((rule, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: rules are edited in place by position
                <li key={index} className="grid gap-1.5 rounded-lg border border-line bg-panel-2 p-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <select
                      className={INPUT}
                      value={rule.field}
                      onChange={(e) => update(index, defaultRule(e.target.value as RuleField))}
                      aria-label="Field"
                    >
                      {Object.entries(FIELDS).map(([field, spec]) => (
                        <option key={field} value={field}>
                          {spec.label}
                        </option>
                      ))}
                    </select>
                    {FIELDS[rule.field].ops.length > 1 && (
                      <select
                        className={INPUT}
                        value={rule.op}
                        onChange={(e) => update(index, { ...rule, op: e.target.value as RuleOp })}
                        aria-label="Comparison"
                      >
                        {FIELDS[rule.field].ops.map((op) => (
                          <option key={op} value={op}>
                            {OP_LABELS[op]}
                          </option>
                        ))}
                      </select>
                    )}
                    <ValueInput rule={rule} onChange={(value) => update(index, { ...rule, value })} />
                    <button
                      type="button"
                      onClick={() => setRules(rules.filter((_, i) => i !== index))}
                      aria-label={`Remove rule ${describeRule(rule)}`}
                      className="ml-auto rounded p-1 text-muted hover:text-err"
                    >
                      <X className="size-3.5" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            <Button
              size="sm"
              icon={<Plus />}
              onClick={() => setRules([...rules, defaultRule("orientation")])}
              disabled={rules.length >= 20}
              className="justify-self-start"
            >
              Add rule
            </Button>
          </section>
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
