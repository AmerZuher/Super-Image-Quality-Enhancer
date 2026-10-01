import { describe, expect, it } from "vitest";
import type { Job } from "./client";
import { upsertJob } from "./keys";

const job = (id: string, progress: number): Job => ({
  id,
  kind: "system.self_test",
  title: "System self-test",
  state: "running",
  progress,
  message: "",
  params: {},
  result: null,
  error: null,
  created_at: null,
  started_at: null,
  finished_at: null,
});

describe("upsertJob", () => {
  it("prepends new jobs", () => {
    expect(upsertJob([job("a", 0)], job("b", 0)).map((j) => j.id)).toEqual(["b", "a"]);
  });

  it("replaces an existing job in place", () => {
    const list = upsertJob([job("b", 0), job("a", 0)], job("a", 0.5));
    expect(list.map((j) => [j.id, j.progress])).toEqual([
      ["b", 0],
      ["a", 0.5],
    ]);
  });

  it("handles an empty cache", () => {
    expect(upsertJob(undefined, job("a", 0))).toHaveLength(1);
  });
});
