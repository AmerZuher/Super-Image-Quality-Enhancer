import type { Job } from "./client";

export const keys = {
  system: ["system"] as const,
  jobs: ["jobs"] as const,
  job: (id: string) => ["jobs", id] as const,
  updates: ["updates"] as const,
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
