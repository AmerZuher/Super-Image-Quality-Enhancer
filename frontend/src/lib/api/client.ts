import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Job = components["schemas"]["JobOut"];
export type JobState = Job["state"];
export type SystemStatus = components["schemas"]["SystemOut"];
export type Worker = components["schemas"]["WorkerOut"];
export type UpdateStatus = components["schemas"]["UpdateStatusOut"];
export type Release = components["schemas"]["ReleaseOut"];
export type Asset = components["schemas"]["AssetOut"];
export type Upload = components["schemas"]["UploadOut"];
export type Catalog = components["schemas"]["CatalogOut"];
export type OpSpec = components["schemas"]["OpOut"];
export type OpParam = components["schemas"]["OpParamOut"];
export type OutputFormat = components["schemas"]["OutputFormatOut"];
export type EditDocument = components["schemas"]["EditDocumentIn"];
export type Geometry = components["schemas"]["GeometryIn"];
export type Crop = components["schemas"]["CropIn"];
export type OpEntry = components["schemas"]["OpEntryIn"];
export type ExportRequest = components["schemas"]["ExportIn"];
export type Rendition = components["schemas"]["RenditionOut"];

/** RFC 9457 problem details returned by every failing endpoint. */
export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: string;
  fix?: string;
}

export class ApiError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title ?? "Request failed");
    this.name = "ApiError";
    this.problem = problem;
  }
}

export const api = createClient<paths>({ baseUrl: "" });

/** Unwrap an openapi-fetch result, turning problem+json bodies into ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const body = (result.error ?? {}) as Problem;
    throw new ApiError({
      status: result.response.status,
      title: body.title ?? result.response.statusText,
      detail: body.detail ?? `The server answered ${result.response.status}.`,
      code: body.code ?? `http.${result.response.status}`,
      fix: body.fix,
    });
  }
  return result.data;
}

/** Like unwrap, for endpoints that answer 204 No Content. */
export function unwrapEmpty(result: { error?: unknown; response: Response }): void {
  if (result.response.ok && result.error === undefined) return;
  unwrap({ ...result, data: undefined });
}

export function errorMessage(error: unknown): { message: string; fix?: string } {
  if (error instanceof ApiError) return { message: error.message, fix: error.problem.fix };
  if (error instanceof TypeError) {
    return { message: "Can't reach the SIQE Studio API.", fix: "Check that the api container is running." };
  }
  return { message: error instanceof Error ? error.message : String(error) };
}
