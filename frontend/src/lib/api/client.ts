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
export type Model = components["schemas"]["ModelOut"];
export type ModelImport = components["schemas"]["ModelImportOut"];
export type ModelTask = Model["task"];
export type AiPlan = components["schemas"]["AiPlanOut"];
export type AiRunRequest = components["schemas"]["AiRunIn"];
export type LibraryPage = components["schemas"]["LibraryPageOut"];
export type LibraryStatus = components["schemas"]["LibraryStatusOut"];
export type Album = components["schemas"]["AlbumOut"];
export type RuleSet = components["schemas"]["RuleSet"];
export type Rule = components["schemas"]["Rule"];
export type ImportStatus = components["schemas"]["ImportStatusOut"];
export type AuthStatus = components["schemas"]["AuthStatusOut"];
export type ApiKey = components["schemas"]["ApiKeyOut"];
export type ApiKeyCreated = components["schemas"]["ApiKeyCreatedOut"];
export type FlowNodeType = components["schemas"]["FlowNodeTypeOut"];
export type FlowParam = FlowNodeType["params"][number];
export type FlowDocument = components["schemas"]["FlowDocumentIO"];
export type FlowNode = components["schemas"]["FlowNodeIO"];
export type FlowEdge = components["schemas"]["FlowEdgeIO"];
export type Flow = components["schemas"]["FlowOut"];
export type FlowProblem = Flow["problems"][number];
export type Recipe = components["schemas"]["RecipeOut"];
export type FlowRun = components["schemas"]["FlowRunOut"];
export type FlowRunItem = components["schemas"]["FlowRunItemOut"];
export type FlowRunDetail = components["schemas"]["FlowRunDetailOut"];
export type FlowRunRequest = components["schemas"]["FlowRunIn"];
export type ForgeBlockType = components["schemas"]["ForgeBlockTypeOut"];
export type ForgeParam = ForgeBlockType["params"][number];
export type ForgeTemplate = components["schemas"]["ForgeTemplateOut"];
export type ForgeGraph = components["schemas"]["ForgeGraph"];
export type ForgeBlock = components["schemas"]["ForgeBlock"];
export type ForgeLink = components["schemas"]["ForgeLink"];
export type ForgeAnalysis = components["schemas"]["ForgeAnalysis"];
export type ForgeProblem = components["schemas"]["ForgeProblem"];
export type ForgeFix = components["schemas"]["ForgeFix"];
export type ForgeShape = components["schemas"]["ForgeShape"];
export type ForgeStats = components["schemas"]["ForgeStats"];
export type ForgeProject = components["schemas"]["ForgeProjectOut"];
export type ForgeDataset = components["schemas"]["ForgeDatasetOut"];
export type ForgeDatasetRequest = components["schemas"]["ForgeDatasetIn"];
export type ForgeImageSource = components["schemas"]["ForgeImageSourceIn"];
export type Degradation = components["schemas"]["Degradation"];
export type DatasetSettings = components["schemas"]["DatasetSettings"];
export type TrainSettings = components["schemas"]["TrainSettings"];
export type ForgeRun = components["schemas"]["ForgeRunOut"];
export type ForgeMetric = components["schemas"]["ForgeMetricOut"];
export type ForgeRunDetail = components["schemas"]["ForgeRunDetailOut"];

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
