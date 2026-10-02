import type { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import type {
  Asset,
  FlowRun,
  FlowRunDetail,
  ForgeDataset,
  ForgeMetric,
  ForgeRun,
  ForgeRunDetail,
  Job,
  Model,
  Rendition,
  SystemStatus,
  Worker,
} from "./api/client";
import { keys, removeById, upsertById, upsertJob } from "./api/keys";

type Status = "connecting" | "open" | "closed";

interface EventsState {
  status: Status;
  since: number;
  set: (status: Status) => void;
}

export const useEventsStore = create<EventsState>((set) => ({
  status: "connecting",
  since: Date.now(),
  set: (status) => set((s) => (s.status === status ? s : { status, since: Date.now() })),
}));

interface ServerEvent {
  type: string;
  data: Record<string, unknown>;
}

let libraryTimer: ReturnType<typeof setTimeout> | undefined;

/** Library lists are paged queries; refetch them at most a few times a second. */
function refreshLibrary(client: QueryClient): void {
  if (libraryTimer) return;
  libraryTimer = setTimeout(() => {
    libraryTimer = undefined;
    void client.invalidateQueries({ queryKey: keys.library });
  }, 400);
}

/** Append streamed points, skipping any already loaded (a refetch can race the stream). */
export function mergeMetrics(current: ForgeMetric[], points: ForgeMetric[]): ForgeMetric[] {
  const seen = new Set(current.map((m) => `${m.kind}:${m.step}`));
  const fresh = points.filter((m) => !seen.has(`${m.kind}:${m.step}`));
  return fresh.length ? [...current, ...fresh] : current;
}

export function applyEvent(client: QueryClient, event: ServerEvent): void {
  switch (event.type) {
    case "library.updated":
      refreshLibrary(client);
      return;
    case "job.updated": {
      const job = event.data as unknown as Job & { truncated?: boolean };
      if (job.truncated) {
        void client.invalidateQueries({ queryKey: keys.jobs });
        return;
      }
      client.setQueryData<Job[]>(keys.jobs, (list) => upsertJob(list, job));
      client.setQueryData(keys.job(job.id), job);
      return;
    }
    case "worker.heartbeat": {
      const beat = event.data as unknown as Worker;
      client.setQueryData<SystemStatus>(keys.system, (system) => {
        if (!system) return system;
        const workers = system.workers.filter((w) => w.id !== beat.id);
        return { ...system, workers: [...workers, { ...beat, online: true }] };
      });
      return;
    }
    case "asset.updated": {
      const asset = event.data as unknown as Asset & { truncated?: boolean };
      if (asset.truncated) {
        void client.invalidateQueries({ queryKey: keys.assets, exact: true });
        return;
      }
      refreshLibrary(client);
      if (asset.quarantined_at) {
        // Quarantined images leave Studio and AI Lab until they're restored.
        client.setQueryData<Asset[]>(keys.assets, (list) => removeById(list, asset.id));
        return;
      }
      // Events leave out the edit document; merge so a cached copy keeps it.
      client.setQueryData<Asset[]>(keys.assets, (list) => upsertById(list, asset, true));
      if (asset.parent_id) {
        client.setQueryData<Asset[]>(keys.children(asset.parent_id), (list) =>
          list ? upsertById(list, asset, true) : list,
        );
      }
      return;
    }
    case "model.updated": {
      const model = event.data as unknown as Model;
      client.setQueryData<Model[]>(keys.models, (list) => list?.map((m) => (m.id === model.id ? model : m)));
      // Installing a model changes what a run would do.
      void client.invalidateQueries({ queryKey: ["plan"] });
      return;
    }
    case "asset.deleted":
      refreshLibrary(client);
      client.setQueryData<Asset[]>(keys.assets, (list) => removeById(list, String(event.data.id)));
      void client.invalidateQueries({ predicate: (q) => q.queryKey[2] === "children" });
      return;
    case "rendition.updated": {
      const rendition = event.data as unknown as Rendition & { truncated?: boolean };
      if (rendition.truncated || !rendition.asset_id) {
        void client.invalidateQueries({ predicate: (q) => q.queryKey[2] === "renditions" });
        return;
      }
      client.setQueryData<Rendition[]>(keys.renditions(rendition.asset_id), (list) =>
        list ? upsertById(list, rendition, true) : list,
      );
      return;
    }
    case "rendition.deleted":
      client.setQueryData<Rendition[]>(keys.renditions(String(event.data.asset_id)), (list) =>
        removeById(list, String(event.data.id)),
      );
      return;
    case "flow.updated":
      void client.invalidateQueries({ queryKey: keys.flows });
      return;
    case "flow.run": {
      const run = event.data as unknown as FlowRun;
      client.setQueryData<FlowRun[]>(keys.runs, (list) => (list ? upsertById(list, run, true) : list));
      if (run.flow_id) {
        client.setQueryData<FlowRun[]>(keys.flowRuns(run.flow_id), (list) =>
          list ? upsertById(list, run, true) : list,
        );
      }
      client.setQueryData<FlowRunDetail>(keys.run(run.id), (detail) =>
        detail ? { ...detail, run: { ...detail.run, ...run } } : detail,
      );
      if (run.state !== "queued" && run.state !== "running") {
        // Final counts and per-image results, and the flow's "last run" line.
        void client.invalidateQueries({ queryKey: keys.run(run.id) });
        void client.invalidateQueries({ queryKey: keys.flows });
      }
      return;
    }
    case "forge.project":
      void client.invalidateQueries({ queryKey: keys.forgeProjects });
      return;
    case "forge.dataset": {
      const dataset = event.data as unknown as ForgeDataset & { deleted?: boolean };
      client.setQueryData<ForgeDataset[]>(keys.forgeDatasets, (list) =>
        dataset.deleted ? removeById(list, dataset.id) : list ? upsertById(list, dataset) : list,
      );
      return;
    }
    case "forge.run": {
      const run = event.data as unknown as ForgeRun & { deleted?: boolean };
      if (run.deleted) {
        client.setQueryData<ForgeRun[]>(keys.forgeRuns, (list) => removeById(list, run.id));
        return;
      }
      // Events leave out the settings; merge so cached copies keep them.
      client.setQueryData<ForgeRun[]>(keys.forgeRuns, (list) => (list ? upsertById(list, run, true) : list));
      client.setQueryData<ForgeRunDetail>(keys.forgeRun(run.id), (detail) =>
        detail ? { ...detail, run: { ...detail.run, ...run } } : detail,
      );
      if (run.state !== "queued" && run.state !== "running") {
        void client.invalidateQueries({ queryKey: keys.forgeProjects });
      }
      return;
    }
    case "forge.metrics": {
      const { run_id: runId, points } = event.data as { run_id: string; points: ForgeMetric[] };
      client.setQueryData<ForgeRunDetail>(keys.forgeRun(runId), (detail) =>
        detail ? { ...detail, metrics: mergeMetrics(detail.metrics, points) } : detail,
      );
      return;
    }
    case "events.resync":
      void client.invalidateQueries();
      return;
    default:
      return;
  }
}

/**
 * One WebSocket for the whole app. Reconnects with backoff; while it is down the queries
 * fall back to polling (see useFallbackInterval), so nothing on screen goes stale.
 */
export function connectEvents(client: QueryClient): () => void {
  let socket: WebSocket | null = null;
  let retry = 1000;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  const { set } = useEventsStore.getState();

  const open = () => {
    if (stopped) return;
    set("connecting");
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${window.location.host}/api/events`);
    socket.onopen = () => {
      retry = 1000;
      set("open");
      void client.invalidateQueries();
    };
    socket.onmessage = (message) => {
      try {
        applyEvent(client, JSON.parse(String(message.data)) as ServerEvent);
      } catch {
        // Ignore malformed frames; the next resync repairs state.
      }
    };
    socket.onclose = () => {
      set("closed");
      if (stopped) return;
      timer = setTimeout(open, retry);
      retry = Math.min(retry * 2, 15_000);
    };
  };

  open();
  return () => {
    stopped = true;
    clearTimeout(timer);
    socket?.close();
  };
}
