import { Link } from "@tanstack/react-router";
import { clsx } from "clsx";
import { AlertTriangle, FolderInput, Info, Plus, Sparkles, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { useModels } from "@/features/ailab/api";
import { useAlbums } from "@/features/library/api";
import { INPUT, RulesEditor } from "@/features/library/RulesEditor";
import { useCatalog } from "@/features/studio/api";
import type { Flow, FlowNode, FlowNodeType, FlowParam, OpSpec, RuleSet } from "@/lib/api/client";

const FIELD = "grid gap-1 text-[12px] text-fg-2";

interface Adjustment {
  id: string;
  params: Record<string, number>;
}

function AdjustmentsInput({
  value,
  onChange,
}: {
  value: Adjustment[];
  onChange: (value: Adjustment[]) => void;
}) {
  const { data: catalog } = useCatalog();
  const ops = catalog?.ops ?? [];
  const byId = new Map(ops.map((o) => [o.id, o]));
  const fresh = (op: OpSpec): Adjustment => ({
    id: op.id,
    params: Object.fromEntries(op.params.map((p) => [p.name, p.default])),
  });
  return (
    <div className="grid gap-2">
      {value.map((entry, index) => {
        const op = byId.get(entry.id);
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: adjustments are edited in place by position
          <div key={index} className="grid gap-1.5 rounded-lg border border-line bg-panel-2 p-2">
            <div className="flex items-center gap-1.5">
              <select
                className={clsx(INPUT, "min-w-0 flex-1")}
                value={entry.id}
                aria-label="Adjustment"
                onChange={(e) => {
                  const next = byId.get(e.target.value);
                  if (next) onChange(value.map((v, i) => (i === index ? fresh(next) : v)));
                }}
              >
                {ops.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => onChange(value.filter((_, i) => i !== index))}
                aria-label={`Remove ${op?.label ?? entry.id}`}
                className="rounded p-1 text-muted hover:text-err"
              >
                <X className="size-3.5" />
              </button>
            </div>
            {op?.params.map((p) => (
              <label key={p.name} className="grid grid-cols-[1fr_auto] items-center gap-x-2 text-[11.5px]">
                <span>{p.label}</span>
                <span className="font-mono text-fg">
                  {entry.params[p.name] ?? p.default}
                  {p.unit}
                </span>
                <input
                  type="range"
                  className="col-span-2 accent-[var(--cyan)]"
                  min={p.min}
                  max={p.max}
                  step={p.step}
                  value={entry.params[p.name] ?? p.default}
                  onChange={(e) =>
                    onChange(
                      value.map((v, i) =>
                        i === index ? { ...v, params: { ...v.params, [p.name]: Number(e.target.value) } } : v,
                      ),
                    )
                  }
                />
              </label>
            ))}
          </div>
        );
      })}
      <Button
        size="sm"
        icon={<Plus />}
        className="justify-self-start"
        disabled={!ops.length || value.length >= 20}
        onClick={() => ops[0] && onChange([...value, fresh(ops[0])])}
      >
        Add adjustment
      </Button>
    </div>
  );
}

