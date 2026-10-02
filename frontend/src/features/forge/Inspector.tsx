import { clsx } from "clsx";
import { AlertTriangle, CheckCircle2, Info, Trash2, Wand2, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { INPUT } from "@/features/library/RulesEditor";
import type {
  ForgeAnalysis,
  ForgeBlock,
  ForgeBlockType,
  ForgeFix,
  ForgeParam,
  ForgeProblem,
  ForgeShape,
} from "@/lib/api/client";
import { formatBytes } from "@/lib/format";
import { compact, shapeLabel } from "./graph";

const FIELD = "grid gap-1 text-[12px] text-fg-2";

function ParamInput({
  param,
  value,
  onChange,
  blockId,
}: {
  param: ForgeParam;
  value: unknown;
  onChange: (value: unknown) => void;
  blockId: string;
}) {
  const id = `forge-${blockId}-${param.name}`;
  const help = param.help ? <span className="text-[11.5px] text-muted">{param.help}</span> : null;
  if (param.kind === "choice") {
    return (
      <label className={FIELD} htmlFor={id}>
        <span className="text-fg">{param.label}</span>
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
  }
  return (
    <label className={FIELD} htmlFor={id}>
      <span className="text-fg">{param.label}</span>
      <span className="flex items-center gap-1.5">
        <input
          id={id}
          type="number"
          className={clsx(INPUT, "w-28")}
          value={value === null || value === undefined ? "" : Number(value)}
          min={param.min ?? undefined}
          max={param.max ?? undefined}
          step={param.step ?? (param.kind === "integer" ? 1 : 0.05)}
          onChange={(e) => {
            if (e.target.value === "") return;
            const n = Number(e.target.value);
            onChange(param.kind === "integer" ? Math.round(n) : n);
          }}
        />
        {param.unit && <span className="text-[11.5px] text-muted">{param.unit}</span>}
      </span>
      {help}
    </label>
  );
}

/** Settings for the selected block, with the shapes going in and out. */
export function BlockInspector({
  block,
  spec,
  inputs,
  shape,
  problems,
  fixes,
  onChange,
  onFix,
  onDelete,
  onClose,
}: {
  block: ForgeBlock;
  spec: ForgeBlockType | undefined;
  inputs: (ForgeShape | undefined)[];
  shape: ForgeShape | undefined;
  problems: string[];
  fixes: ForgeFix[];
  onChange: (block: ForgeBlock) => void;
  onFix: (fix: ForgeFix) => void;
  onDelete: () => void;
  onClose?: () => void;
}) {
  const params = block.params ?? {};
  return (
    <div className="grid gap-4" data-testid="forge-inspector">
      <header className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="eyebrow mb-0.5">{spec?.category_label ?? "Block"}</div>
          <h3 className="text-[14px] font-semibold text-fg">{spec?.label ?? block.type}</h3>
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
      <dl className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-panel-2 p-2.5 font-mono text-[11.5px]">
        <div>
          <dt className="text-muted">In</dt>
          <dd className="text-fg">
            {block.type === "input"
              ? "image"
              : inputs.length
                ? inputs.map((s) => shapeLabel(s) || "?").join(" + ")
                : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Out</dt>
          <dd className="text-fg">{shapeLabel(shape) || "—"}</dd>
        </div>
      </dl>
      {problems.length > 0 && (
        <div
          className="grid gap-2 rounded-lg border border-err/45 bg-err-soft p-2.5 text-[12px] text-err"
          role="alert"
        >
          {problems.map((p) => (
            <p key={p} className="flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              {p}
            </p>
          ))}
          {fixes.map((fix) => (
            <Button
              key={fix.label}
              size="sm"
              icon={<Wand2 />}
              onClick={() => onFix(fix)}
              className="justify-self-start"
            >
              {fix.label}
            </Button>
          ))}
        </div>
      )}
      {block.type !== "input" && block.type !== "output" && (
        <label className={FIELD}>
          <span className="text-fg">Name on the canvas</span>
          <input
            className={INPUT}
            value={block.label ?? ""}
            placeholder={spec?.label}
            maxLength={60}
            onChange={(e) => onChange({ ...block, label: e.target.value || null })}
          />
        </label>
      )}
      {spec?.params.map((param) => (
        <ParamInput
          key={`${block.id}-${param.name}`}
          param={param}
          blockId={block.id}
          value={params[param.name]}
          onChange={(value) => onChange({ ...block, params: { ...params, [param.name]: value } })}
        />
      ))}
      {block.type !== "input" && (
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

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="grid gap-0.5" title={hint}>
      <dt className="text-[11.5px] text-muted">{label}</dt>
      <dd className="text-[15px] font-semibold text-fg">{value}</dd>
    </div>
  );
}

/** The whole model: size, cost and every problem with its fix. Shown when no block is selected. */
export function ModelSummary({
  analysis,
  onFix,
  onShow,
}: {
  analysis: ForgeAnalysis | undefined;
  onFix: (fix: ForgeFix) => void;
  onShow: (block: string) => void;
}) {
  if (!analysis) return null;
  const { stats, problems } = analysis;
  const ok = problems.length === 0;
  return (
    <div className="grid gap-4" data-testid="forge-summary">
      <header>
        <div className="eyebrow mb-0.5">This model</div>
        {ok ? (
          <Chip tone="ok" icon={<CheckCircle2 />}>
            Ready to train
          </Chip>
        ) : (
          <Chip tone="err" icon={<AlertTriangle />}>
            {problems.length === 1 ? "1 problem" : `${problems.length} problems`}
          </Chip>
        )}
      </header>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Stat label="Parameters" value={stats.params.toLocaleString()} />
        <Stat label="Scale" value={stats.scale ? `×${stats.scale}` : "—"} />
        <Stat
          label="Compute"
          value={`${stats.gmacs_per_megapixel.toLocaleString(undefined, { maximumFractionDigits: 1 })} GMAC/MP`}
          hint={`${compact(stats.macs_per_pixel)} multiply-adds per input pixel`}
        />
        <Stat label="Colour" value={stats.color === "y" ? "Brightness (Y)" : "RGB"} />
        <Stat
          label="Training memory"
          value={formatBytes(stats.train_memory_mb * 1024 * 1024)}
          hint="Estimated at batch 16, patch 64; lowered automatically if memory runs out"
        />
        <Stat label="Layers" value={String(stats.layers)} />
      </dl>
      {stats.patch_multiple > 1 && (
        <p className="flex items-start gap-1.5 text-[11.5px] text-fg-2">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          Training patches must be a multiple of {stats.patch_multiple} px (the model halves the image).
        </p>
      )}
      {problems.length > 0 && (
        <ul className="grid gap-2" aria-label="Problems">
          {problems.map((problem: ForgeProblem, i) => (
            <li
              // biome-ignore lint/suspicious/noArrayIndexKey: problems have no id and keep their order
              key={i}
              className="grid gap-2 rounded-lg border border-err/45 bg-err-soft p-2.5 text-[12px] text-err"
            >
              <span className="flex items-start gap-1.5">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                {problem.message}
              </span>
              <span className="flex flex-wrap gap-2">
                {problem.fix && (
                  <Button size="sm" icon={<Wand2 />} onClick={() => onFix(problem.fix as ForgeFix)}>
                    {problem.fix.label}
                  </Button>
                )}
                {problem.block && (
                  <Button size="sm" variant="ghost" onClick={() => onShow(problem.block as string)}>
                    Show block
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
