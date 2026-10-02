import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { Rule, RuleSet } from "@/lib/api/client";
import { defaultRule, describeRule, FIELDS, OP_LABELS, type RuleField, type RuleOp } from "./rules";

export const INPUT =
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

/** Edit a set of rules: shared by smart albums and the If block in Flows. */
export function RulesEditor({
  value,
  onChange,
  intro,
  label = "Rules",
}: {
  value: RuleSet;
  onChange: (rules: RuleSet) => void;
  intro: string;
  label?: string;
}) {
  const rules = value.rules ?? [];
  const setRules = (next: Rule[]) => onChange({ ...value, rules: next });
  const update = (index: number, rule: Rule) => setRules(rules.map((r, i) => (i === index ? rule : r)));
  return (
    <section className="grid gap-2" aria-label={label}>
      <div className="flex items-center gap-2 text-[12.5px] text-fg-2">
        {intro}
        <select
          className={INPUT}
          value={value.match}
          onChange={(e) => onChange({ ...value, match: e.target.value as "all" | "any" })}
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
  );
}
