import { clsx } from "clsx";
import { AlertTriangle, Boxes, Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Drawer } from "@/components/ui/Drawer";
import { INPUT } from "@/features/library/RulesEditor";
import { errorMessage, type ForgeProject } from "@/lib/api/client";
import { relativeTime } from "@/lib/format";
import { useCreateProject, useForgeTemplates } from "./api";
import { compact } from "./graph";

export function ProjectList({
  projects,
  current,
  onPick,
  onNew,
}: {
  projects: ForgeProject[];
  current: string | undefined;
  onPick: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <div className="grid content-start gap-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="eyebrow">Your models</h2>
        <Button size="sm" variant="primary" icon={<Plus />} onClick={onNew}>
          New model
        </Button>
      </div>
      <ul className="grid gap-1" aria-label="Models">
        {projects.map((project) => {
          const { stats, problems } = project.analysis;
          return (
            <li key={project.id}>
              <button
                type="button"
                onClick={() => onPick(project.id)}
                aria-current={current === project.id ? "page" : undefined}
                className={clsx(
                  "grid w-full gap-1 rounded-lg border px-2.5 py-2 text-left transition",
                  current === project.id
                    ? "border-cyan bg-cyan-soft"
                    : "border-transparent hover:border-line-2 hover:bg-panel-2",
                )}
              >
                <span className="flex items-center gap-1.5">
                  <Boxes className="size-3.5 shrink-0 text-cyan" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">
                    {project.name}
                  </span>
                </span>
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
                  {problems.length > 0 ? (
                    <Chip tone="warn" icon={<AlertTriangle />}>
                      Needs fixing
                    </Chip>
                  ) : (
                    <span className="font-mono">
                      ×{stats.scale} · {compact(stats.params)} params
                    </span>
                  )}
                  {project.best_psnr !== null && (
                    <span className="font-mono">best {project.best_psnr.toFixed(2)} dB</span>
                  )}
                  <span>{relativeTime(project.updated_at)}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Start a model from a template or a bare input and output. */
export function NewProjectDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (project: ForgeProject) => void;
}) {
  const { data: templates } = useForgeTemplates();
  const create = useCreateProject();
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("siqe-classic");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const chosen = templates?.find((t) => t.id === template);
    create.mutate(
      { name: name.trim() || chosen?.name || "Untitled model", template: template || null },
      {
        onSuccess: (project) => {
          setName("");
          onCreated(project);
        },
      },
    );
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="New model"
      footer={
        <div className="flex justify-end">
          <Button variant="primary" type="submit" form="new-model" loading={create.isPending}>
            Create model
          </Button>
        </div>
      }
    >
      <form id="new-model" onSubmit={submit} className="grid gap-4">
        <label className="grid gap-1 text-[12.5px] text-fg-2">
          Name
          <input
            className={INPUT}
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
            placeholder={templates?.find((t) => t.id === template)?.name ?? "Untitled model"}
            // biome-ignore lint/a11y/noAutofocus: the drawer opens to name the model
            autoFocus
          />
        </label>
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-[12.5px] text-fg-2">Start from</legend>
          {[
            ...(templates ?? []).map((t) => ({
              id: t.id,
              name: t.name,
              summary: t.summary,
              meta: `${t.scale ? `×${t.scale} · ` : "denoise · "}${compact(t.params)} params`,
            })),
            { id: "", name: "Just an input and an output", summary: "Draw the rest yourself.", meta: "" },
          ].map((t) => (
            <label
              key={t.id || "blank"}
              className="flex cursor-pointer items-start gap-2 rounded-lg border border-line p-2.5 has-[:checked]:border-cyan has-[:checked]:bg-cyan-soft"
            >
              <input
                type="radio"
                name="template"
                checked={template === t.id}
                onChange={() => setTemplate(t.id)}
                className="mt-0.5 accent-[var(--cyan)]"
              />
              <span className="grid min-w-0 gap-0.5">
                <span className="flex flex-wrap items-baseline gap-x-2 text-[12.5px] font-medium text-fg">
                  {t.name}
                  {t.meta && <span className="font-mono text-[11px] font-normal text-muted">{t.meta}</span>}
                </span>
                <span className="text-[12px] text-fg-2">{t.summary}</span>
              </span>
            </label>
          ))}
        </fieldset>
        {create.error && (
          <p role="alert" className="text-[12px] text-err">
            {errorMessage(create.error).message} {errorMessage(create.error).fix}
          </p>
        )}
      </form>
    </Drawer>
  );
}
