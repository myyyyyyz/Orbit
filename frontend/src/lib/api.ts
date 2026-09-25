const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
export { API_BASE };

// API v1 前缀（P2-1: API 版本管理）
const V1 = "/api/v1";

const TOKEN_KEY = "orbit_token";
const REFRESH_KEY = "orbit_refresh_token";
const REQUEST_TIMEOUT_MS = 30_000;
const MAX_NETWORK_RETRIES = 1;

/** 统一的 API 错误：携带 HTTP 状态码与后端 request_id，便于排障与 UI 分支。 */
export class ApiError extends Error {
  status: number;
  requestId?: string;
  constructor(message: string, status: number, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }
}

function getStored(key: string): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(key);
}

function setStored(key: string, value: string | null) {
  if (typeof window === "undefined") return;
  if (value) localStorage.setItem(key, value);
  else localStorage.removeItem(key);
}

export function getToken(): string | null {
  return getStored(TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return getStored(REFRESH_KEY);
}

/** 保存令牌。后端登录/注册/刷新统一走这里，避免各处漏存 refresh_token。 */
export function setTokens(accessToken?: string | null, refreshToken?: string | null) {
  if (accessToken !== undefined) setStored(TOKEN_KEY, accessToken);
  if (refreshToken !== undefined) setStored(REFRESH_KEY, refreshToken);
}

export function clearTokens() {
  setStored(TOKEN_KEY, null);
  setStored(REFRESH_KEY, null);
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

// ── Access Token 自动续期 ──
// 单个并发请求可能同时收到 401；用一个在途 Promise 合并，避免打出一串刷新请求
// （并发的 refresh 会互相轮换掉对方的 refresh_token，导致其中一些必然失败）。
let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${API_BASE}${V1}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return null;
      const data = await res.json();
      if (!data?.access_token) return null;
      setTokens(data.access_token, data.refresh_token);
      return data.access_token as string;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

/** 从后端错误体里提取人类可读信息（兼容 {error,detail} / {detail} / 校验数组）。 */
function extractErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const body = payload as Record<string, unknown>;
  const detail = body.detail;
  if (typeof detail === "string" && detail) return detail;
  if (typeof body.error === "string" && body.error && body.error !== "请求参数校验失败") {
    return body.error;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string } | undefined;
    if (first?.msg) return `参数错误：${first.msg}`;
    return "参数错误";
  }
  if (typeof body.error === "string" && body.error) return body.error;
  return fallback;
}

function buildHeaders(options: RequestInit, tokenOverride?: string | null): Record<string, string> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  const token = tokenOverride ?? getToken();
  const apiKey = getApiKey();
  const model = getModel();

  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (apiKey) headers["X-API-Key"] = apiKey;
  if (model) headers["X-LLM-Model"] = model;

  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

function isRetriableStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

const NO_RETRY_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  attempt = 0,
  tokenOverride?: string | null,
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const controller = new AbortController();
  const externalSignal = options.signal;
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", onExternalAbort);
  }
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers: buildHeaders(options, tokenOverride),
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", onExternalAbort);
    // 调用方主动取消：原样抛出，让上层忽略（不要显示为错误）
    if (externalSignal?.aborted) throw err;
    const isTimeout = (err as Error)?.name === "AbortError";
    // 写操作不自动重试（可能已生效，重试会造成重复副作用）
    if (attempt < MAX_NETWORK_RETRIES && !NO_RETRY_METHODS.has(method)) {
      return request<T>(endpoint, options, attempt + 1, tokenOverride);
    }
    throw new ApiError(
      isTimeout
        ? `请求超时（${REQUEST_TIMEOUT_MS / 1000}s），请检查后端服务或网络`
        : "网络异常：无法连接后端服务，请确认服务已启动",
      0,
    );
  } finally {
    clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }

  // 401 → 用 refresh_token 续期一次后重放原请求
  if (res.status === 401 && !tokenOverride) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      return request<T>(endpoint, options, attempt, newToken);
    }
    clearTokens();
  }

  if (!res.ok) {
    if (isRetriableStatus(res.status) && attempt < MAX_NETWORK_RETRIES && !NO_RETRY_METHODS.has(method)) {
      return request<T>(endpoint, options, attempt + 1, tokenOverride);
    }
    const payload = await res.json().catch(() => null);
    throw new ApiError(
      extractErrorMessage(payload, `HTTP ${res.status}`),
      res.status,
      res.headers.get("X-Request-ID") || undefined,
    );
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// Auth
export interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  token_type?: string;
  expires_in?: number;
  user_id?: number;
  username?: string;
  role?: string;
  tenant_id?: string;
  collection_name?: string;
}