function ParamInput({
  param,
  value,
  onChange,
  nodeType,
}: {
  param: FlowParam;
  value: unknown;
  onChange: (value: unknown) => void;
  nodeType: string;
}) {
  const { data: models } = useModels();
  const { data: albums } = useAlbums();
  const id = `param-${nodeType}-${param.name}`;
  const label = (
    <span className="flex items-center justify-between gap-2">
      <span className="text-fg">{param.label}</span>
      {param.optional && <span className="text-[11px] text-muted">optional</span>}
    </span>
  );
  const help = param.help ? <span className="text-[11.5px] text-muted">{param.help}</span> : null;

  switch (param.kind) {
    case "boolean":
      return (
        <label className="flex items-start gap-2 text-[12px]">
          <input
            type="checkbox"
            className="mt-0.5 accent-[var(--cyan)]"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span className="grid">
            <span className="text-fg">{param.label}</span>
            {help}
          </span>
        </label>
      );
    case "choice":
      return (
        <label className={FIELD} htmlFor={id}>
          {label}
          <select
            id={id}
            className={INPUT}
            value={String(value ?? "")}
            onChange={(e) => onChange(e.target.value)}
          >
            {param.choices?.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
          {help}
        </label>
      );
    case "integer":
    case "number": {
      const empty = value === null || value === undefined || value === "";
      return (
        <label className={FIELD} htmlFor={id}>
          {label}
          <span className="flex items-center gap-1.5">
            <input
              id={id}
              type="number"
              className={clsx(INPUT, "w-28")}
              value={empty ? "" : Number(value)}
              min={param.min ?? undefined}
              max={param.max ?? undefined}
              step={param.step ?? (param.kind === "integer" ? 1 : 0.1)}
              placeholder={param.optional ? "Off" : undefined}
              onChange={(e) => {
                if (e.target.value === "") onChange(param.optional ? null : (param.default ?? 0));
                else
                  onChange(
                    param.kind === "integer" ? Math.round(Number(e.target.value)) : Number(e.target.value),
                  );
              }}
            />
            {param.unit && <span className="text-[11.5px] text-muted">{param.unit}</span>}
          </span>
          {help}
        </label>
      );
    }
    case "color": {
      const transparent = value === "transparent";
      return (
        <div className={FIELD}>
          <label htmlFor={id}>{label}</label>
          <span className="flex items-center gap-2">
            <input
              id={id}
              type="color"
              className="h-8 w-12 cursor-pointer rounded border border-line-2 bg-panel-2 disabled:opacity-40"
              value={transparent ? "#ffffff" : String(value ?? "#ffffff")}
              disabled={transparent}
              onChange={(e) => onChange(e.target.value)}
            />
            <span className="font-mono text-[11.5px] text-fg">{String(value)}</span>
            {nodeType === "canvas" && (
              <label className="ml-auto flex items-center gap-1.5 text-[12px]">
                <input
                  type="checkbox"
                  className="accent-[var(--cyan)]"
                  checked={transparent}
                  onChange={(e) => onChange(e.target.checked ? "transparent" : "#ffffff")}
                />
                Transparent
              </label>
            )}
          </span>
          {help}
        </div>
      );
    }
    case "model": {
      const options = (models ?? []).filter((m) => m.task === param.task);
      const chosen = options.find((m) => m.id === value);
      return (
        <label className={FIELD} htmlFor={id}>
          {label}
          <select
            id={id}
            className={INPUT}
            value={String(value ?? "")}
            onChange={(e) => onChange(e.target.value)}
          >
            {options.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
                {m.status === "installed" ? "" : " (not downloaded)"}
              </option>
            ))}
          </select>
          {chosen && (
            <span className="text-[11.5px] text-muted">
              {chosen.summary} · {chosen.license}
            </span>
          )}
          {chosen && chosen.status !== "installed" && (
            <span className="flex items-center gap-1 text-[11.5px] text-warn">
              <AlertTriangle className="size-3.5" aria-hidden="true" />
              Download it in{" "}
              <Link to="/ai-lab" className="underline">
                AI Lab
              </Link>{" "}
              before running this flow.
            </span>
          )}
        </label>
      );
    }
    case "album": {
      const manual = (albums ?? []).filter((a) => a.kind === "manual");
      return (
        <label className={FIELD} htmlFor={id}>
          {label}
          <select
            id={id}
            className={INPUT}
            value={String(value ?? "")}
            onChange={(e) => onChange(e.target.value || null)}
          >
            <option value="">Choose an album…</option>
            {manual.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          {manual.length === 0 ? (
            <span className="text-[11.5px] text-muted">Make a hand-picked album in the Library first.</span>
          ) : (
            help
          )}
        </label>
      );
    }
    case "tags":
      return (
        <label className={FIELD} htmlFor={id}>
          {label}
          <input
            id={id}
            className={INPUT}
            defaultValue={((value as string[] | undefined) ?? []).join(", ")}
            placeholder="processed, web"
            onBlur={(e) =>
              onChange(
                e.target.value
                  .split(",")
                  .map((t) => t.trim())
                  .filter(Boolean),
              )
            }
          />
          <span className="text-[11.5px] text-muted">Separate tags with commas.</span>
        </label>
      );
    case "rules":
      return (
        <div className="grid gap-1 text-[12px]">
          <RulesEditor
            value={(value as RuleSet | undefined) ?? { match: "all", rules: [] }}
            onChange={onChange}
            intro="Yes when an image matches"
            label="If rules"
          />
          <span className="text-[11.5px] text-muted">Everything else goes out of No.</span>
        </div>
      );
    case "adjustments":
      return (
        <div className={FIELD}>
          {label}
          <AdjustmentsInput value={(value as Adjustment[] | undefined) ?? []} onChange={onChange} />
        </div>
      );
    default:
      return (
        <label className={FIELD} htmlFor={id}>
          {label}
          <input
            id={id}
            className={INPUT}
            value={String(value ?? "")}
            maxLength={200}
            onChange={(e) => onChange(e.target.value)}
          />
          {help}
        </label>
      );
  }
}

