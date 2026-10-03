/**
 * Upload queue. Files go up as the raw request body, two at a time.
 *
 * This is the one place the app calls the API without openapi-fetch: fetch() can't report
 * upload progress, so it uses XMLHttpRequest (for images here, and for ONNX models added in AI
 * Lab via ``uploadModel``). The URLs and response types still come from the generated schema,
 * so a change to an endpoint fails type-checking here.
 */
import type { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import type { Asset, Job, ModelImport, Problem, Upload } from "@/lib/api/client";
import { keys, upsertById, upsertJob } from "@/lib/api/keys";
import type { paths } from "@/lib/api/schema";

const UPLOAD_PATH = "/api/assets" satisfies keyof paths;
const MODEL_PATH = "/api/models/onnx" satisfies keyof paths;
type ModelQuery = NonNullable<paths[typeof MODEL_PATH]["post"]["parameters"]["query"]>;
const CONCURRENCY = 2;

export type UploadState = "waiting" | "uploading" | "done" | "failed";

export interface UploadItem {
  key: string;
  name: string;
  size: number;
  loaded: number;
  state: UploadState;
  assetId?: string;
  duplicate?: boolean;
  error?: { message: string; fix?: string };
}

interface UploadsStore {
  items: UploadItem[];
  patch: (key: string, patch: Partial<UploadItem>) => void;
  add: (items: UploadItem[]) => void;
  dismiss: (key: string) => void;
  clearFinished: () => void;
}

export const useUploads = create<UploadsStore>((set) => ({
  items: [],
  patch: (key, patch) =>
    set((s) => ({ items: s.items.map((item) => (item.key === key ? { ...item, ...patch } : item)) })),
  add: (items) => set((s) => ({ items: [...s.items, ...items] })),
  dismiss: (key) => set((s) => ({ items: s.items.filter((item) => item.key !== key) })),
  clearFinished: () => set((s) => ({ items: s.items.filter((item) => item.state !== "done") })),
}));

const files = new Map<string, File>();
let active = 0;
let counter = 0;

function problemFrom(xhr: XMLHttpRequest): { message: string; fix?: string } {
  try {
    const body = JSON.parse(xhr.responseText) as Problem;
    return { message: body.detail ?? body.title ?? `The server answered ${xhr.status}.`, fix: body.fix };
  } catch {
    return { message: `The server answered ${xhr.status}.` };
  }
}

type Sent<T> = { ok: true; body: T } | { ok: false; error: { message: string; fix?: string } };

function send<T>(url: string, file: File, onProgress: (loaded: number) => void): Promise<Sent<T>> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (event) => onProgress(event.loaded);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve({ ok: true, body: JSON.parse(xhr.responseText) as T });
      } else {
        resolve({ ok: false, error: problemFrom(xhr) });
      }
    };
    xhr.onerror = () =>
      resolve({
        ok: false,
        error: {
          message: "The upload was interrupted.",
          fix: "Check that SIQE Studio is running, then retry.",
        },
      });
    xhr.send(file);
  });
}

export function uploadFile(file: File, onProgress: (loaded: number) => void): Promise<Sent<Upload>> {
  return send<Upload>(`${UPLOAD_PATH}?filename=${encodeURIComponent(file.name)}`, file, onProgress);
}

/** Add an ONNX model: the server checks it in a job (``body.job``) and adds it when it passes. */
export function uploadModel(
  file: File,
  query: Omit<ModelQuery, "filename">,
  onProgress: (loaded: number) => void,
): Promise<Sent<ModelImport>> {
  const params = new URLSearchParams({ filename: file.name });
  if (query.name) params.set("name", query.name);
  if (query.task) params.set("task", query.task);
  return send<ModelImport>(`${MODEL_PATH}?${params}`, file, onProgress);
}

function pump(client: QueryClient, onUploaded?: (asset: Asset) => void): void {
  const { items, patch } = useUploads.getState();
  while (active < CONCURRENCY) {
    const next = items.find((item) => item.state === "waiting" && files.has(item.key));
    if (!next) return;
    const file = files.get(next.key);
    if (!file) return;
    files.delete(next.key);
    active++;
    patch(next.key, { state: "uploading" });
    void uploadFile(file, (loaded) => patch(next.key, { loaded })).then((result) => {
      active--;
      if (result.ok) {
        const { asset, job, duplicate } = result.body;
        client.setQueryData<Asset[]>(keys.assets, (list) => upsertById(list, asset, true));
        if (job) client.setQueryData<Job[]>(keys.jobs, (list) => upsertJob(list, job));
        patch(next.key, { state: "done", loaded: file.size, assetId: asset.id, duplicate });
        onUploaded?.(asset);
      } else {
        patch(next.key, { state: "failed", error: result.error });
      }
      pump(client, onUploaded);
    });
  }
}

export function startUploads(
  list: Iterable<File>,
  client: QueryClient,
  onUploaded?: (asset: Asset) => void,
): void {
  const added: UploadItem[] = [];
  for (const file of list) {
    const key = `u${++counter}`;
    files.set(key, file);
    added.push({ key, name: file.name, size: file.size, loaded: 0, state: "waiting" });
  }
  if (!added.length) return;
  useUploads.getState().add(added);
  pump(client, onUploaded);
}

/** Keep only files whose extension the server accepts; returns [accepted, rejected names]. */
export function filterAccepted(list: Iterable<File>, extensions: readonly string[]): [File[], string[]] {
  const accepted: File[] = [];
  const rejected: string[] = [];
  const allowed = new Set(extensions.map((e) => e.toLowerCase()));
  for (const file of list) {
    const dot = file.name.lastIndexOf(".");
    const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
    if (allowed.size === 0 || allowed.has(ext)) accepted.push(file);
    else rejected.push(file.name);
  }
  return [accepted, rejected];
}
