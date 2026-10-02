import { useNavigate, useSearch } from "@tanstack/react-router";
import { clsx } from "clsx";
import {
  AlertTriangle,
  ArrowLeft,
  Boxes,
  CheckCircle2,
  Code2,
  Copy,
  Database,
  Gauge,
  PanelLeft,
  Plus,
  Trash2,
  TrendingUp,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Drawer } from "@/components/ui/Drawer";
import { Spinner } from "@/components/ui/Spinner";
import { INPUT } from "@/features/library/RulesEditor";
import {
  errorMessage,
  type ForgeBlock,
  type ForgeFix,
  type ForgeGraph,
  type ForgeProject,
} from "@/lib/api/client";
import { useMedia } from "@/lib/media";
import {
  useCheck,
  useDatasets,
  useDeleteProject,
  useDuplicateProject,
  useForgeCatalog,
  useForgeRun,
  useForgeRuns,
  useProjects,
  useUpdateProject,
} from "./api";
import { Canvas } from "./Canvas";
import { CodeView } from "./CodeView";
import { DatasetDetail, DatasetList, NewDatasetDialog } from "./Datasets";
import { applyFix, compact, defaultParams, newBlockId, placeNew } from "./graph";
import { BlockInspector, ModelSummary } from "./Inspector";
import { Palette } from "./Palette";
import { NewProjectDialog, ProjectList } from "./Projects";
import { RunDetail, RunList, TrainForm } from "./Train";

export type ForgeTab = "design" | "code" | "data" | "train";

export interface ForgeSearch {
  project?: string;
  tab?: ForgeTab;
  run?: string;
  dataset?: string;
}

type SaveState = "saved" | "pending" | "saving" | "failed";

const SAVE_DELAY = 700;
const CHECK_DELAY = 150;

/** A local copy of the graph being drawn: checked as you go, saved shortly after each change. */
function useDraft(project: ForgeProject | undefined) {
  const update = useUpdateProject();
  const [graph, setGraph] = useState<ForgeGraph | null>(project?.graph ?? null);
  const [checked, setChecked] = useState<ForgeGraph | null>(project?.graph ?? null);
  const [state, setState] = useState<SaveState>("saved");
  const loaded = useRef<string | undefined>(project?.id);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const checkTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (project && loaded.current !== project.id) {
      loaded.current = project.id;
      clearTimeout(saveTimer.current);
      clearTimeout(checkTimer.current);
      setGraph(project.graph);
      setChecked(project.graph);
      setState("saved");
    } else if (project && graph === null) {
      setGraph(project.graph);
      setChecked(project.graph);
    }
  }, [project, graph]);

  const change = useCallback(
    (next: ForgeGraph) => {
      if (!project) return;
      setGraph(next);
      setState("pending");
      clearTimeout(checkTimer.current);
      checkTimer.current = setTimeout(() => setChecked(next), CHECK_DELAY);
      clearTimeout(saveTimer.current);
      const id = project.id;
      saveTimer.current = setTimeout(() => {
        setState("saving");
        update.mutate(
          { id, graph: next },
          {
            onSuccess: () => setState((s) => (s === "saving" ? "saved" : s)),
            onError: () => setState("failed"),
          },
        );
      }, SAVE_DELAY);
    },
    [project, update.mutate],
  );

  useEffect(
    () => () => {
      clearTimeout(saveTimer.current);
      clearTimeout(checkTimer.current);
    },
    [],
  );
  const { data: analysis } = useCheck(checked);
  return {
    graph: graph ?? project?.graph ?? null,
    analysis: analysis ?? project?.analysis,
    change,
    state,
    error: update.error,
  };
}