export const auth = {
  register: (username: string, password: string) =>
    request<TokenResponse>(`${V1}/auth/register`, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  login: (username: string, password: string) =>
    request<TokenResponse>(`${V1}/auth/login`, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  refresh: () => refreshAccessToken(),
  /** 登出：通知后端立即撤销令牌（失败也不阻塞本地清理）。 */
  logout: async () => {
    const refreshToken = getRefreshToken();
    try {
      await request<{ status: string }>(`${V1}/auth/logout`, {
        method: "POST",
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch { /* 令牌可能已过期，本地清理即可 */ }
    clearTokens();
  },
  me: () =>
    request<{ user_id: number; username: string; role: string; tenant_id?: string }>(
      `${V1}/auth/me`
    ),
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
    const params = new URLSearchParams({
      q: question,
      top_k: String(topK),
    });
    const url = `${API_BASE}${V1}/knowledge/ask/stream?${params}`;

    let doneCalled = false;
    const finish = (model: string) => {
      if (doneCalled) return;
      doneCalled = true;
      onDone?.(model);
    };

    return consumeSSE(
      url,
      { signal: abortSignal },
      {
        onError,
        onData: (data) => {
          if (data.stage) return;
          if (data.message) {
            onError?.(String(data.message));
            return;
          }
          if (data.text) onToken?.(String(data.text));
          if (data.model) finish(String(data.model));
        },
        onDone: () => finish(""),
      }
    );
  },
};

/**
 * 通用 SSE 消费器：统一处理 401 续期重试、超时中断、行缓冲与错误映射。
 * 之前 streamAsk / streamLoop 各写了一份，且都没有 401 处理与超时中断。
 */
async function consumeSSE(
  url: string,
  init: { signal?: AbortSignal; headers?: Record<string, string> } = {},
  hooks: {
    onData?: (data: Record<string, unknown>, event?: string) => void;
    onEvent?: (event: string, data: Record<string, unknown>) => void;
    onError?: (message: string) => void;
    onDone?: () => void;
  } = {}
): Promise<void> {
  const controller = new AbortController();
  const externalSignal = init.signal;
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", onExternalAbort);
  }
  // 流式响应整体超时：后端首包迟迟不来时给出明确提示而不是无限转圈
  const timeoutId = setTimeout(() => controller.abort(), 120_000);

  try {
    const doFetch = async (tokenOverride?: string | null) => {
      const headers: Record<string, string> = { ...(init.headers || {}) };
      const token = tokenOverride ?? getToken();
      const apiKey = getApiKey();
      const model = getModel();
      if (token) headers["Authorization"] = `Bearer ${token}`;
      if (apiKey) headers["X-API-Key"] = apiKey;
      if (model) headers["X-LLM-Model"] = model;
      return fetch(url, { headers, signal: controller.signal });
    };

    let response = await doFetch();
    if (response.status === 401) {
      const newToken = await refreshAccessToken();
      if (newToken) response = await doFetch(newToken);
      else clearTokens();
    }

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      hooks.onError?.(extractErrorMessage(payload, `HTTP ${response.status}`));
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      hooks.onError?.("响应流不可用");
      return;
    }

    const decoder = new TextDecoder();
    let buffer = "";
    let sawTerminal = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(line.slice(6)) as Record<string, unknown>;
        } catch {
          continue; // 半包 JSON，忽略
        }
        sawTerminal = true;
        hooks.onData?.(data);
      }
    }
    if (sawTerminal) hooks.onDone?.();
  } catch (err) {
    if (externalSignal?.aborted) return; // 调用方主动取消
    const isTimeout = (err as Error)?.name === "AbortError";
    hooks.onError?.(isTimeout ? "请求超时（120s），请重试" : (err as Error)?.message || "流式请求失败");
  } finally {
    clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}

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
  onCheckpoint?: (title: string, options: string[], payload?: Record<string, unknown>) => void;
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

  // 项目工具权限（三态门控）：自动执行清单 / 需人工同意清单
  getToolPolicy: (projectDir = "") =>
    request<{
      project_dir: string;
      auto_commands: string[];
      approval_commands: string[];
      default_auto_commands: string[];
      is_default: boolean;
    }>(`${V1}/agents/tool-policy${projectDir ? `?project_dir=${encodeURIComponent(projectDir)}` : ""}`),
  setToolPolicy: (body: { project_dir: string; auto_commands: string[]; approval_commands: string[] }) =>
    request<{ status: string; project_dir: string; auto_commands: string[]; approval_commands: string[] }>(
      `${V1}/agents/tool-policy`,
      { method: "PUT", body: JSON.stringify(body) }
    ),

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
    const url = `${API_BASE}${V1}/agents/loop/${loopId}/events`;
    const doFetch = async (tokenOverride?: string | null) => {
      const headers: Record<string, string> = {};
      const token = tokenOverride ?? getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
      return fetch(url, { headers, signal: abortSignal });
    };

    return doFetch().then(async (initial) => {
      let response = initial;
      if (response.status === 401) {
        const newToken = await refreshAccessToken();
        if (newToken) response = await doFetch(newToken);
        else clearTokens();
      }
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
            cb.onCheckpoint?.(title, options, data.payload);
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
  /** 依赖明细（永远 200，body 表达健康度）—— 供运维面板展示 */
  health: () =>
    request<{ status: string; chromadb: string; sqlite: string; llm_api: string }>(
      "/health/detail"
    ),
  /** 就绪探针：关键依赖不可用时后端返回 503，此处会抛 ApiError */
  ready: () =>
    request<{ status: string; chromadb: string; sqlite: string; llm_api: string }>(
      "/ready"
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
