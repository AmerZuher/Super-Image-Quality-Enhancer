import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type AiRunRequest,
  type Asset,
  api,
  type Job,
  type Model,
  unwrap,
  unwrapEmpty,
} from "@/lib/api/client";
import { keys, upsertJob } from "@/lib/api/keys";
import { useEventsStore } from "@/lib/events";

function useFallback(ms: number): number | false {
  return useEventsStore((s) => s.status === "open") ? false : ms;
}

export function useModels() {
  const refetchInterval = useFallback(3_000);
  return useQuery({
    queryKey: keys.models,
    queryFn: async () => unwrap(await api.GET("/api/models")),
    refetchInterval,
  });
}

function useTrackJob() {
  const client = useQueryClient();
  return (job: Job | null | undefined) => {
    if (!job) return;
    client.setQueryData<Job[]>(keys.jobs, (list) => upsertJob(list, job));
    client.setQueryData(keys.job(job.id), job);
  };
}

export function useInstallModel() {
  const client = useQueryClient();
  const track = useTrackJob();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/models/{model_id}/install", { params: { path: { model_id: id } } })),
    onSuccess: ({ model, job }) => {
      client.setQueryData<Model[]>(keys.models, (list) => list?.map((m) => (m.id === model.id ? model : m)));
      track(job);
    },
  });
}

export function useRemoveModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrapEmpty(await api.DELETE("/api/models/{model_id}", { params: { path: { model_id: id } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.models }),
  });
}

export function usePlan(request: AiRunRequest | null) {
  return useQuery({
    queryKey: keys.plan(request?.asset_id ?? "", request?.model_id ?? "", request?.device ?? "auto"),
    queryFn: async () => unwrap(await api.POST("/api/ai/plan", { body: request as AiRunRequest })),
    enabled: Boolean(request?.asset_id && request?.model_id),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 15_000,
  });
}

export function useStartRun() {
  const track = useTrackJob();
  return useMutation({
    mutationFn: async (body: AiRunRequest) => unwrap(await api.POST("/api/ai/runs", { body })),
    onSuccess: ({ job }) => track(job),
  });
}

export function useChildren(assetId: string | undefined) {
  const refetchInterval = useFallback(4_000);
  return useQuery({
    queryKey: keys.children(assetId ?? ""),
    queryFn: async () =>
      unwrap(await api.GET("/api/assets", { params: { query: { parent_id: assetId ?? "", limit: 100 } } })),
    enabled: Boolean(assetId),
    refetchInterval,
  });
}

export function useRemoveResult(parentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrapEmpty(await api.DELETE("/api/assets/{asset_id}", { params: { path: { asset_id: id } } })),
    onSuccess: (_, id) => {
      client.setQueryData<Asset[]>(keys.children(parentId), (list) => list?.filter((a) => a.id !== id));
      client.setQueryData<Asset[]>(keys.assets, (list) => list?.filter((a) => a.id !== id));
    },
  });
}
