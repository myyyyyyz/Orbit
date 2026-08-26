import type {
  ActiveIndexVersion,
  EvaluationReport,
  FolderPlan,
  ImportBatch,
  KnowledgeRun,
  KnowledgeRunPage,
} from "@/components/knowledge-workbench/workbench-types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export interface PlanFolderInput {
  path: string;
  use_agent: boolean;
}

export class KnowledgeApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.name = "KnowledgeApiError";
  }
}

export interface KnowledgeApi {
  listRuns(limit?: number, cursor?: string): Promise<KnowledgeRunPage>;
  getRun(runId: string): Promise<KnowledgeRun>;
  getPlan(runId: string): Promise<FolderPlan>;
  createImport(): Promise<ImportBatch>;
  uploadImportFile(importId: string, file: File, relativePath: string): Promise<ImportBatch>;
  completeImport(importId: string): Promise<ImportBatch>;
  getImport(importId: string): Promise<ImportBatch>;
  deleteImport(importId: string): Promise<void>;
  planFolder(input: PlanFolderInput): Promise<FolderPlan>;
  approve(runId: string): Promise<KnowledgeRun>;
  execute(runId: string): Promise<KnowledgeRun>;
  evaluate(runId: string): Promise<EvaluationReport>;
  getEvaluation(runId: string): Promise<EvaluationReport>;
  getActiveVersion(): Promise<ActiveIndexVersion>;
  promote(runId: string): Promise<ActiveIndexVersion>;
  rollback(runId: string): Promise<ActiveIndexVersion>;
}

function storedToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("orbit_token");
}

export function createKnowledgeApi(fetcher: Fetcher = fetch): KnowledgeApi {
  async function request<T>(endpoint: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      ...(init.headers as Record<string, string> | undefined),
    };
    const token = storedToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (init.body !== undefined && !(init.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    const response = await fetcher(`${API_BASE}${endpoint}`, { ...init, headers });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = payload && typeof payload === "object" && "detail" in payload
        ? payload.detail
        : response.statusText;
      throw new KnowledgeApiError(response.status, detail);
    }
    return payload as T;
  }

  const runPath = (runId: string, suffix = "") =>
    `/api/v1/knowledge/runs/${encodeURIComponent(runId)}${suffix}`;
  const action = <T>(runId: string, suffix: string) =>
    request<T>(runPath(runId, suffix), { method: "POST" });

  return {
    listRuns(limit = 20, cursor) {
      const params = new URLSearchParams({ limit: String(limit) });
      if (cursor) params.set("cursor", cursor);
      return request<KnowledgeRunPage>(`/api/v1/knowledge/runs?${params}`);
    },
    getRun: (runId) => request<KnowledgeRun>(runPath(runId)),
    getPlan: (runId) => request<FolderPlan>(runPath(runId, "/plan")),
    createImport: () => request<ImportBatch>("/api/v1/knowledge/imports", { method: "POST" }),
    uploadImportFile(importId, file, relativePath) {
      const form = new FormData();
      form.set("relative_path", relativePath);
      form.set("file", file);
      return request<ImportBatch>(`/api/v1/knowledge/imports/${encodeURIComponent(importId)}/files`, {
        method: "POST",
        body: form,
      });
    },
    completeImport: (importId) => request<ImportBatch>(`/api/v1/knowledge/imports/${encodeURIComponent(importId)}/complete`, { method: "POST" }),
    getImport: (importId) => request<ImportBatch>(`/api/v1/knowledge/imports/${encodeURIComponent(importId)}`),
    deleteImport: (importId) => request<void>(`/api/v1/knowledge/imports/${encodeURIComponent(importId)}`, { method: "DELETE" }),
    planFolder: (input) =>
      request<FolderPlan>("/api/v1/knowledge/plan-folder", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    approve: (runId) => action<KnowledgeRun>(runId, "/approve"),
    execute: (runId) => action<KnowledgeRun>(runId, "/execute"),
    evaluate: (runId) => action<EvaluationReport>(runId, "/evaluate"),
    getEvaluation: (runId) =>
      request<EvaluationReport>(runPath(runId, "/evaluation")),
    getActiveVersion: () =>
      request<ActiveIndexVersion>("/api/v1/knowledge/active-version"),
    promote: (runId) => action<ActiveIndexVersion>(runId, "/promote"),
    rollback: (runId) => action<ActiveIndexVersion>(runId, "/rollback"),
  };
}

export const knowledgeApi = createKnowledgeApi();
