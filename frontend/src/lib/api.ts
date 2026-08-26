const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
export { API_BASE };

function getStored(key: string): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(key);
}

function getToken(): string | null {
  return getStored("orbit_token");
}

function getApiKey(): string | null {
  try {
    const models = JSON.parse(getStored("orbit_llm_models_v2") || "[]") as { name: string; enabled: boolean; apiKey: string }[];
    const active = models.find((m) => m.enabled);
    if (active?.apiKey) return active.apiKey;
  } catch { /* fall through */ }
  return getStored("orbit_llm_key");
}

function getModel(): string | null {
  try {
    const models = JSON.parse(getStored("orbit_llm_models_v2") || "[]") as { name: string; enabled: boolean }[];
    const active = models.find((m) => m.enabled);
    if (active) return active.name;
  } catch { /* fall through */ }
  return getStored("orbit_llm_active_model") || getStored("orbit_llm_model");
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const apiKey = getApiKey();
  const model = getModel();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  if (model) {
    headers["X-LLM-Model"] = model;
  }

  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }

  return res.json();
}

// API v1 前缀（P2-1: API 版本管理）
const V1 = "/api/v1";

// Auth
export const auth = {
  register: (username: string, password: string) =>
    request<{ access_token: string; token?: string }>(`${V1}/auth/register`, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  login: (username: string, password: string) =>
    request<{ access_token: string; token?: string }>(`${V1}/auth/login`, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
};

// Knowledge Base
export const knowledge = {
  upload: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<{ filename: string; status: string }>(
      `${V1}/knowledge/upload`,
      { method: "POST", body: formData }
    );
  },

  search: (q: string, topK = 5) =>
    request<{ results: { text: string; metadata: Record<string, string>; score: number }[] }>(
      `${V1}/knowledge/search?q=${encodeURIComponent(q)}&top_k=${topK}`
    ),

  /** 按 source 元数据删除该文档的全部 chunk */
  deleteSource: (source: string) =>
    request<{ status: string; source: string; message: string }>(
      `${V1}/knowledge/source?source=${encodeURIComponent(source)}`,
      { method: "DELETE" }
    ),

  ask: (question: string, topK = 5) =>
    request<{ answer: string; sources: { filename: string; chunk: string }[] }>(
      `${V1}/knowledge/ask`,
      { method: "POST", body: JSON.stringify({ question, top_k: topK }) }
    ),

  streamAsk: (
    question: string,
    topK = 5,
    onToken?: (token: string) => void,
    onDone?: (model: string) => void,
    onError?: (error: string) => void,
    abortSignal?: AbortSignal
  ): Promise<void> => {
    const token = getToken();
    const apiKey = getApiKey();
    const model = getModel();
    const params = new URLSearchParams({
      q: question,
      top_k: String(topK),
    });

    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (apiKey) headers["X-API-Key"] = apiKey;
    if (model) headers["X-LLM-Model"] = model;

    const timeoutId = setTimeout(() => {
      onError?.("请求超时，请检查网络或 API Key 是否有效");
    }, 60000);

    return fetch(`${API_BASE}${V1}/knowledge/ask/stream?${params}`, {
      headers,
      signal: abortSignal,
    }).then(async (response) => {
      clearTimeout(timeoutId);
      if (!response.ok) {
        onError?.(`HTTP ${response.status}`);
        return;
      }
      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";
      let modelReceived = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.stage) continue;
              if (data.message) {
                onError?.(data.message);
                continue;
              }
              if (data.text) onToken?.(data.text);
              if (data.model) {
                modelReceived = true;
                onDone?.(data.model);
              }
            } catch {
              // ignore parse errors for partial chunks
            }
          }
        }
      }
      if (!modelReceived) onDone?.("");
    }).catch((err) => {
      if (err.name !== "AbortError") {
        onError?.(err.message);
      }
    });
  },
};

// ── Agent Loop ──

export interface LoopEvent {
  seq: number;
  agent: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at?: string;
}

export interface LoopGroup {
  id: number;
  session_id: string;
  status: string;
  current_agent: string;
  iteration_count: number;
  task_desc: string;
  plan_json?: string;
}

interface LoopCallbacks {
  onEvent?: (ev: LoopEvent) => void;
  onCheckpoint?: (title: string, options: string[]) => void;
  onDone?: () => void;
  onError?: (message: string) => void;
}