/** Settings for the selected block. */
export function BlockInspector({
  node,
  spec,
  problems,
  onChange,
  onDelete,
  onClose,
}: {
  node: FlowNode;
  spec: FlowNodeType | undefined;
  problems: string[];
  onChange: (node: FlowNode) => void;
  onDelete: () => void;
  onClose?: () => void;
}) {
  const params = node.params ?? {};
  return (
    <div className="grid gap-4" data-testid="block-inspector">
      <header className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="eyebrow mb-0.5">{spec?.category_label ?? "Block"}</div>
          <h3 className="flex items-center gap-1.5 text-[14px] font-semibold text-fg">
            {spec?.label ?? node.type}
            {spec?.ai && (
              <Chip tone="gold" icon={<Sparkles />}>
                AI
              </Chip>
            )}
          </h3>
          <p className="mt-1 text-[12px] text-fg-2">{spec?.summary}</p>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted hover:bg-panel-2 hover:text-fg"
            aria-label="Close block settings"
          >
            <X className="size-4" />
          </button>
        )}
      </header>
      {problems.length > 0 && (
        <ul
          className="grid gap-1 rounded-lg border border-err/45 bg-err-soft p-2.5 text-[12px] text-err"
          role="alert"
        >
          {problems.map((p) => (
            <li key={p} className="flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              {p}
            </li>
          ))}
        </ul>
      )}
      {node.type !== "input" && (
        <label className={FIELD}>
          <span className="text-fg">Name on the canvas</span>
          <input
            className={INPUT}
            value={node.label ?? ""}
            placeholder={spec?.label}
            maxLength={60}
            onChange={(e) => onChange({ ...node, label: e.target.value || null })}
          />
        </label>
      )}
      {spec?.params.map((param) => (
        <ParamInput
          key={`${node.id}-${param.name}`}
          param={param}
          nodeType={node.type}
          value={params[param.name]}
          onChange={(value) => onChange({ ...node, params: { ...params, [param.name]: value } })}
        />
      ))}
      {spec?.queue === "gpu" && (
        <p className="flex items-start gap-1.5 text-[11.5px] text-fg-2">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          Runs on the GPU, one image at a time; other blocks keep working on the next images meanwhile.
        </p>
      )}
      {node.type !== "input" && (
        <Button
          variant="danger"
          size="sm"
          icon={<Trash2 />}
          onClick={onDelete}
          className="justify-self-start"
        >
          Remove block
        </Button>
      )}
    </div>
  );
}

/** Settings for the whole flow, shown when no block is selected. */
export function FlowSettings({
  flow,
  onSave,
  saving,
}: {
  flow: Flow;
  onSave: (changes: {
    name?: string;
    description?: string;
    watch_folder?: string;
    watch_enabled?: boolean;
  }) => void;
  saving: boolean;
}) {
  const [folder, setFolder] = useState(flow.watch_folder ?? "");
  const general = flow.problems.filter((p) => !p.node);
  return (
    <div className="grid gap-4" data-testid="flow-settings">
      <div>
        <div className="eyebrow mb-0.5">Flow</div>
        <h3 className="text-[14px] font-semibold text-fg">Settings</h3>
        <p className="mt-1 text-[12px] text-fg-2">Select a block on the canvas to change what it does.</p>
      </div>
      {general.length > 0 && (
        <ul
          className="grid gap-1 rounded-lg border border-err/45 bg-err-soft p-2.5 text-[12px] text-err"
          role="alert"
        >
          {general.map((p) => (
            <li key={p.message} className="flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              {p.message}
            </li>
          ))}
        </ul>
      )}
      <label className={FIELD}>
        <span className="text-fg">Name</span>
        <input
          className={INPUT}
          defaultValue={flow.name}
          maxLength={120}
          key={`name-${flow.id}`}
          onBlur={(e) =>
            e.target.value.trim() && e.target.value !== flow.name && onSave({ name: e.target.value.trim() })
          }
        />
      </label>
      <label className={FIELD}>
        <span className="text-fg">Notes</span>
        <textarea
          className={clsx(INPUT, "h-20 py-1.5")}
          defaultValue={flow.description}
          key={`desc-${flow.id}`}
          maxLength={1000}
          onBlur={(e) => e.target.value !== flow.description && onSave({ description: e.target.value })}
        />
      </label>
      <section className="grid gap-2 rounded-lg border border-line p-3" aria-labelledby="watch-title">
        <h4 id="watch-title" className="flex items-center gap-1.5 text-[12.5px] font-semibold text-fg">
          <FolderInput className="size-4 text-cyan" aria-hidden="true" />
          Run on new images automatically
        </h4>
        <p className="text-[12px] text-fg-2">
          When images arrive in this folder inside the import folder, they're added to the Library and this
          flow runs on them. Leave it empty to watch the whole import folder.
        </p>
        <input
          className={INPUT}
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          placeholder="e.g. inbox/wallpapers"
          aria-label="Folder to watch"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={flow.watch_enabled ? "outline" : "primary"}
            loading={saving}
            disabled={!flow.watch_enabled && flow.problems.length > 0}
            onClick={() => onSave({ watch_folder: folder, watch_enabled: !flow.watch_enabled })}
          >
            {flow.watch_enabled ? "Stop watching" : "Start watching"}
          </Button>
          {flow.watch_enabled && folder !== (flow.watch_folder ?? "") && (
            <Button size="sm" onClick={() => onSave({ watch_folder: folder })} loading={saving}>
              Change folder
            </Button>
          )}
          {flow.watch_enabled ? (
            <Chip tone="ok" icon={<FolderInput />}>
              Watching {flow.watch_folder ? `/${flow.watch_folder}` : "the import folder"}
            </Chip>
          ) : flow.problems.length > 0 ? (
            <span className="text-[11.5px] text-muted">Fix the problems first.</span>
          ) : null}
        </div>
      </section>
    </div>
  );
}
