import { clsx } from "clsx";
import { AlertTriangle, CheckCircle2, Download, FileDown, MapPin, Trash2, XCircle } from "lucide-react";
import { type CSSProperties, type ReactNode, useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Spinner } from "@/components/ui/Spinner";
import {
  type Asset,
  type ExportRequest,
  errorMessage,
  type OutputFormat,
  type Rendition,
} from "@/lib/api/client";
import { useCancelJob } from "@/lib/api/queries";
import { formatBytes, relativeTime } from "@/lib/format";
import { useDeleteRendition, useJob, useRenditions, useStartExport } from "../api";
import { outputSize, plannedSize } from "../doc";
import { formatDimensions } from "../format";
import { useEditor } from "../store";

const SIZES: { label: string; value: number | null }[] = [
  { label: "Full size", value: null },
  { label: "4096", value: 4096 },
  { label: "2048", value: 2048 },
  { label: "1080", value: 1080 },
];

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[12.5px] text-fg-2">{label}</span>
        {hint && <span className="text-[11px] text-muted">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function RenditionRow({ rendition, assetId }: { rendition: Rendition; assetId: string }) {
  const { data: job } = useJob(
    rendition.status === "pending" || rendition.status === "failed" ? rendition.job_id : null,
  );
  const remove = useDeleteRendition(assetId);
  const cancel = useCancelJob();
  const failed = rendition.status === "failed" || job?.state === "failed" || job?.state === "cancelled";
  return (
    <li className="grid grid-cols-[minmax(0,1fr)] gap-1.5 py-2.5" data-testid="rendition">
      <div className="flex items-center gap-2">
        {rendition.status === "ready" ? (
          <CheckCircle2 className="size-4 shrink-0 text-ok" aria-label="Ready" />
        ) : failed ? (
          <XCircle className="size-4 shrink-0 text-err" aria-label="Failed" />
        ) : (
          <Spinner className="size-4 shrink-0 text-cyan" label="Exporting" />
        )}
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg" title={rendition.filename}>
          {rendition.filename}
        </span>
        {rendition.status === "ready" && rendition.download_url ? (
          <a
            href={rendition.download_url}
            download={rendition.filename}
            className="inline-flex h-7 items-center gap-1.5 rounded-lg border border-cyan bg-cyan px-2.5 text-xs font-semibold text-on-cyan hover:brightness-110"
          >
            <Download className="size-3.5" aria-hidden="true" />
            Download
          </a>
        ) : !failed && job && (job.state === "running" || job.state === "queued") ? (
          <Button size="sm" variant="ghost" onClick={() => cancel.mutate(job.id)} loading={cancel.isPending}>
            Cancel
          </Button>
        ) : null}
        {(rendition.status !== "pending" || failed) && (
          <button
            type="button"
            onClick={() => remove.mutate(rendition.id)}
            className="grid size-7 place-items-center rounded-md text-muted hover:bg-panel-2 hover:text-err"
            aria-label={`Delete ${rendition.filename}`}
            title="Delete this export"
          >
            <Trash2 className="size-3.5" />
          </button>
        )}
      </div>
      {rendition.status === "pending" && !failed && (
        <div className="grid gap-1">
          <ProgressBar value={job?.progress ?? 0} label={`Exporting ${rendition.filename}`} />
          <span className="text-[11px] text-muted">{job?.message ?? "Waiting for a worker"}</span>
        </div>
      )}
      {failed && (
        <p className="flex items-start gap-1.5 text-[11.5px] text-err">
          <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          {job?.state === "cancelled"
            ? "Cancelled."
            : String(
                (job?.error as { message?: string } | null)?.message ?? job?.message ?? "The export failed.",
              )}
        </p>
      )}
      <div className="flex flex-wrap gap-x-3 text-[11px] text-muted">
        <span className="font-mono">{formatDimensions(rendition.width, rendition.height)}</span>
        {rendition.size_bytes != null && <span>{formatBytes(rendition.size_bytes)}</span>}
        {rendition.quality != null && <span>quality {rendition.quality}</span>}
        <span>{relativeTime(rendition.created_at)}</span>
      </div>
    </li>
  );
}

export function ExportPanel({ asset, formats }: { asset: Asset; formats: OutputFormat[] }) {
  const doc = useEditor((s) => s.doc);
  const flush = useEditor((s) => s.flush);
  const start = useStartExport(asset.id);
  const { data: renditions } = useRenditions(asset.id);
  const ids = { quality: useId(), side: useId(), target: useId() };

  const [format, setFormat] = useState<OutputFormat["id"]>(asset.has_alpha ? "png" : "jpeg");
  const [quality, setQuality] = useState(90);
  const [maxSide, setMaxSide] = useState<number | null>(null);
  const [targetKb, setTargetKb] = useState<number | null>(null);
  const [strip, setStrip] = useState(true);

  const spec = formats.find((f) => f.id === format);
  const [ow, oh] = outputSize(asset.width, asset.height, doc.geometry);
  const [fw, fh] = plannedSize(ow, oh, maxSide);
  const tooBig = spec ? Math.max(fw, fh) > spec.max_side : false;
  const losesAlpha = asset.has_alpha && spec && !spec.alpha;
  const losesDepth = asset.bit_depth === 16 && spec && !spec.sixteen_bit;

  const submit = async () => {
    await flush();
    const body: ExportRequest = {
      format,
      quality,
      max_side: maxSide,
      target_kb: spec?.lossy ? targetKb : null,
      strip_metadata: strip,
    };
    start.mutate(body);
  };
  const failure = start.error ? errorMessage(start.error) : null;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
      <fieldset className="grid gap-2">
        <legend className="eyebrow mb-2">Format</legend>
        <div className="grid grid-cols-3 gap-1.5">
          {formats.map((f) => (
            <label
              key={f.id}
              className={clsx(
                "grid h-12 cursor-pointer place-items-center rounded-md border text-center transition has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-cyan",
                format === f.id
                  ? "border-cyan bg-cyan-soft text-cyan"
                  : "border-line-2 text-fg-2 hover:border-cyan",
              )}
            >
              <input
                type="radio"
                name="export-format"
                value={f.id}
                checked={format === f.id}
                onChange={() => setFormat(f.id)}
                className="sr-only"
              />
              <span className="text-[12.5px] font-semibold">{f.label}</span>
              <span className="-mt-2 text-[10px] text-muted">{f.lossy ? "lossy" : "lossless"}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {spec?.lossy && (
        <Field label="Quality" hint={targetKb ? "Chosen automatically to hit the target size" : undefined}>
          <div className="flex items-center gap-3">
            <input
              id={ids.quality}
              type="range"
              className="range"
              min={1}
              max={100}
              value={quality}
              disabled={Boolean(targetKb)}
              onChange={(event) => setQuality(Number(event.target.value))}
              aria-label="Quality"
              style={{ "--from": "0%", "--to": `${quality}%` } as CSSProperties}
            />
            <output htmlFor={ids.quality} className="w-8 text-right font-mono text-[12px] text-fg">
              {quality}
            </output>
          </div>
        </Field>
      )}

      <Field label="Longest side" hint="pixels">
        <div className="grid grid-cols-4 gap-1.5">
          {SIZES.map((s) => (
            <button
              key={s.label}
              type="button"
              aria-pressed={maxSide === s.value}
              onClick={() => setMaxSide(s.value)}
              className={clsx(
                "h-8 rounded-md border text-[12px] transition",
                maxSide === s.value
                  ? "border-cyan bg-cyan-soft font-semibold text-cyan"
                  : "border-line-2 text-fg-2 hover:border-cyan",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        <input
          id={ids.side}
          type="number"
          min={16}
          max={65535}
          placeholder="Custom, for example 3000"
          aria-label="Custom longest side in pixels"
          value={maxSide && !SIZES.some((s) => s.value === maxSide) ? maxSide : ""}
          onChange={(event) => setMaxSide(event.target.value ? Number(event.target.value) : null)}
          className="h-8 rounded-md border border-line-2 bg-bg px-2.5 text-[12.5px] text-fg outline-none placeholder:text-muted focus:border-cyan"
        />
      </Field>

      {spec?.lossy && (
        <Field label="Target file size" hint="optional, KB">
          <input
            id={ids.target}
            type="number"
            min={1}
            placeholder="No target"
            aria-label="Target file size in kilobytes"
            value={targetKb ?? ""}
            onChange={(event) => setTargetKb(event.target.value ? Number(event.target.value) : null)}
            className="h-8 rounded-md border border-line-2 bg-bg px-2.5 text-[12.5px] text-fg outline-none placeholder:text-muted focus:border-cyan"
          />
        </Field>
      )}

      <label className="flex cursor-pointer items-start gap-2.5 text-[12.5px] text-fg-2">
        <input
          type="checkbox"
          checked={strip}
          onChange={(event) => setStrip(event.target.checked)}
          className="mt-0.5 size-4 accent-[var(--cyan)]"
        />
        <span>
          Remove camera data and location
          {asset.has_gps && (
            <span
              className={clsx(
                "mt-0.5 flex items-center gap-1 text-[11.5px]",
                strip ? "text-ok" : "text-warn",
              )}
            >
              <MapPin className="size-3" aria-hidden="true" />
              {strip ? "GPS location will be removed" : "This photo's GPS location will be included"}
            </span>
          )}
        </span>
      </label>

      <div className="grid gap-2 rounded-lg border border-line bg-panel-2 p-3 text-[12.5px]">
        <div className="flex justify-between gap-2">
          <span className="text-muted">Output</span>
          <span className="font-mono text-fg tabular-nums" data-testid="export-size">
            {formatDimensions(fw, fh)}
          </span>
        </div>
        {tooBig && spec && (
          <p className="flex items-start gap-1.5 text-err">
            <XCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {spec.label} allows at most {spec.max_side.toLocaleString()} px per side. Choose a smaller size or
            another format.
          </p>
        )}
        {losesAlpha && (
          <p className="flex items-start gap-1.5 text-warn">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {spec?.label} has no transparency; transparent areas become white.
          </p>
        )}
        {losesDepth && (
          <p className="flex items-start gap-1.5 text-warn">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            This is a 16-bit image; {spec?.label} saves 8 bits. Use PNG or TIFF to keep 16 bits.
          </p>
        )}
      </div>

      <Button
        variant="primary"
        icon={<FileDown />}
        onClick={() => void submit()}
        loading={start.isPending}
        disabled={tooBig || !spec}
      >
        Export {spec?.label ?? ""}
      </Button>
      {failure && (
        <div className="grid gap-0.5 text-[12px]" role="alert">
          <p className="flex items-start gap-1.5 text-err">
            <XCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {failure.message}
          </p>
          {failure.fix && <p className="text-fg-2">{failure.fix}</p>}
        </div>
      )}

      <section aria-labelledby="exports-heading" className="grid grid-cols-[minmax(0,1fr)]">
        <h3 id="exports-heading" className="eyebrow">
          Exports of this image
        </h3>
        {renditions?.length ? (
          <ul className="divide-y divide-line">
            {renditions.map((r) => (
              <RenditionRow key={r.id} rendition={r} assetId={asset.id} />
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[12px] text-muted">
            Nothing exported yet. Exports render at full resolution.
          </p>
        )}
      </section>
    </div>
  );
}