export const agents = {
  runLoop: (
    sessionId: string,
    task: string,
    projectDir = "",
    roleModels?: Record<string, string>,
    opts?: { projectName?: string; mode?: "interactive" | "L1" | "L2"; budgetLimit?: number }
  ) => {
    const headers: Record<string, string> = {};
    if (roleModels) {
      for (const [role, m] of Object.entries(roleModels)) {
        if (m) headers[`X-LLM-Model-${role[0].toUpperCase()}${role.slice(1)}`] = m;
      }
    }
    const body: Record<string, unknown> = { session_id: sessionId, task, project_dir: projectDir };
    if (opts?.projectName) body.project_name = opts.projectName;
    if (opts?.mode) body.mode = opts.mode;
    if (opts?.budgetLimit) body.budget_limit = opts.budgetLimit;
    return request<{ loop_id: number; status: string; message: string }>(`${V1}/agents/loop`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  },

  listLoops: () => request<{ loops: LoopGroup[] }>(`${V1}/agents/loops`),

  getProjectState: (projectName: string, projectDir?: string) =>
    request<{
      project_name: string;
      run_count: number;
      token_consumption_total: number;
      last_run_at?: string;
      last_loop_result: Record<string, unknown>;
      open_problems: string[];
      constraints: string[];
      critiques: Record<string, unknown>[];
      summary_text: string;
    }>(`${V1}/agents/state/${encodeURIComponent(projectName)}${projectDir ? `?project_dir=${encodeURIComponent(projectDir)}` : ""}`),

  listSchedules: () => request<{ schedules: Array<{ id: number; project_name: string; task_prompt: string; cron_expr: string; mode: "L1" | "L2"; enabled: boolean; last_run_at?: string; next_run_at?: string; created_at?: string }> }>(`${V1}/agents/schedules`),
  createSchedule: (body: {
    project_name: string;
    task_prompt: string;
    cron_expr: string;
    mode?: "L1" | "L2";
    enabled?: boolean;
  }) => request<{ id: number }>(`${V1}/agents/schedules`, { method: "POST", body: JSON.stringify(body) }),
  updateSchedule: (id: number, body: Partial<{ task_prompt: string; cron_expr: string; mode: "L1" | "L2"; enabled: boolean }>) =>
    request<{ status: string }>(`${V1}/agents/schedules/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSchedule: (id: number) => request<{ status: string }>(`${V1}/agents/schedules/${id}`, { method: "DELETE" }),

  getPauseAll: () => request<{ key: string; value: boolean }>(`${V1}/agents/loop/pause-all`),
  setPauseAll: (paused: boolean) => request<{ key: string; value: boolean }>(`${V1}/agents/loop/pause-all`, { method: "POST", body: JSON.stringify({ paused }) }),

  scanMemory: (root?: string) =>
    request<{
      root: string;
      scanned: number;
      listing: string;
      files: Array<{ path: string; type: string; mtime: string | null }>;
    }>(`${V1}/agents/memory/scan${root ? `?root=${encodeURIComponent(root)}` : ""}`),
  selectMemory: (body: { query: string; root?: string; model?: string; session_id?: string }) =>
    request<{
      root: string;
      scanned: number;
      selected: number;
      selected_files: string[];
      injected_preview: string;
      stats: Record<string, unknown>;
    }>(`${V1}/agents/memory/select`, { method: "POST", body: JSON.stringify(body) }),

  getLoop: (loopId: number) =>
    request<{ loop: LoopGroup; events: LoopEvent[] }>(`${V1}/agents/loop/${loopId}`),

  decision: (loopId: number, decision: string, note = "") =>
    request<{ status: string; decision: string }>(`${V1}/agents/loop/${loopId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    }),

  streamLoop: (loopId: number, cb: LoopCallbacks, abortSignal?: AbortSignal): Promise<void> => {
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    return fetch(`${API_BASE}${V1}/agents/loop/${loopId}/events`, {
      headers,
      signal: abortSignal,
    }).then(async (response) => {
      if (!response.ok) {
        cb.onError?.(`HTTP ${response.status}`);
        return;
      }
      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          const lines = frame.split("\n");
          currentEvent = "";
          let dataLine = "";
          for (const line of lines) {
            if (line.startsWith("event: ")) currentEvent = line.slice(7).trim();
            else if (line.startsWith("data: ")) dataLine = line.slice(6);
          }
          if (!dataLine) continue;
          let data: LoopEvent;
          try {
            data = JSON.parse(dataLine) as LoopEvent;
          } catch {
            continue;
          }
          data.event_type = currentEvent;
          if (!data.payload) data.payload = {};
          cb.onEvent?.(data);
          if (currentEvent === "checkpoint") {
            const title = (data.payload.title as string) || "等待你的决策";
            const options = (data.payload.options as string[]) || ["continue"];
            cb.onCheckpoint?.(title, options);
          }
          if (currentEvent === "done") {
            cb.onDone?.();
          } else if (currentEvent === "error") {
            const msg = (data.payload.message as string) || "Agent Loop 执行失败";
            cb.onError?.(msg);
          }
        }
      }
    }).catch((err) => {
      if (err.name !== "AbortError") cb.onError?.(err.message);
    });
  },
};

// P2-3: Token 用量面板 API
export const usage = {
  get: () =>
    request<{
      date: string;
      prompt_tokens: number;
      completion_tokens: number;
      total_tokens: number;
      estimated_cost_usd: number;
      by_model: Array<{ model: string; tokens: number; calls: number; cost_estimate: number }>;
      limit_warning: boolean;
      limit_percent: number;
    }>(`${V1}/knowledge/usage`),
};

// Strategy
export const strategy = {
  get: () =>
    request<{
      version: string;
      chunk: { size: number; overlap: number; method: string };
      embed: { model: string; backend: string };
      retrieval: { top_k: number; method: string; rerank_enabled: boolean };
    }>(`${V1}/knowledge/strategy`),
  patch: (data: Record<string, unknown>) =>
    request<{ status: string; version: string; changes: unknown[] }>(
      `${V1}/knowledge/strategy`,
      { method: "PATCH", body: JSON.stringify(data) }
    ),
};

// Health & Monitoring
export const system = {
  health: () =>
    request<{ status: string; chromadb: string; sqlite: string; llm_api: string }>(
      "/health"
    ),
  cacheStats: () =>
    request<{
      total_entries: number;
      active_entries: number;
      max_size: number;
      hit_count: number;
      miss_count: number;
      hit_rate: number;
      index_enabled: boolean;
      index_ntotal: number;
      history: Array<{ ts: number; hit: boolean }>;
    }>(`${V1}/knowledge/cache/stats`),
  cacheClear: () =>
    request<{ status: string; message: string }>(`${V1}/knowledge/cache`, {
      method: "DELETE",
    }),
};
