import { clsx } from "clsx";
import { AlertTriangle, ArrowRight, Database, Dices, Plus, RefreshCw, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { JobStateChip } from "@/components/ui/JobStateChip";
import { Spinner } from "@/components/ui/Spinner";
import { useAlbums } from "@/features/library/api";
import { INPUT, RulesEditor } from "@/features/library/RulesEditor";
import { useLibraryStore } from "@/features/library/store";
import { useJob } from "@/features/studio/api";
import {
  type DatasetSettings,
  type Degradation,
  errorMessage,
  type ForgeDataset,
  type ForgeImageSource,
  type RuleSet,
} from "@/lib/api/client";
import { formatBytes, relativeTime } from "@/lib/format";
import {
  useCreateDataset,
  useDatasetPreview,
  useDeleteDataset,
  useRebuildDataset,
  useSetDegradation,
} from "./api";

const FIELD = "grid gap-1 text-[12px] text-fg-2";

export function DatasetList({
  datasets,
  current,
  onPick,
  onNew,
}: {
  datasets: ForgeDataset[];
  current: string | undefined;
  onPick: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <div className="grid content-start gap-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="eyebrow">Datasets</h2>
        <Button size="sm" variant="primary" icon={<Plus />} onClick={onNew}>
          New dataset
        </Button>
      </div>
      {datasets.length === 0 && (
        <p className="text-[12px] text-fg-2">
          A dataset is a set of clean crops cut from your Library. Training damages them on the fly.
        </p>
      )}
      <ul className="grid gap-1" aria-label="Datasets">
        {datasets.map((d) => (
          <li key={d.id}>
            <button
              type="button"
              onClick={() => onPick(d.id)}
              aria-current={current === d.id ? "page" : undefined}
              className={clsx(
                "grid w-full gap-1 rounded-lg border px-2.5 py-2 text-left transition",
                current === d.id
                  ? "border-cyan bg-cyan-soft"
                  : "border-transparent hover:border-line-2 hover:bg-panel-2",
              )}
            >
              <span className="flex items-center gap-1.5">
                <Database className="size-3.5 shrink-0 text-cyan" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">{d.name}</span>
              </span>
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
                {d.state !== "succeeded" && <JobStateChip state={d.state} />}
                {d.state === "succeeded" && (
                  <span className="font-mono">
                    {d.images.toLocaleString()} images · {(d.train_crops + d.val_crops).toLocaleString()}{" "}
                    crops
                  </span>
                )}
                <span>{relativeTime(d.created_at)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

type SourceKind = ForgeImageSource["kind"];

/** Choose Library images and how to cut them. */
export function NewDatasetDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (dataset: ForgeDataset) => void;
}) {
  const selection = useLibraryStore((s) => s.selected);
  const { data: albums } = useAlbums();
  const create = useCreateDataset();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<SourceKind>("all");
  const [albumId, setAlbumId] = useState("");
  const [rules, setRules] = useState<RuleSet>({ match: "all", rules: [] });
  const [settings, setSettings] = useState<DatasetSettings>({
    crop: 256,
    crops_per_image: 8,
    min_width: 600,
    min_height: 300,
    val_every: 10,
    max_images: 2000,
  });

  // biome-ignore lint/correctness/useExhaustiveDependencies: choose a source when the dialog opens
  useEffect(() => {
    if (open) {
      setKind(selection.length ? "assets" : kind === "assets" ? "all" : kind);
      create.reset();
    }
  }, [open]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const source: ForgeImageSource =
      kind === "assets"
        ? { kind, asset_ids: selection }
        : kind === "album"
          ? { kind, album_id: albumId }
          : kind === "rules"
            ? { kind, rules }
            : { kind };
    create.mutate(
      { name: name.trim() || "Training photos", source, settings },
      {
        onSuccess: (d) => {
          setName("");
          onCreated(d);
        },
      },
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
    { kind: "rules", label: "Images that match rules", help: "For example: sharp, at least 2000 px wide." },
    { kind: "all", label: "Every image in the Library", help: "Up to the maximum below, sharpest first." },
  ];
  const ready =
    (kind !== "album" || albumId) &&
    (kind !== "rules" || (rules.rules ?? []).length > 0) &&
    (kind !== "assets" || selection.length > 0);
  const number = (key: keyof DatasetSettings, label: string, min: number, max: number, unit = "") => (
    <label className={FIELD}>
      <span className="text-fg">{label}</span>
      <span className="flex items-center gap-1.5">
        <input
          type="number"
          className={clsx(INPUT, "w-24")}
          min={min}
          max={max}
          value={settings[key]}
          onChange={(e) =>
            e.target.value && setSettings({ ...settings, [key]: Math.round(Number(e.target.value)) })
          }
        />
        {unit && <span className="text-[11.5px] text-muted">{unit}</span>}
      </span>
    </label>
  );

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="New dataset"
      footer={
        <div className="flex justify-end">
          <Button
            variant="primary"
            type="submit"
            form="new-dataset"
            loading={create.isPending}
            disabled={!ready}
          >
            Build dataset
          </Button>
        </div>
      }
    >
      <form id="new-dataset" noValidate onSubmit={submit} className="grid gap-4">
        <label className="grid gap-1 text-[12.5px] text-fg-2">
          Name
          <input
            className={INPUT}
            value={name}
            maxLength={120}
            placeholder="Training photos"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-[12.5px] text-fg-2">Cut crops from</legend>
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
                name="dataset-source"
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
        <div className="grid grid-cols-2 gap-3">
          <label className={FIELD}>
            <span className="text-fg">Crop size</span>
            <select
              className={INPUT}
              value={settings.crop}
              onChange={(e) => setSettings({ ...settings, crop: Number(e.target.value) })}
            >
              {[128, 192, 256, 384, 512].map((c) => (
                <option key={c} value={c}>
                  {c} × {c} px
                </option>
              ))}
            </select>
          </label>
          {number("crops_per_image", "Crops per image", 1, 64)}
          {number("min_width", "Skip narrower than", 64, 20000, "px")}
          {number("min_height", "Skip shorter than", 64, 20000, "px")}
          {number("val_every", "Keep 1 in N for checking", 2, 100)}
          {number("max_images", "At most", 1, 20000, "images")}
        </div>
        <p className="text-[11.5px] text-muted">
          Crops are clean; training damages them differently every time. Smooth, empty crops are skipped.
        </p>
        {create.error && (
          <p role="alert" className="text-[12px] text-err">
            {errorMessage(create.error).message} {errorMessage(create.error).fix}
          </p>
        )}
      </form>
    </Drawer>
  );
}

function RangeField({
  label,
  unit,
  min,
  max,
  step,
  value,
  chance,
  onChange,
  onChance,
}: {
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  value: { low: number; high: number };
  chance: number;
  onChange: (value: { low: number; high: number }) => void;
  onChance: (chance: number) => void;
}) {
  const num = (v: number, set: (n: number) => void, aria: string) => (
    <input
      type="number"
      className={clsx(INPUT, "w-20")}
      min={min}
      max={max}
      step={step}
      value={v}
      aria-label={aria}
      onChange={(e) => e.target.value !== "" && set(Number(e.target.value))}
    />
  );
  return (
    <fieldset className="grid gap-1.5 rounded-lg border border-line p-2.5">
      <legend className="px-1 text-[12px] text-fg">{label}</legend>
      <span className="flex flex-wrap items-center gap-1.5 text-[12px] text-fg-2">
        {num(value.low, (low) => onChange({ ...value, low }), `${label} from`)}
        to
        {num(value.high, (high) => onChange({ ...value, high }), `${label} to`)}
        <span className="text-[11.5px] text-muted">{unit}</span>
      </span>
      <label className="flex items-center gap-2 text-[12px] text-fg-2">
        <span className="w-[92px] shrink-0">On {Math.round(chance * 100)}% of crops</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={chance}
          onChange={(e) => onChance(Number(e.target.value))}
          className="min-w-0 flex-1 accent-[var(--cyan)]"
          aria-label={`${label}: share of crops`}
        />
      </label>
    </fieldset>
  );
}

function Chain({ d, scale }: { d: Degradation; scale: number }) {
  const steps = [
    "Clean crop",
    d.blur_chance > 0 ? `Blur σ ${d.blur.low}–${d.blur.high}` : null,
    `Bicubic ↓${scale}`,
    d.noise_chance > 0 ? `Noise σ ${d.noise.low}–${d.noise.high}` : null,
    d.jpeg_chance > 0 ? `JPEG q ${d.jpeg.low}–${d.jpeg.high}` : null,
  ].filter(Boolean) as string[];
  return (
    <ol
      className="flex flex-wrap items-center gap-1.5 font-mono text-[11px]"
      aria-label="Damage applied, in order"
    >
      {steps.map((step, i) => (
        <li key={step} className="flex items-center gap-1.5">
          {i > 0 && <ArrowRight className="size-3 text-muted" aria-hidden="true" />}
          <span className="rounded-md border border-line-2 bg-panel-2 px-1.5 py-0.5 text-fg-2">{step}</span>
        </li>
      ))}
    </ol>
  );
}

const SAVE_DELAY = 500;

/** A dataset: its numbers, how training damages its crops, and a preview of that damage. */
export function DatasetDetail({ dataset, onDeleted }: { dataset: ForgeDataset; onDeleted: () => void }) {
  const save = useSetDegradation();
  const rebuild = useRebuildDataset();
  const remove = useDeleteDataset();
  const { data: job } = useJob(
    dataset.state === "queued" || dataset.state === "running" ? dataset.job_id : null,
  );
  const [degradation, setDegradation] = useState<Degradation>(dataset.degradation);
  const [scale, setScale] = useState(3);
  const [seed, setSeed] = useState(0);
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const { data: preview, isFetching } = useDatasetPreview(dataset, scale, seed);

  // biome-ignore lint/correctness/useExhaustiveDependencies: load the saved settings when another dataset opens
  useEffect(() => {
    setDegradation(dataset.degradation);
    setArmed(false);
  }, [dataset.id]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const change = (next: Degradation) => {
    setDegradation(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => save.mutate({ id: dataset.id, degradation: next }), SAVE_DELAY);
  };
  const busy = dataset.state === "queued" || dataset.state === "running";

  return (
    <div className="grid gap-4" data-testid="forge-dataset">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="min-w-0 flex-1 truncate font-display text-[16px] font-medium">{dataset.name}</h2>
        <JobStateChip state={dataset.state} />
        <Button
          size="sm"
          icon={<RefreshCw />}
          disabled={busy}
          loading={rebuild.isPending}
          onClick={() => rebuild.mutate(dataset.id)}
          title="Cut the crops again, for example after adding photos"
        >
          Rebuild
        </Button>
        <Button
          size="sm"
          variant="danger"
          icon={<Trash2 />}
          loading={remove.isPending}
          onBlur={() => setArmed(false)}
          onClick={() => (armed ? remove.mutate(dataset.id, { onSuccess: onDeleted }) : setArmed(true))}
          aria-label={armed ? `Confirm deleting ${dataset.name}` : `Delete ${dataset.name}`}
        >
          <span className={clsx(!armed && "max-md:sr-only")}>{armed ? "Delete dataset?" : "Delete"}</span>
        </Button>
      </header>
      {(rebuild.error || remove.error) && (
        <p role="alert" className="flex items-start gap-1.5 text-[12px] text-err">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          {errorMessage(rebuild.error ?? remove.error).message}{" "}
          {errorMessage(rebuild.error ?? remove.error).fix}
        </p>
      )}
      {busy && (
        <p className="flex items-center gap-2 text-[12.5px] text-fg-2">
          <Spinner className="size-3.5" />
          {job?.message || "Waiting for a worker"}
          {job && job.progress > 0 && <span className="font-mono">{Math.round(job.progress * 100)}%</span>}
        </p>
      )}
      {dataset.state === "failed" && dataset.error && (
        <p
          role="alert"
          className="flex items-start gap-1.5 rounded-lg border border-err/45 bg-err-soft p-2.5 text-[12px] text-err"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          {String(dataset.error.message ?? "The dataset couldn't be built.")}
        </p>
      )}
      {dataset.state === "succeeded" && (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(
            [
              ["Images", dataset.images.toLocaleString()],
              ["Training crops", dataset.train_crops.toLocaleString()],
              ["Checking crops", dataset.val_crops.toLocaleString()],
              ["On disk", formatBytes(dataset.size_bytes)],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <dt className="text-[11.5px] text-muted">{label}</dt>
              <dd className="text-[15px] font-semibold text-fg">{value}</dd>
            </div>
          ))}
          {dataset.skipped > 0 && (
            <p className="col-span-full text-[11.5px] text-muted">
              {dataset.skipped.toLocaleString()} images skipped (too small, not RGB, or unreadable).
            </p>
          )}
        </dl>
      )}

      <section className="grid gap-3" aria-label="Damage">
        <div>
          <h3 className="text-[13px] font-semibold text-fg">How training damages the crops</h3>
          <p className="text-[12px] text-fg-2">
            Each training sample gets fresh damage drawn from these ranges. Changes apply to the next run; no
            rebuild needed.
          </p>
        </div>
        <Chain d={degradation} scale={scale} />
        <div className="grid gap-3 md:grid-cols-3">
          <RangeField
            label="Blur"
            unit="σ px"
            min={0}
            max={5}
            step={0.1}
            value={degradation.blur}
            chance={degradation.blur_chance}
            onChange={(blur) => change({ ...degradation, blur })}
            onChance={(blur_chance) => change({ ...degradation, blur_chance })}
          />
          <RangeField
            label="Noise"
            unit="σ of 255"
            min={0}
            max={50}
            step={1}
            value={degradation.noise}
            chance={degradation.noise_chance}
            onChange={(noise) => change({ ...degradation, noise })}
            onChance={(noise_chance) => change({ ...degradation, noise_chance })}
          />
          <RangeField
            label="JPEG"
            unit="quality"
            min={10}
            max={100}
            step={1}
            value={degradation.jpeg}
            chance={degradation.jpeg_chance}
            onChange={(jpeg) => change({ ...degradation, jpeg })}
            onChance={(jpeg_chance) => change({ ...degradation, jpeg_chance })}
          />
        </div>
      </section>

      <section className="grid gap-2" aria-label="Preview">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="flex-1 text-[13px] font-semibold text-fg">
            Preview: damaged input, then the clean crop
          </h3>
          <select
            className={INPUT}
            value={scale}
            onChange={(e) => setScale(Number(e.target.value))}
            aria-label="Preview scale"
          >
            {[1, 2, 3, 4].map((s) => (
              <option key={s} value={s}>
                {s === 1 ? "Same size (denoise)" : `×${s}`}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            icon={<Dices />}
            onClick={() => setSeed((s) => s + 1)}
            disabled={dataset.state !== "succeeded"}
          >
            Other crops
          </Button>
        </div>
        {dataset.state !== "succeeded" ? (
          <p className="text-[12px] text-muted">The preview appears once the dataset is built.</p>
        ) : preview ? (
          <img
            src={preview}
            alt="Damaged training inputs, enlarged, beside the clean crops they come from"
            className={clsx(
              "w-full max-w-[640px] rounded-lg border border-line [image-rendering:pixelated]",
              (isFetching || save.isPending) && "opacity-70",
            )}
            data-testid="forge-preview"
          />
        ) : (
          <Spinner />
        )}
      </section>
    </div>
  );
}
