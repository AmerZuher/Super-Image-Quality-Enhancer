import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type Degradation,
  type ForgeDataset,
  type ForgeDatasetRequest,
  type ForgeGraph,
  type ForgeProject,
  type ForgeRun,
  type ForgeRunDetail,
  type Job,
  type TrainSettings,
  unwrap,
  unwrapEmpty,
} from "@/lib/api/client";
import { keys, removeById, upsertById, upsertJob } from "@/lib/api/keys";
import { useEventsStore } from "@/lib/events";

function useFallback(ms: number): number | false {
  return useEventsStore((s) => s.status === "open") ? false : ms;
}

export function useForgeCatalog() {
  return useQuery({
    queryKey: keys.forgeCatalog,
    queryFn: async () => unwrap(await api.GET("/api/forge/catalog")),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useForgeTemplates() {
  return useQuery({
    queryKey: keys.forgeTemplates,
    queryFn: async () => unwrap(await api.GET("/api/forge/templates")),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useProjects() {
  const refetchInterval = useFallback(15_000);
  return useQuery({
    queryKey: keys.forgeProjects,
    queryFn: async () => unwrap(await api.GET("/api/forge/projects")),
    refetchInterval,
  });
}

/** Shapes, problems and costs of a graph as drawn, before it is saved. */
export function useCheck(graph: ForgeGraph | null) {
  const key = graph ? JSON.stringify(graph) : "";
  return useQuery({
    queryKey: keys.forgeCheck(key),
    enabled: graph !== null,
    queryFn: async () => unwrap(await api.POST("/api/forge/check", { body: { graph: graph as ForgeGraph } })),
    placeholderData: keepPreviousData,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 30_000,
  });
}

export function useCreateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; template?: string | null; description?: string }) =>
      unwrap(await api.POST("/api/forge/projects", { body: { description: "", ...body } })),
    onSuccess: (project) =>
      client.setQueryData<ForgeProject[]>(keys.forgeProjects, (list) => upsertById(list, project)),
  });
}

export function useUpdateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: {
      id: string;
      name?: string;
      description?: string;
      graph?: ForgeGraph;
    }) =>
      unwrap(
        await api.PUT("/api/forge/projects/{project_id}", { params: { path: { project_id: id } }, body }),
      ),
    onSuccess: (project) => {
      client.setQueryData<ForgeProject[]>(keys.forgeProjects, (list) =>
        list?.map((p) => (p.id === project.id ? project : p)),
      );
      void client.invalidateQueries({ queryKey: keys.forgeCode(project.id) });
    },
  });
}

export function useDuplicateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/forge/projects/{project_id}/duplicate", {
          params: { path: { project_id: id } },
        }),
      ),
    onSuccess: (project) =>
      client.setQueryData<ForgeProject[]>(keys.forgeProjects, (list) => upsertById(list, project)),
  });
}

export function useDeleteProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrapEmpty(
        await api.DELETE("/api/forge/projects/{project_id}", { params: { path: { project_id: id } } }),
      ),
    onSuccess: (_, id) =>
      client.setQueryData<ForgeProject[]>(keys.forgeProjects, (list) => removeById(list, id)),
  });
}

export function useProjectCode(projectId: string | undefined, version: string) {
  return useQuery({
    queryKey: [...keys.forgeCode(projectId ?? "none"), version],
    enabled: Boolean(projectId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/forge/projects/{project_id}/code", {
          params: { path: { project_id: projectId as string } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

// ---------------------------------------------------------------------------- datasets

export function useDatasets() {
  const refetchInterval = useFallback(5_000);
  return useQuery({
    queryKey: keys.forgeDatasets,
    queryFn: async () => unwrap(await api.GET("/api/forge/datasets")),
    refetchInterval,
  });
}

function storeDataset(client: ReturnType<typeof useQueryClient>, dataset: ForgeDataset) {
  client.setQueryData<ForgeDataset[]>(keys.forgeDatasets, (list) => upsertById(list, dataset));
}

export function useCreateDataset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: ForgeDatasetRequest) => unwrap(await api.POST("/api/forge/datasets", { body })),
    onSuccess: (dataset) => storeDataset(client, dataset),
  });
}

export function useSetDegradation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, degradation }: { id: string; degradation: Degradation }) =>
      unwrap(
        await api.PUT("/api/forge/datasets/{dataset_id}/degradation", {
          params: { path: { dataset_id: id } },
          body: { degradation },
        }),
      ),
    onSuccess: (dataset) => storeDataset(client, dataset),
  });
}

export function useRebuildDataset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/forge/datasets/{dataset_id}/rebuild", { params: { path: { dataset_id: id } } }),
      ),
    onSuccess: (dataset) => storeDataset(client, dataset),
  });
}

