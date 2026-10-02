import type { Job } from "./client";

export const keys = {
  system: ["system"] as const,
  jobs: ["jobs"] as const,
  job: (id: string) => ["jobs", id] as const,
  updates: ["updates"] as const,
  catalog: ["catalog"] as const,
  assets: ["assets"] as const,
  asset: (id: string) => ["assets", id] as const,
  edits: (id: string) => ["assets", id, "edits"] as const,
  renditions: (assetId: string) => ["assets", assetId, "renditions"] as const,
  children: (assetId: string) => ["assets", assetId, "children"] as const,
  models: ["models"] as const,
  plan: (assetId: string, modelId: string, device: string) => ["plan", assetId, modelId, device] as const,
};

/** Insert or replace a job in a newest-first list. */
export function upsertJob(list: Job[] | undefined, job: Job): Job[] {
  const current = list ?? [];
  const index = current.findIndex((j) => j.id === job.id);
  if (index === -1) return [job, ...current];
  const next = current.slice();
  next[index] = job;
  return next;
}

/** Insert or replace any record with an id, newest first; returns the same array if nothing changed. */
export function upsertById<T extends { id: string }>(list: T[] | undefined, item: T, merge = false): T[] {
  const current = list ?? [];
  const index = current.findIndex((x) => x.id === item.id);
  if (index === -1) return [item, ...current];
  const next = current.slice();
  next[index] = merge ? { ...current[index], ...item } : item;
  return next;
}

export function removeById<T extends { id: string }>(list: T[] | undefined, id: string): T[] | undefined {
  return list?.filter((x) => x.id !== id);
}
