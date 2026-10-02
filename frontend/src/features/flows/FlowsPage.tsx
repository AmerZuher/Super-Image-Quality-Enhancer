import { useNavigate, useSearch } from "@tanstack/react-router";
import { clsx } from "clsx";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Copy,
  Download,
  FolderInput,
  ListChecks,
  PanelLeft,
  Play,
  Plus,
  Settings2,
  Sparkles,
  Trash2,
  Workflow,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Drawer } from "@/components/ui/Drawer";
import { Spinner } from "@/components/ui/Spinner";
import { useModels } from "@/features/ailab/api";
import { useAlbums } from "@/features/library/api";
import { errorMessage, type Flow, type FlowDocument, type FlowNode, type FlowRun } from "@/lib/api/client";
import { useMedia } from "@/lib/media";
import {
  flowFile,
  useDeleteFlow,
  useDuplicateFlow,
  useFlowCatalog,
  useFlows,
  useRun,
  useRuns,
  useUpdateFlow,
} from "./api";
import { Canvas } from "./Canvas";
import { FlowList, NewFlowDialog } from "./FlowList";
import {
  countsByNode,
  defaultParams,
  newNodeId,
  placeNew,
  problemsByNode,
  type SummaryContext,
} from "./graph";
import { BlockInspector, FlowSettings } from "./Inspector";
import { Palette } from "./Palette";
import { RunDialog } from "./RunDialog";
import { RunDetail, RunList } from "./Runs";

export interface FlowsSearch {
  flow?: string;
  tab?: "runs";
  run?: string;
  /** Opened from the Library's selection bar: offer to run on the selected images. */
  source?: "selection";
}

type SaveState = "saved" | "pending" | "saving" | "failed";

const SAVE_DELAY = 700;

/** Keeps a local copy of the flow being edited and saves it shortly after each change. */
function useDraft(flow: Flow | undefined) {
  const update = useUpdateFlow();
  const [doc, setDoc] = useState<FlowDocument | null>(flow?.document ?? null);
  const [state, setState] = useState<SaveState>("saved");
  const loaded = useRef<string | undefined>(flow?.id);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (flow && loaded.current !== flow.id) {
      loaded.current = flow.id;
      clearTimeout(timer.current);
      setDoc(flow.document);
      setState("saved");
    } else if (flow && doc === null) {
      setDoc(flow.document);
    }
  }, [flow, doc]);

  const change = useCallback(
    (next: FlowDocument) => {
      if (!flow) return;
      setDoc(next);
      setState("pending");
      clearTimeout(timer.current);
      const id = flow.id;
      timer.current = setTimeout(() => {
        setState("saving");
        update.mutate(
          { id, document: next },
          {
            onSuccess: () => setState((s) => (s === "saving" ? "saved" : s)),
            onError: () => setState("failed"),
          },
        );
      }, SAVE_DELAY);
    },
    [flow, update.mutate],
  );

  useEffect(() => () => clearTimeout(timer.current), []);
  return { doc: doc ?? flow?.document ?? null, change, state, error: update.error };
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
    <div className="mx-auto grid max-w-[520px] justify-items-center gap-3 p-10 text-center">
      <Workflow className="size-9 text-cyan" aria-hidden="true" />
      <h2 className="font-display text-[20px] font-medium">Automate the work you repeat</h2>
      <p className="text-[13px] text-fg-2">
        A flow is a chain of blocks: pick images, sort them with If, edit or enhance them, then export, tag or
        file them. Run it on a selection, an album or a whole folder as images arrive.
      </p>
      <Button variant="primary" icon={<Plus />} onClick={onNew}>
        Make your first flow
      </Button>
    </div>
  );
}

