import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { OpSpec } from "@/lib/api/client";
import { entry, paramValue, resetGroup, setParam, setToggle } from "../doc";
import { useEditor } from "../store";
import { Histogram } from "./Histogram";
import { Slider } from "./Slider";

const GROUPS: { id: OpSpec["group"]; label: string; order: string[] }[] = [
  {
    id: "light",
    label: "Light",
    order: ["exposure", "contrast", "highlights", "shadows", "whites", "blacks"],
  },
  { id: "color", label: "Colour", order: ["temperature", "tint", "vibrance", "saturation", "black_white"] },
  { id: "detail", label: "Detail", order: ["sharpen"] },
  { id: "effects", label: "Effects", order: ["vignette"] },
];

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-2 py-1.5 text-[12.5px] text-fg-2">
      {label}
      <input
        type="checkbox"
        role="switch"
        aria-checked={checked}
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="peer sr-only"
      />
      <span
        aria-hidden="true"
        className="relative h-[18px] w-8 rounded-full bg-line-2 transition peer-checked:bg-cyan peer-focus-visible:outline-2 peer-focus-visible:outline-cyan after:absolute after:top-[3px] after:left-[3px] after:size-3 after:rounded-full after:bg-bg after:transition peer-checked:after:translate-x-[14px]"
      />
    </label>
  );
}

export function AdjustPanel({ specs }: { specs: OpSpec[] }) {
  const doc = useEditor((s) => s.doc);
  const update = useEditor((s) => s.update);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <Histogram />
      {GROUPS.map((group) => {
        const ops = group.order
          .map((id) => specs.find((s) => s.id === id))
          .filter((s): s is OpSpec => s !== undefined);
        if (!ops.length) return null;
        const touched = ops.some((s) => entry(doc, s.id));
        return (
          <section key={group.id} aria-labelledby={`grp-${group.id}`} className="grid gap-0.5">
            <header className="mb-1 flex h-6 items-center justify-between">
              <h3 id={`grp-${group.id}`} className="eyebrow">
                {group.label}
              </h3>
              {touched && (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<RotateCcw />}
                  onClick={() =>
                    update(`Reset ${group.label.toLowerCase()}`, (d) => resetGroup(d, specs, group.id))
                  }
                >
                  Reset
                </Button>
              )}
            </header>
            {ops.map((spec) =>
              spec.params.length === 0 ? (
                <Toggle
                  key={spec.id}
                  label={spec.label}
                  checked={Boolean(entry(doc, spec.id))}
                  onChange={(on) => update(spec.label, (d) => setToggle(d, specs, spec.id, on))}
                />
              ) : (
                spec.params.map((param) => (
                  <Slider
                    key={`${spec.id}.${param.name}`}
                    label={spec.params.length > 1 ? `${spec.label} ${param.label.toLowerCase()}` : spec.label}
                    param={param}
                    value={paramValue(doc, spec, param.name)}
                    // Radius and midpoint only mean something once the amount is set.
                    disabled={param.name !== "amount" && spec.params.length > 1 && !entry(doc, spec.id)}
                    onChange={(value) =>
                      update(spec.label, (d) => setParam(d, specs, spec.id, param.name, value))
                    }
                  />
                ))
              ),
            )}
          </section>
        );
      })}
    </div>
  );
}