export function useDeleteDataset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrapEmpty(
        await api.DELETE("/api/forge/datasets/{dataset_id}", { params: { path: { dataset_id: id } } }),
      ),
    onSuccess: (_, id) =>
      client.setQueryData<ForgeDataset[]>(keys.forgeDatasets, (list) => removeById(list, id)),
  });
}

/** Damaged inputs beside their clean crops, as an object URL; follows degradation changes. */
export function useDatasetPreview(dataset: ForgeDataset | undefined, scale: number, seed: number) {
  const version = dataset ? JSON.stringify(dataset.degradation) + dataset.updated_at : "";
  const query = useQuery({
    queryKey: keys.forgePreview(dataset?.id ?? "none", scale, seed, version),
    enabled: dataset?.state === "succeeded",
    queryFn: async () => {
      const result = await api.GET("/api/forge/datasets/{dataset_id}/preview", {
        params: { path: { dataset_id: (dataset as ForgeDataset).id }, query: { scale, seed } },
        parseAs: "blob",
      });
      return URL.createObjectURL(unwrap(result) as Blob);
    },
    placeholderData: keepPreviousData,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 60_000,
  });
  return query;
}

// -------------------------------------------------------------------------------- runs

export function useForgeRuns() {
  const refetchInterval = useFallback(5_000);
  return useQuery({
    queryKey: keys.forgeRuns,
    queryFn: async () => unwrap(await api.GET("/api/forge/runs", { params: { query: { limit: 200 } } })),
    refetchInterval,
  });
}

export function useForgeRun(runId: string | undefined) {
  const live = useEventsStore((s) => s.status === "open");
  return useQuery({
    queryKey: keys.forgeRun(runId ?? "none"),
    enabled: Boolean(runId),
    queryFn: async () =>
      unwrap(await api.GET("/api/forge/runs/{run_id}", { params: { path: { run_id: runId as string } } })),
    // Metrics stream over the event socket; poll only while it is down.
    refetchInterval: (query) => {
      const state = query.state.data?.run.state;
      if (!live && (state === "queued" || state === "running")) return 3_000;
      return false;
    },
  });
}

function storeRun(client: ReturnType<typeof useQueryClient>, run: ForgeRun) {
  client.setQueryData<ForgeRun[]>(keys.forgeRuns, (list) => upsertById(list, run));
  client.setQueryData<ForgeRunDetail>(keys.forgeRun(run.id), (detail) =>
    detail ? { ...detail, run } : detail,
  );
}

export function useStartTraining() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      projectId,
      datasetId,
      settings,
    }: {
      projectId: string;
      datasetId: string;
      settings: TrainSettings;
    }) =>
      unwrap(
        await api.POST("/api/forge/projects/{project_id}/runs", {
          params: { path: { project_id: projectId } },
          body: { dataset_id: datasetId, settings },
        }),
      ),
    onSuccess: (run) => {
      storeRun(client, run);
      void client.invalidateQueries({ queryKey: keys.forgeProjects });
    },
  });
}

export function useRunControl() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, action }: { id: string; action: "pause" | "resume" | "stop" }) => {
      const params = { params: { path: { run_id: id } } };
      if (action === "pause") return unwrap(await api.POST("/api/forge/runs/{run_id}/pause", params));
      if (action === "resume") return unwrap(await api.POST("/api/forge/runs/{run_id}/resume", params));
      return unwrap(await api.POST("/api/forge/runs/{run_id}/stop", params));
    },
    onSuccess: (run) => storeRun(client, run),
  });
}

export function useDeleteRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrapEmpty(await api.DELETE("/api/forge/runs/{run_id}", { params: { path: { run_id: id } } })),
    onSuccess: (_, id) => client.setQueryData<ForgeRun[]>(keys.forgeRuns, (list) => removeById(list, id)),
  });
}

export function usePublish() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, name, summary }: { id: string; name: string; summary: string }) =>
      unwrap(
        await api.POST("/api/forge/runs/{run_id}/publish", {
          params: { path: { run_id: id } },
          body: { name, summary },
        }),
      ).job,
    onSuccess: (job: Job) => {
      client.setQueryData<Job[]>(keys.jobs, (list) => upsertJob(list, job));
      client.setQueryData(keys.job(job.id), job);
    },
  });
}

/** Download the best checkpoint's weights through the API client (works with sign-in on). */
export async function downloadWeights(run: ForgeRun): Promise<void> {
  const result = await api.GET("/api/forge/runs/{run_id}/weights", {
    params: { path: { run_id: run.id } },
    parseAs: "blob",
  });
  const blob = unwrap(result) as Blob;
  const disposition = result.response.headers.get("content-disposition") ?? "";
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? "weights.safetensors";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
