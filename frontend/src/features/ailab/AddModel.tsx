import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileUp, Upload } from "lucide-react";
import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { ProgressBar } from "@/components/ui/ProgressBar";
import type { Job } from "@/lib/api/client";
import { keys, upsertJob } from "@/lib/api/keys";
import { formatBytes } from "@/lib/format";
import { useJob } from "../studio/api";
import { uploadModel } from "../studio/uploads";

const INPUT =
  "h-8 rounded-md border border-line-2 bg-panel-2 px-2 text-[12.5px] text-fg outline-none focus:border-cyan";

type Stage =
  | { kind: "idle" }
  | { kind: "uploading"; loaded: number }
  | { kind: "checking"; jobId: string }
  | { kind: "failed"; message: string; fix?: string };

interface JobError {
  message?: string;
  fix?: string | null;
}

/** Add an ONNX model you exported yourself. The server runs it on test images before adding it. */
export function AddModel() {
  const client = useQueryClient();
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [task, setTask] = useState<"denoise" | "deblur">("denoise");
  const [stage, setStage] = useState<Stage>({ kind: "idle" });
  const { data: job } = useJob(stage.kind === "checking" ? stage.jobId : null);

  const busy =
    stage.kind === "uploading" ||
    (stage.kind === "checking" && !job?.state.match(/succeeded|failed|cancelled/));
  const done = stage.kind === "checking" && job?.state === "succeeded";
  const jobError =
    stage.kind === "checking" && job?.state === "failed" ? (job.error as JobError | null) : null;

  async function add() {
    if (!file) return;
    setStage({ kind: "uploading", loaded: 0 });
    const result = await uploadModel(file, { name: name.trim() || undefined, task }, (loaded) =>
      setStage({ kind: "uploading", loaded }),
    );
    if (!result.ok) {
      setStage({ kind: "failed", ...result.error });
      return;
    }
    client.setQueryData<Job[]>(keys.jobs, (list) => upsertJob(list, result.body.job));
    setStage({ kind: "checking", jobId: result.body.job.id });
  }

  function reset() {
    setFile(null);
    setName("");
    setStage({ kind: "idle" });
    if (input.current) input.current.value = "";
  }

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="grid gap-3 rounded-lg border border-dashed border-line-2 bg-panel-2 p-3"
      data-testid="add-model"
    >
      <div className="flex items-start gap-2">
        <FileUp className="mt-0.5 size-4 shrink-0 text-cyan" aria-hidden="true" />
        <div className="min-w-0">
          <h3 id={`${id}-title`} className="text-[13px] font-semibold text-fg">
            Add your own ONNX model
          </h3>
          <p className="text-[12px] text-fg-2">
            An image-to-image model with one N×C×H×W input (values 0 to 1) and dynamic height and width. It is
            run on test images first to find its scale and limits, then works here and in Flows, on the CPU.
          </p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <label className="grid gap-1 text-[12px] text-fg-2" htmlFor={`${id}-file`}>
          ONNX file
          <input
            ref={input}
            id={`${id}-file`}
            type="file"
            accept=".onnx"
            data-testid="onnx-file-input"
            disabled={busy}
            className="text-[12px] text-fg-2 file:mr-2 file:h-8 file:rounded-md file:border file:border-line-2 file:bg-panel file:px-2 file:text-fg"
            onChange={(e) => {
              const picked = e.target.files?.[0] ?? null;
              setFile(picked);
              if (picked && !name) setName(picked.name.replace(/\.onnx$/i, "").replace(/[_-]+/g, " "));
              if (stage.kind !== "uploading") setStage({ kind: "idle" });
            }}
          />
        </label>
        <label className="grid gap-1 text-[12px] text-fg-2" htmlFor={`${id}-name`}>
          Name
          <input
            id={`${id}-name`}
            className={INPUT}
            value={name}
            maxLength={60}
            disabled={busy}
            placeholder="My model"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="grid gap-1 text-[12px] text-fg-2 sm:col-span-2" htmlFor={`${id}-task`}>
          If it keeps the size, it
          <select
            id={`${id}-task`}
            className={INPUT}
            value={task}
            disabled={busy}
            onChange={(e) => setTask(e.target.value as "denoise" | "deblur")}
          >
            <option value="denoise">Denoises</option>
            <option value="deblur">Deblurs</option>
          </select>
          <span className="text-[11.5px] text-muted">
            Models that enlarge are always listed as upscalers.
          </span>
        </label>
      </div>

      {stage.kind === "uploading" && file && (
        <div className="grid gap-1">
          <ProgressBar value={stage.loaded / Math.max(1, file.size)} label={`Uploading ${file.name}`} />
          <span className="text-[11.5px] text-muted">
            Uploading {formatBytes(stage.loaded)} of {formatBytes(file.size)}
          </span>
        </div>
      )}
      {stage.kind === "checking" && !done && !jobError && (
        <div className="grid gap-1">
          <ProgressBar value={job?.progress ?? 0} label="Checking the model" />
          <span className="text-[11.5px] text-muted">{job?.message ?? "Checking the model"}</span>
        </div>
      )}
      {done && (
        <p className="flex items-center gap-2 text-[12px] text-fg-2" role="status">
          <Chip tone="ok" icon={<CheckCircle2 />}>
            Added
          </Chip>
          {job?.message}
        </p>
      )}
      {(stage.kind === "failed" || jobError) && (
        <div role="alert" className="grid gap-0.5 text-[12px]">
          <p className="flex items-start gap-1.5 text-err">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {stage.kind === "failed" ? stage.message : (jobError?.message ?? "The model couldn't be added.")}
          </p>
          {(stage.kind === "failed" ? stage.fix : jobError?.fix) && (
            <p className="text-fg-2">{stage.kind === "failed" ? stage.fix : jobError?.fix}</p>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {done ? (
          <Button size="sm" icon={<FileUp />} onClick={reset}>
            Add another model
          </Button>
        ) : (
          <Button
            size="sm"
            icon={<Upload />}
            disabled={!file || busy}
            loading={busy}
            onClick={() => void add()}
          >
            Add ONNX model
          </Button>
        )}
      </div>
    </section>
  );
}
