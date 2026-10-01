import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEventsStore } from "../events";
import { api, type Job, unwrap } from "./client";
import { keys, upsertJob } from "./keys";

export { keys, upsertJob };

/** Poll faster while the live event stream is down, so the UI never freezes. */
function useFallbackInterval(liveMs: number | false, fallbackMs: number) {
  const connected = useEventsStore((s) => s.status === "open");
  return connected ? liveMs : fallbackMs;
}

export function useSystem() {
  const refetchInterval = useFallbackInterval(15_000, 5_000);
  return useQuery({
    queryKey: keys.system,
    queryFn: async () => unwrap(await api.GET("/api/system")),
    refetchInterval,
  });
}

export function useJobs(limit = 50) {
  const refetchInterval = useFallbackInterval(false, 3_000);
  return useQuery({
    queryKey: keys.jobs,
    queryFn: async () => unwrap(await api.GET("/api/jobs", { params: { query: { limit } } })),
    refetchInterval,
  });
}

export function useUpdates() {
  return useQuery({
    queryKey: keys.updates,
    queryFn: async () => unwrap(await api.GET("/api/updates")),
    staleTime: 30 * 60_000,
    refetchInterval: 60 * 60_000,
  });
}

export function useRefreshUpdates() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.GET("/api/updates", { params: { query: { refresh: true } } })),
    onSuccess: (data) => client.setQueryData(keys.updates, data),
  });
}

export function useStartSelfTest() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/jobs/self-test")),
    onSuccess: (job) => client.setQueryData<Job[]>(keys.jobs, (list) => upsertJob(list, job)),
  });
}

export function useCancelJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/jobs/{job_id}/cancel", { params: { path: { job_id: id } } })),
    onSuccess: (job) => client.setQueryData<Job[]>(keys.jobs, (list) => upsertJob(list, job)),
  });
}