function SaveIndicator({ state }: { state: SaveState }) {
  if (state === "failed") {
    return (
      <Chip tone="err" icon={<AlertTriangle />}>
        Not saved
      </Chip>
    );
  }
  if (state === "saved") {
    return (
      <span className="flex items-center gap-1 text-[11.5px] text-muted">
        <CheckCircle2 className="size-3.5" aria-hidden="true" />
        Saved
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[11.5px] text-muted">
      <Spinner className="size-3" />
      Saving…
    </span>
  );
}

function Empty({ onNew }: { onNew: () => void }) {
  return (
    <div className="mx-auto grid max-w-[560px] justify-items-center gap-3 p-10 text-center">
      <Boxes className="size-9 text-gold" aria-hidden="true" />
      <h2 className="font-display text-[20px] font-medium">Design and train your own model</h2>
      <p className="text-[13px] text-fg-2">
        Start from SIQE Classic or another template, change it block by block with live shape checks, train it
        on your own photos, and publish it to AI Lab. No code needed, and you can read the PyTorch it makes.
      </p>
      <Button variant="primary" icon={<Plus />} onClick={onNew}>
        Make your first model
      </Button>
    </div>
  );
}

const TABS: [ForgeTab, string, typeof Boxes][] = [
  ["design", "Design", Boxes],
  ["code", "Code", Code2],
  ["data", "Data", Database],
  ["train", "Train", TrendingUp],
];

export function ForgePage() {
  const search = useSearch({ from: "/forge" }) as ForgeSearch;
  const navigate = useNavigate({ from: "/forge" });
  const wide = useMedia("(min-width: 1024px)");
  const roomy = useMedia("(min-width: 1800px)");
  const docked = useMedia("(min-width: 1536px)");
  const { data: projects, isLoading } = useProjects();
  const { data: catalog } = useForgeCatalog();
  const { data: datasets } = useDatasets();
  const { data: runs } = useForgeRuns();
  const [creating, setCreating] = useState(false);
  const [newDataset, setNewDataset] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [armed, setArmed] = useState(false);
  const update = useUpdateProject();
  const duplicate = useDuplicateProject();
  const remove = useDeleteProject();

  const list = projects ?? [];
  const project = list.find((p) => p.id === search.project) ?? (wide ? list[0] : undefined);
  const { graph, analysis, change, state: saveState, error: saveError } = useDraft(project);
  const specs = useMemo(() => new Map((catalog ?? []).map((b) => [b.type, b])), [catalog]);
  const tab: ForgeTab = search.tab ?? "design";
  const projectRuns = useMemo(
    () => (runs ?? []).filter((r) => r.project_id === project?.id),
    [runs, project?.id],
  );
  const shownRunId = search.run ?? projectRuns[0]?.id;
  const { data: shownRun } = useForgeRun(tab === "train" ? shownRunId : undefined);
  const allDatasets = datasets ?? [];
  const shownDataset = allDatasets.find((d) => d.id === search.dataset) ?? allDatasets[0];
  const [name, setName] = useState(project?.name ?? "");

  // biome-ignore lint/correctness/useExhaustiveDependencies: start fresh whenever another model opens
  useEffect(() => {
    setSelected(null);
    setArmed(false);
    setName(project?.name ?? "");
  }, [project?.id]);

  const go = (next: ForgeSearch) => navigate({ search: { project: project?.id, ...next } });
  const pick = (id: string) => {
    setListOpen(false);
    navigate({ search: { project: id, tab: search.tab } });
  };

  const addBlock = (type: string, at?: { x: number; y: number }) => {
    const spec = specs.get(type);
    if (!spec || !graph) return;
    const blocks = graph.blocks ?? [];
    const id = newBlockId(
      type,
      blocks.map((b) => b.id),
    );
    const block: ForgeBlock = {
      id,
      type,
      params: defaultParams(spec),
      position: at ?? placeNew(graph, selected),
    };
    const links = [...(graph.links ?? [])];
    // Clicking a block in the palette while another is selected inserts it after that block.
    const from = !at && selected ? blocks.find((b) => b.id === selected) : undefined;
    if (from && specs.get(from.type)?.has_output) {
      const onward = links.filter((l) => l.source === from.id);
      const kept = links.filter((l) => l.source !== from.id);
      kept.push({ source: from.id, target: id });
      if (spec.has_output) for (const l of onward) kept.push({ source: id, target: l.target });
      links.splice(0, links.length, ...kept);
    }
    change({ ...graph, blocks: [...blocks, block], links });
    setSelected(id);
    setAdding(false);
  };

  const changeBlock = (block: ForgeBlock) => {
    if (!graph) return;
    change({ ...graph, blocks: (graph.blocks ?? []).map((b) => (b.id === block.id ? block : b)) });
  };

  const deleteBlock = (id: string) => {
    if (!graph) return;
    change({
      ...graph,
      blocks: (graph.blocks ?? []).filter((b) => b.id !== id),
      links: (graph.links ?? []).filter((l) => l.source !== id && l.target !== id),
    });
    setSelected(null);
  };

  const fix = (f: ForgeFix) => {
    if (graph) change(applyFix(graph, f));
  };

  if (isLoading) {
    return (
      <div className="grid place-items-center p-10">
        <Spinner />
      </div>
    );
  }

  const newDialog = (
    <NewProjectDialog
      open={creating}
      onClose={() => setCreating(false)}
      onCreated={(p) => {
        setCreating(false);
        navigate({ search: { project: p.id } });
      }}
    />
  );
  const datasetDialog = (
    <NewDatasetDialog
      open={newDataset}
      onClose={() => setNewDataset(false)}
      onCreated={(d) => {
        setNewDataset(false);
        go({ tab: "data", dataset: d.id });
      }}
    />
  );

  if (list.length === 0) {
    return (
      <>
        <Empty onNew={() => setCreating(true)} />
        {newDialog}
      </>
    );
  }

  const sidebar = (
    <ProjectList
      projects={list}
      current={project?.id}
      onPick={pick}
      onNew={() => {
        setListOpen(false);
        setCreating(true);
      }}
    />
  );

  if (!project || !graph) {
    return (
      <div className="p-4">
        {sidebar}
        {newDialog}
      </div>
    );
  }

  const selectedBlock = (graph.blocks ?? []).find((b) => b.id === selected) ?? null;
  const blockProblems = (analysis?.problems ?? []).filter((p) => p.block === selectedBlock?.id);
  const inspector = selectedBlock ? (
    <BlockInspector
      block={selectedBlock}
      spec={specs.get(selectedBlock.type)}
      inputs={(graph.links ?? [])
        .filter((l) => l.target === selectedBlock.id)
        .map((l) => analysis?.shapes[l.source])}
      shape={analysis?.shapes[selectedBlock.id]}
      problems={blockProblems.map((p) => p.message)}
      fixes={blockProblems.flatMap((p) => (p.fix ? [p.fix] : []))}
      onChange={changeBlock}
      onFix={fix}
      onDelete={() => deleteBlock(selectedBlock.id)}
      onClose={wide ? undefined : () => setSelected(null)}
    />
  ) : (
    <div className="grid gap-5">
      <label className="grid gap-1 text-[12px] text-fg-2">
        <span className="text-fg">Model name</span>
        <input
          className={INPUT}
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            const trimmed = name.trim();
            if (trimmed && trimmed !== project.name) update.mutate({ id: project.id, name: trimmed });
            else setName(project.name);
          }}
        />
      </label>
      <ModelSummary
        analysis={analysis}
        onFix={fix}
        onShow={(id) => {
          setSelected(id);
          setSummaryOpen(false);
        }}
      />
    </div>
  );
  const problems = analysis?.problems.length ?? 0;
  const stats = analysis?.stats;

  return (
    <div className="flex h-full min-h-0">
      {roomy && (
        <aside className="w-[248px] shrink-0 overflow-y-auto border-r border-line bg-panel p-3">
          {sidebar}
        </aside>
      )}
      <section className="flex min-w-0 flex-1 flex-col" aria-label={project.name}>
        <header className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-2">
          {!wide && (
            <Button
              variant="ghost"
              size="sm"
              icon={<ArrowLeft />}
              onClick={() => navigate({ search: {} })}
              aria-label="All models"
            />
          )}
          {wide && !roomy && (
            <Button variant="ghost" size="sm" icon={<PanelLeft />} onClick={() => setListOpen(true)}>
              Models
            </Button>
          )}
          <h1 className="min-w-0 truncate font-display text-[16px] font-medium">{project.name}</h1>
          {stats && problems === 0 && (
            <span className="font-mono text-[11.5px] text-fg-2 max-sm:hidden">
              ×{stats.scale} · {compact(stats.params)} params · {stats.gmacs_per_megapixel.toFixed(1)} GMAC/MP
            </span>
          )}
          {problems > 0 && (
            <Chip tone="warn" icon={<AlertTriangle />}>
              {problems === 1 ? "1 problem" : `${problems} problems`}
            </Chip>
          )}
          <SaveIndicator state={saveState} />
          <span className="flex-1" />
          <div role="tablist" aria-label="View" className="flex rounded-lg border border-line-2 p-0.5">
            {TABS.map(([value, label, Icon]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={tab === value}
                onClick={() => go(value === "design" ? {} : { tab: value })}
                className={clsx(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] transition [&_svg]:size-3.5",
                  tab === value ? "bg-cyan-soft text-fg" : "text-fg-2 hover:text-fg",
                )}
              >
                <Icon aria-hidden="true" />
                <span className={clsx(tab !== value && "max-sm:sr-only")}>{label}</span>
              </button>
            ))}
          </div>
          {!wide && tab === "design" && (
            <Button
              size="sm"
              variant="ghost"
              icon={<Gauge />}
              onClick={() => setSummaryOpen(true)}
              aria-label="Model size and problems"
            />
          )}
          <Button
            size="sm"
            variant="ghost"
            icon={<Copy />}
            loading={duplicate.isPending}
            onClick={() => duplicate.mutate(project.id, { onSuccess: (p) => pick(p.id) })}
            title="Make a copy to try a change"
          >
            <span className="max-md:sr-only">Duplicate</span>
          </Button>
          <Button
            size="sm"
            variant="danger"
            icon={<Trash2 />}
            loading={remove.isPending}
            onBlur={() => setArmed(false)}
            onClick={() =>
              armed
                ? remove.mutate(project.id, { onSuccess: () => navigate({ search: {} }) })
                : setArmed(true)
            }
            aria-label={armed ? `Confirm deleting ${project.name}` : `Delete ${project.name}`}
            title="Training runs and published models stay"
          >
            <span className={clsx(!armed && "max-md:sr-only")}>{armed ? "Delete model?" : "Delete"}</span>
          </Button>
        </header>
        {saveState === "failed" && saveError && (
          <p role="alert" className="border-b border-err/40 bg-err-soft px-3 py-1.5 text-[12px] text-err">
            Your last change wasn't saved: {errorMessage(saveError).message}
          </p>
        )}

        {tab === "design" && (
          <div className="flex min-h-0 flex-1">
            {docked && (
              <aside className="w-[200px] shrink-0 overflow-y-auto border-r border-line bg-panel p-3">
                <Palette catalog={catalog ?? []} onAdd={addBlock} />
              </aside>
            )}
            <div className="relative min-w-0 flex-1 max-lg:min-h-[60vh]">
              <Canvas
                key={project.id}
                graph={graph}
                specs={specs}
                analysis={analysis}
                selected={selected}
                onChange={change}
                onSelect={setSelected}
                onDropBlock={addBlock}
              />
              {!docked && (
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Plus />}
                  className={clsx("absolute", wide ? "top-3 left-3" : "right-3 bottom-3")}
                  onClick={() => setAdding((v) => !v)}
                  aria-expanded={adding}
                >
                  Add block
                </Button>
              )}
              {wide && !docked && adding && (
                <div className="absolute top-12 left-3 max-h-[calc(100%-4rem)] w-[220px] overflow-y-auto rounded-xl border border-line bg-panel p-3 shadow-float">
                  <Palette catalog={catalog ?? []} onAdd={addBlock} />
                </div>
              )}
            </div>
            {wide && (
              <aside className="w-[320px] shrink-0 overflow-y-auto border-l border-line bg-panel p-4">
                {inspector}
              </aside>
            )}
          </div>
        )}

        {tab === "code" && (
          <div className="min-h-0 flex-1">
            <CodeView project={project} />
          </div>
        )}

        {tab === "data" && (
          <div className="grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[300px_1fr]">
            <aside className="border-line p-3 max-lg:border-b lg:overflow-y-auto lg:border-r">
              <DatasetList
                datasets={allDatasets}
                current={shownDataset?.id}
                onPick={(id) => go({ tab: "data", dataset: id })}
                onNew={() => setNewDataset(true)}
              />
            </aside>
            <div className="min-w-0 p-4 lg:overflow-y-auto">
              {shownDataset ? (
                <DatasetDetail
                  key={shownDataset.id}
                  dataset={shownDataset}
                  onDeleted={() => go({ tab: "data" })}
                />
              ) : (
                <p className="text-[12.5px] text-fg-2">
                  Build a dataset from your Library to train on. Any photos work; sharp, large ones work best.
                </p>
              )}
            </div>
          </div>
        )}

        {tab === "train" && (
          <div className="grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[360px_1fr]">
            <aside className="grid content-start gap-5 border-line p-4 max-lg:border-b lg:overflow-y-auto lg:border-r">
              <TrainForm
                key={project.id}
                project={{ ...project, analysis: analysis ?? project.analysis }}
                datasets={allDatasets}
                onStarted={(run) => go({ tab: "train", run: run.id })}
                onNewDataset={() => setNewDataset(true)}
              />
              <section className="grid gap-2">
                <h2 className="eyebrow">Runs of this model</h2>
                <RunList
                  runs={projectRuns}
                  current={shownRunId}
                  onPick={(id) => go({ tab: "train", run: id })}
                />
              </section>
            </aside>
            <div className="min-w-0 p-4 lg:overflow-y-auto">
              {shownRun ? (
                <RunDetail detail={shownRun} />
              ) : shownRunId ? (
                <Spinner />
              ) : (
                <p className="text-[12.5px] text-fg-2">
                  Start a run to see the loss and PSNR charts here as it learns.
                </p>
              )}
            </div>
          </div>
        )}
      </section>

      {!wide && (
        <>
          <Drawer open={adding} onClose={() => setAdding(false)} title="Add a block">
            <Palette catalog={catalog ?? []} onAdd={addBlock} />
          </Drawer>
          <Drawer open={Boolean(selectedBlock)} onClose={() => setSelected(null)} title="Block settings">
            {inspector}
          </Drawer>
          <Drawer
            open={summaryOpen && !selectedBlock}
            onClose={() => setSummaryOpen(false)}
            title="This model"
          >
            {inspector}
          </Drawer>
        </>
      )}
      {wide && !roomy && (
        <Drawer open={listOpen} onClose={() => setListOpen(false)} title="Models">
          {sidebar}
        </Drawer>
      )}
      {newDialog}
      {datasetDialog}
    </div>
  );
}
