import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type Asset,
  api,
  type EditDocument,
  type ExportRequest,
  type Job,
  type Rendition,
  unwrap,
  unwrapEmpty,
} from "@/lib/api/client";
import { keys, removeById, upsertById, upsertJob } from "@/lib/api/keys";
import { useEventsStore } from "@/lib/events";

function useFallback(ms: number): number | false {
  return useEventsStore((s) => s.status === "open") ? false : ms;
}

export function useCatalog() {
  return useQuery({
    queryKey: keys.catalog,
    queryFn: async () => unwrap(await api.GET("/api/ops")),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useAssets() {
  const refetchInterval = useFallback(4_000);
  return useQuery({
    queryKey: keys.assets,
    queryFn: async () => unwrap(await api.GET("/api/assets", { params: { query: { limit: 500 } } })),
    refetchInterval,
  });
}

export function useEdits(assetId: string | undefined) {
  return useQuery({
    queryKey: keys.edits(assetId ?? ""),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/assets/{asset_id}/edits", { params: { path: { asset_id: assetId ?? "" } } }),
      ),
    enabled: Boolean(assetId),
    // The editor owns this document once loaded; never overwrite it underneath the user.
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
  });
}

export async function saveEdits(assetId: string, doc: EditDocument): Promise<EditDocument> {
  return unwrap(
    await api.PUT("/api/assets/{asset_id}/edits", { params: { path: { asset_id: assetId } }, body: doc }),
  );
}

export function useRenditions(assetId: string | undefined) {
  const refetchInterval = useFallback(3_000);
  return useQuery({
    queryKey: keys.renditions(assetId ?? ""),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/assets/{asset_id}/renditions", { params: { path: { asset_id: assetId ?? "" } } }),
      ),
    enabled: Boolean(assetId),
    refetchInterval,
  });
}

export function useJob(id: string | null | undefined) {
  const refetchInterval = useFallback(2_000);
  const client = useQueryClient();
  return useQuery({
    queryKey: keys.job(id ?? ""),
    queryFn: async () =>
      unwrap(await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id ?? "" } } })),
    enabled: Boolean(id),
    initialData: () => client.getQueryData<Job[]>(keys.jobs)?.find((j) => j.id === id),
    refetchInterval,
  });
}

export function useStartExport(assetId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: ExportRequest) =>
      unwrap(
        await api.POST("/api/assets/{asset_id}/exports", { params: { path: { asset_id: assetId } }, body }),
      ),
    onSuccess: ({ job, rendition }) => {
      client.setQueryData<Job[]>(keys.jobs, (list) => upsertJob(list, job));
      client.setQueryData(keys.job(job.id), job);
      client.setQueryData<Rendition[]>(keys.renditions(assetId), (list) => upsertById(list, rendition));
    },
  });
}

export function useDeleteRendition(assetId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrapEmpty(
        await api.DELETE("/api/renditions/{rendition_id}", { params: { path: { rendition_id: id } } }),
      ),
    onSuccess: (_, id) =>
      client.setQueryData<Rendition[]>(keys.renditions(assetId), (list) => removeById(list, id)),
  });
}

export function useDeleteAsset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrapEmpty(await api.DELETE("/api/assets/{asset_id}", { params: { path: { asset_id: id } } })),
    onSuccess: (_, id) => client.setQueryData<Asset[]>(keys.assets, (list) => removeById(list, id)),
  });
}
