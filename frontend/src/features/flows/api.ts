import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type Flow,
  type FlowDocument,
  type FlowRun,
  type FlowRunRequest,
  unwrap,
  unwrapEmpty,
} from "@/lib/api/client";
import { keys, removeById, upsertById } from "@/lib/api/keys";
import { useEventsStore } from "@/lib/events";

function useFallback(ms: number): number | false {
  return useEventsStore((s) => s.status === "open") ? false : ms;
}

export function useFlowCatalog() {
  return useQuery({
    queryKey: keys.flowCatalog,
    queryFn: async () => unwrap(await api.GET("/api/flows/catalog")),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useRecipes() {
  return useQuery({
    queryKey: keys.recipes,
    queryFn: async () => unwrap(await api.GET("/api/flows/recipes")),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useFlows() {
  const refetchInterval = useFallback(10_000);
  return useQuery({
    queryKey: keys.flows,
    queryFn: async () => unwrap(await api.GET("/api/flows")),
    refetchInterval,
  });
}

export function useCreateFlow() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; recipe?: string; document?: FlowDocument }) =>
      unwrap(await api.POST("/api/flows", { body: { description: "", ...body } })),
    onSuccess: (flow) => client.setQueryData<Flow[]>(keys.flows, (list) => upsertById(list, flow)),
  });
}

export function useImportFlow() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (file: { name: string; description?: string; document: FlowDocument }) =>
      unwrap(
        await api.POST("/api/flows/import", {
          body: { format: "siqe-flow", version: 1, description: "", ...file },
        }),
      ),
    onSuccess: (flow) => client.setQueryData<Flow[]>(keys.flows, (list) => upsertById(list, flow)),
  });
}

export function useUpdateFlow() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: {
      id: string;
      name?: string;
      description?: string;
      document?: FlowDocument;
      watch_folder?: string;
      watch_enabled?: boolean;
    }) => unwrap(await api.PUT("/api/flows/{flow_id}", { params: { path: { flow_id: id } }, body })),
    onSuccess: (flow) =>
      client.setQueryData<Flow[]>(keys.flows, (list) => list?.map((f) => (f.id === flow.id ? flow : f))),
  });
}

export function useDuplicateFlow() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/flows/{flow_id}/duplicate", { params: { path: { flow_id: id } } })),
    onSuccess: (flow) => client.setQueryData<Flow[]>(keys.flows, (list) => upsertById(list, flow)),
  });
}

export function useDeleteFlow() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrapEmpty(await api.DELETE("/api/flows/{flow_id}", { params: { path: { flow_id: id } } })),
    onSuccess: (_, id) => client.setQueryData<Flow[]>(keys.flows, (list) => removeById(list, id)),
  });
}

export async function flowFile(id: string) {
  return unwrap(await api.GET("/api/flows/{flow_id}/file", { params: { path: { flow_id: id } } }));
}

export function useRunFlow() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: FlowRunRequest & { id: string }) =>
      unwrap(await api.POST("/api/flows/{flow_id}/runs", { params: { path: { flow_id: id } }, body })),
    onSuccess: (run) => {
      client.setQueryData<FlowRun[]>(keys.runs, (list) => upsertById(list, run));
      void client.invalidateQueries({ queryKey: keys.runs });
      void client.invalidateQueries({ queryKey: keys.flows });
    },
  });
}

export function useRuns(flowId?: string) {
  const refetchInterval = useFallback(5_000);
  return useQuery({
    queryKey: flowId ? keys.flowRuns(flowId) : keys.runs,
    queryFn: async () =>
      unwrap(await api.GET("/api/flows/runs/recent", { params: { query: { flow_id: flowId, limit: 30 } } })),
    refetchInterval,
  });
}

export function useRun(runId: string | undefined) {
  const live = useEventsStore((s) => s.status === "open");
  return useQuery({
    queryKey: keys.run(runId ?? "none"),
    enabled: Boolean(runId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/flows/runs/{run_id}", {
          params: { path: { run_id: runId as string }, query: { limit: 500 } },
        }),
      ),
    // Item results don't come over the event stream, so poll while the run is going.
    refetchInterval: (query) => {
      const state = query.state.data?.run.state;
      if (state === "queued" || state === "running") return live ? 2_000 : 3_000;
      return false;
    },
  });
}