export function FlowsPage() {
  const search = useSearch({ from: "/flows" }) as FlowsSearch;
  const navigate = useNavigate({ from: "/flows" });
  const wide = useMedia("(min-width: 1024px)");
  // The flow list gets its own column only when the canvas still has room beside it.
  const roomy = useMedia("(min-width: 1536px)");
  const [listOpen, setListOpen] = useState(false);
  const { data: flows, isLoading } = useFlows();
  const { data: catalog } = useFlowCatalog();
  const { data: models } = useModels();
  const { data: albums } = useAlbums();
  const [creating, setCreating] = useState(false);
  const [running, setRunning] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [armed, setArmed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const update = useUpdateFlow();
  const duplicate = useDuplicateFlow();
  const remove = useDeleteFlow();

  const list = flows ?? [];
  const flow = list.find((f) => f.id === search.flow) ?? (wide ? list[0] : undefined);
  const { doc, change, state: saveState, error: saveError } = useDraft(flow);
  const specs = useMemo(() => new Map((catalog ?? []).map((n) => [n.type, n])), [catalog]);
  const blocks = useMemo(() => (catalog ?? []).filter((n) => n.category !== "input"), [catalog]);
  const problems = useMemo(() => problemsByNode(flow?.problems ?? []), [flow?.problems]);
  const ctx = useMemo<SummaryContext>(() => ({ models, albums }), [models, albums]);
  const { data: runs } = useRuns(flow?.id);
  const lastRunId = flow?.last_run?.id;
  const shownRunId = search.run ?? runs?.[0]?.id;
  const { data: lastRun } = useRun(lastRunId);
  const { data: shownRun } = useRun(search.tab === "runs" ? shownRunId : undefined);

  const counts = useMemo(() => {
    if (!lastRun || !doc) return undefined;
    const map = countsByNode(lastRun.items);
    const input = (doc.nodes ?? []).find((n) => n.type === "input");
    if (input) map.set(input.id, lastRun.run.total);
    return map;
  }, [lastRun, doc]);
  const live = lastRun?.run.state === "running" || lastRun?.run.state === "queued";

  // Arriving from the Library with images selected: open the run dialog once a flow is chosen.
  useEffect(() => {
    if (search.source === "selection" && flow) setRunning(true);
  }, [search.source, flow]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: start fresh whenever another flow opens
  useEffect(() => {
    setSelected(null);
    setArmed(false);
  }, [flow?.id]);

  const pick = (id: string) => {
    setListOpen(false);
    navigate({ search: { flow: id } });
  };
  const selectedNode = (doc?.nodes ?? []).find((n) => n.id === selected) ?? null;

  const addBlock = (type: string, at?: { x: number; y: number }) => {
    const spec = specs.get(type);
    if (!spec || !doc) return;
    const id = newNodeId(
      type,
      (doc.nodes ?? []).map((n) => n.id),
    );
    const node: FlowNode = { id, type, params: defaultParams(spec), position: at ?? placeNew(doc, selected) };
    const edges = [...(doc.edges ?? [])];
    // Clicking a block in the palette while another is selected connects the two.
    const from = !at && selected ? (doc.nodes ?? []).find((n) => n.id === selected) : undefined;
    const fromSpec = from ? specs.get(from.type) : undefined;
    if (from && fromSpec && fromSpec.outputs.length > 0) {
      const free = fromSpec.outputs.find((p) => !edges.some((e) => e.source === from.id && e.port === p));
      edges.push({ source: from.id, target: id, port: free ?? fromSpec.outputs[0] ?? "out" });
    }
    change({ ...doc, nodes: [...(doc.nodes ?? []), node], edges });
    setSelected(id);
    setAdding(false);
  };

  const changeNode = (node: FlowNode) => {
    if (!doc) return;
    change({ ...doc, nodes: (doc.nodes ?? []).map((n) => (n.id === node.id ? node : n)) });
  };

  const deleteNode = (id: string) => {
    if (!doc) return;
    change({
      ...doc,
      nodes: (doc.nodes ?? []).filter((n) => n.id !== id),
      edges: (doc.edges ?? []).filter((e) => e.source !== id && e.target !== id),
    });
    setSelected(null);
  };

  const exportFile = async () => {
    if (!flow) return;
    const file = await flowFile(flow.id);
    const blob = new Blob([JSON.stringify(file, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${flow.name.replace(/[^\w\- ]+/g, "").trim() || "flow"}.flow.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const started = (run: FlowRun) => {
    setRunning(false);
    navigate({ search: { flow: flow?.id, tab: "runs", run: run.id } });
  };

  if (isLoading) {
    return (
      <div className="grid place-items-center p-10">
        <Spinner />
      </div>
    );
  }

  const newDialog = (
    <NewFlowDialog
      open={creating}
      onClose={() => setCreating(false)}
      onCreated={(f) => {
        setCreating(false);
        pick(f.id);
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

  const sidebar = <FlowList flows={list} current={flow?.id} onPick={pick} onNew={() => setCreating(true)} />;

  if (!flow || !doc) {
    // Phone, nothing chosen yet: just the list.
    return (
      <div className="p-4">
        {sidebar}
        {newDialog}
      </div>
    );
  }

  const tab = search.tab === "runs" ? "runs" : "edit";
  const nodeSpec = selectedNode ? specs.get(selectedNode.type) : undefined;
  const inspector = selectedNode ? (
    <BlockInspector
      node={selectedNode}
      spec={nodeSpec}
      problems={problems.get(selectedNode.id) ?? []}
      onChange={changeNode}
      onDelete={() => deleteNode(selectedNode.id)}
      onClose={wide ? undefined : () => setSelected(null)}
    />
  ) : (
    <FlowSettings
      key={flow.id}
      flow={flow}
      saving={update.isPending}
      onSave={(changes) => update.mutate({ id: flow.id, ...changes })}
    />
  );

  return (
    <div className="flex h-full min-h-0">
      {roomy && (
        <aside className="w-[248px] shrink-0 overflow-y-auto border-r border-line bg-panel p-3">
          {sidebar}
        </aside>
      )}
      <section className="flex min-w-0 flex-1 flex-col" aria-label={flow.name}>
        <header className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-2">
          {!wide && (
            <Button
              variant="ghost"
              size="sm"
              icon={<ArrowLeft />}
              onClick={() => navigate({ search: {} })}
              aria-label="All flows"
            />
          )}
          {wide && !roomy && (
            <Button variant="ghost" size="sm" icon={<PanelLeft />} onClick={() => setListOpen(true)}>
              Flows
            </Button>
          )}
          <h1 className="min-w-0 truncate font-display text-[16px] font-medium">{flow.name}</h1>
          {flow.ai && (
            <Chip tone="gold" icon={<Sparkles />}>
              Uses AI
            </Chip>
          )}
          {flow.watch_enabled && (
            <Chip tone="ok" icon={<FolderInput />}>
              Watching {flow.watch_folder ? `/${flow.watch_folder}` : "import folder"}
            </Chip>
          )}
          {flow.problems.length > 0 && (
            <Chip tone="warn" icon={<AlertTriangle />}>
              {flow.problems.length === 1 ? "1 problem" : `${flow.problems.length} problems`}
            </Chip>
          )}
          <SaveIndicator state={saveState} />
          <span className="flex-1" />
          <div role="tablist" aria-label="View" className="flex rounded-lg border border-line-2 p-0.5">
            {(
              [
                ["edit", "Blocks", Workflow],
                ["runs", "Runs", ListChecks],
              ] as const
            ).map(([value, label, Icon]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={tab === value}
                onClick={() =>
                  navigate({
                    search: { flow: flow.id, ...(value === "runs" ? { tab: "runs" as const } : {}) },
                  })
                }
                className={clsx(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] transition [&_svg]:size-3.5",
                  tab === value ? "bg-cyan-soft text-fg" : "text-fg-2 hover:text-fg",
                )}
              >
                <Icon aria-hidden="true" />
                {label}
              </button>
            ))}
          </div>
          {!wide && (
            <Button
              size="sm"
              variant="ghost"
              icon={<Settings2 />}
              onClick={() => setSettingsOpen(true)}
              aria-label="Flow settings"
            />
          )}
          <Button
            size="sm"
            variant="ghost"
            icon={<Download />}
            onClick={exportFile}
            title="Save as a .flow.json file"
          >
            <span className="max-md:sr-only">Export</span>
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={<Copy />}
            loading={duplicate.isPending}
            onClick={() => duplicate.mutate(flow.id, { onSuccess: (f) => pick(f.id) })}
            title="Make a copy"
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
              armed ? remove.mutate(flow.id, { onSuccess: () => navigate({ search: {} }) }) : setArmed(true)
            }
            aria-label={armed ? `Confirm deleting ${flow.name}` : `Delete ${flow.name}`}
          >
            <span className={clsx(!armed && "max-md:sr-only")}>{armed ? "Delete flow?" : "Delete"}</span>
          </Button>
          <Button
            size="sm"
            variant={flow.ai ? "ai" : "primary"}
            icon={<Play />}
            onClick={() => setRunning(true)}
            disabled={flow.problems.length > 0}
            title={flow.problems.length ? "Fix the problems first" : undefined}
          >
            Run
          </Button>
        </header>
        {saveState === "failed" && saveError && (
          <p role="alert" className="border-b border-err/40 bg-err-soft px-3 py-1.5 text-[12px] text-err">
            Your last change wasn't saved: {errorMessage(saveError).message}
          </p>
        )}

        {tab === "edit" ? (
          <div className="flex min-h-0 flex-1">
            {roomy && (
              <aside className="w-[200px] shrink-0 overflow-y-auto border-r border-line bg-panel p-3">
                <Palette catalog={blocks} onAdd={addBlock} />
              </aside>
            )}
            <div className="relative min-w-0 flex-1 max-lg:min-h-[60vh]">
              <Canvas
                key={flow.id}
                doc={doc}
                specs={specs}
                problems={problems}
                counts={counts}
                live={live}
                selected={selected}
                ctx={ctx}
                onChange={change}
                onSelect={setSelected}
                onDropBlock={addBlock}
              />
              {!roomy && (
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
              {wide && !roomy && adding && (
                <div className="absolute top-12 left-3 max-h-[calc(100%-4rem)] w-[220px] overflow-y-auto rounded-xl border border-line bg-panel p-3 shadow-float">
                  <Palette catalog={blocks} onAdd={addBlock} />
                </div>
              )}
            </div>
            {wide && (
              <aside className="w-[320px] shrink-0 overflow-y-auto border-l border-line bg-panel p-4">
                {inspector}
              </aside>
            )}
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[320px_1fr]">
            <aside className="border-line p-3 max-lg:border-b lg:overflow-y-auto lg:border-r">
              <RunList
                runs={runs ?? []}
                current={shownRunId}
                onPick={(id) => navigate({ search: { flow: flow.id, tab: "runs", run: id } })}
              />
            </aside>
            <div className="min-w-0 p-3 lg:overflow-y-auto">
              {shownRun ? <RunDetail detail={shownRun} /> : shownRunId ? <Spinner /> : null}
            </div>
          </div>
        )}
      </section>

      {!wide && (
        <>
          <Drawer open={adding} onClose={() => setAdding(false)} title="Add a block">
            <Palette catalog={blocks} onAdd={addBlock} />
          </Drawer>
          <Drawer open={Boolean(selectedNode)} onClose={() => setSelected(null)} title="Block settings">
            {inspector}
          </Drawer>
          <Drawer
            open={settingsOpen && !selectedNode}
            onClose={() => setSettingsOpen(false)}
            title="Flow settings"
          >
            <FlowSettings
              key={flow.id}
              flow={flow}
              saving={update.isPending}
              onSave={(changes) => update.mutate({ id: flow.id, ...changes })}
            />
          </Drawer>
        </>
      )}
      <RunDialog
        flow={flow}
        open={running}
        preferSelection={search.source === "selection"}
        onClose={() => {
          setRunning(false);
          if (search.source) navigate({ search: { flow: flow.id } });
        }}
        onStarted={started}
      />
      {wide && !roomy && (
        <Drawer open={listOpen} onClose={() => setListOpen(false)} title="Flows">
          {sidebar}
        </Drawer>
      )}
      {newDialog}
    </div>
  );
}
