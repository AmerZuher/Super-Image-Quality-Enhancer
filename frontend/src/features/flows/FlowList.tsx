import { clsx } from "clsx";
import { AlertTriangle, FileUp, FolderInput, Plus, Sparkles, Workflow } from "lucide-react";
import { type ChangeEvent, type FormEvent, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Drawer } from "@/components/ui/Drawer";
import { JobStateChip } from "@/components/ui/JobStateChip";
import { INPUT } from "@/features/library/RulesEditor";
import { errorMessage, type Flow, type FlowDocument } from "@/lib/api/client";
import { relativeTime } from "@/lib/format";
import { useCreateFlow, useImportFlow, useRecipes } from "./api";

export function FlowList({
  flows,
  current,
  onPick,
  onNew,
}: {
  flows: Flow[];
  current: string | undefined;
  onPick: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <div className="grid content-start gap-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="eyebrow">Your flows</h2>
        <Button size="sm" variant="primary" icon={<Plus />} onClick={onNew}>
          New flow
        </Button>
      </div>
      <ul className="grid gap-1" aria-label="Flows">
        {flows.map((flow) => (
          <li key={flow.id}>
            <button
              type="button"
              onClick={() => onPick(flow.id)}
              aria-current={current === flow.id ? "page" : undefined}
              className={clsx(
                "grid w-full gap-1 rounded-lg border px-2.5 py-2 text-left transition",
                current === flow.id
                  ? "border-cyan bg-cyan-soft"
                  : "border-transparent hover:border-line-2 hover:bg-panel-2",
              )}
            >
              <span className="flex items-center gap-1.5">
                <Workflow
                  className={clsx("size-3.5 shrink-0", flow.ai ? "text-gold" : "text-cyan")}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">{flow.name}</span>
              </span>
              <span className="flex flex-wrap items-center gap-1">
                {flow.problems.length > 0 && (
                  <Chip tone="warn" icon={<AlertTriangle />}>
                    Needs fixing
                  </Chip>
                )}
                {flow.watch_enabled && (
                  <Chip tone="ok" icon={<FolderInput />}>
                    Watching
                  </Chip>
                )}
                {flow.last_run ? (
                  <>
                    <JobStateChip state={flow.last_run.state} />
                    <span className="text-[11px] text-muted">{relativeTime(flow.last_run.created_at)}</span>
                  </>
                ) : (
                  flow.problems.length === 0 && <span className="text-[11px] text-muted">Not run yet</span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface FlowFile {
  name?: string;
  description?: string;
  document?: FlowDocument;
}

/** Start a flow from a recipe, from scratch, or from a .flow.json file. */
export function NewFlowDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (flow: Flow) => void;
}) {
  const { data: recipes } = useRecipes();
  const create = useCreateFlow();
  const importFlow = useImportFlow();
  const [name, setName] = useState("");
  const [recipe, setRecipe] = useState<string>("");
  const [fileError, setFileError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const chosen = recipes?.find((r) => r.id === recipe);
    create.mutate(
      { name: name.trim() || chosen?.name || "Untitled flow", recipe: recipe || undefined },
      {
        onSuccess: (flow) => {
          setName("");
          setRecipe("");
          onCreated(flow);
        },
      },
    );
  };

  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setFileError(null);
    let parsed: FlowFile;
    try {
      parsed = JSON.parse(await file.text()) as FlowFile;
    } catch {
      setFileError(`${file.name} isn't a flow file (it isn't valid JSON).`);
      return;
    }
    if (!parsed.document || !Array.isArray(parsed.document.nodes)) {
      setFileError(`${file.name} doesn't contain a flow.`);
      return;
    }
    importFlow.mutate(
      {
        name: parsed.name || file.name.replace(/\.flow\.json$|\.json$/i, ""),
        description: parsed.description ?? "",
        document: parsed.document,
      },
      { onSuccess: onCreated },
    );
  };

  const problem = create.error ?? importFlow.error;
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="New flow"
      footer={
        <div className="flex items-center justify-between gap-2">
          <Button icon={<FileUp />} onClick={() => fileInput.current?.click()} loading={importFlow.isPending}>
            Open a .flow.json file
          </Button>
          <Button variant="primary" type="submit" form="new-flow" loading={create.isPending}>
            Create flow
          </Button>
        </div>
      }
    >
      <form id="new-flow" onSubmit={submit} className="grid gap-4">
        <input
          ref={fileInput}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={onFile}
          aria-label="Flow file"
        />
        <label className="grid gap-1 text-[12.5px] text-fg-2">
          Name
          <input
            className={INPUT}
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
            placeholder={recipes?.find((r) => r.id === recipe)?.name ?? "Untitled flow"}
            // biome-ignore lint/a11y/noAutofocus: the drawer opens to name the flow
            autoFocus
          />
        </label>
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-[12.5px] text-fg-2">Start from</legend>
          {[
            {
              id: "",
              name: "A blank canvas",
              summary: "Just the Images block. Add what you need.",
              ai: false,
            },
            ...(recipes ?? []),
          ].map((r) => (
            <label
              key={r.id || "blank"}
              className="flex cursor-pointer items-start gap-2 rounded-lg border border-line p-2.5 has-[:checked]:border-cyan has-[:checked]:bg-cyan-soft"
            >
              <input
                type="radio"
                name="recipe"
                checked={recipe === r.id}
                onChange={() => setRecipe(r.id)}
                className="mt-0.5 accent-[var(--cyan)]"
              />
              <span className="grid gap-0.5">
                <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-fg">
                  {r.name}
                  {r.ai && (
                    <Chip tone="gold" icon={<Sparkles />}>
                      AI
                    </Chip>
                  )}
                </span>
                <span className="text-[12px] text-fg-2">{r.summary}</span>
              </span>
            </label>
          ))}
        </fieldset>
        {fileError && (
          <p role="alert" className="text-[12px] text-err">
            {fileError}
          </p>
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
