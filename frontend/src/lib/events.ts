import type { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import type { Asset, Job, Model, Rendition, SystemStatus, Worker } from "./api/client";
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

export function applyEvent(client: QueryClient, event: ServerEvent): void {
  switch (event.type) {
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
