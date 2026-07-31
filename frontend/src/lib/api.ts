const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

function getStored(key: string): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(key);
}

function getToken(): string | null {
  return getStored("orbit_token");
}

function getApiKey(): string | null {
  // v2: read from enabled model
  try {
    const models = JSON.parse(getStored("orbit_llm_models_v2") || "[]") as { name: string; enabled: boolean; apiKey: string }[];
    const active = models.find((m) => m.enabled);
    if (active?.apiKey) return active.apiKey;
  } catch { /* fall through */ }
  return getStored("orbit_llm_key");
}

function getModel(): string | null {
  // v2 format: read enabled model from orbit_llm_models_v2
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

  // Don't set Content-Type for FormData (browser sets it with boundary)
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

// Auth
export const auth = {
  register: (username: string, password: string) =>
    request<{ token: string }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  login: (username: string, password: string) =>
    request<{ token: string }>("/api/auth/login", {
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
      "/api/knowledge/upload",
      { method: "POST", body: formData }
    );
  },

  search: (q: string, topK = 5) =>
    request<{ results: { content: string; metadata: Record<string, string>; similarity: number }[] }>(
      `/api/knowledge/search?q=${encodeURIComponent(q)}&top_k=${topK}`
    ),

  ask: (question: string, topK = 5) =>
    request<{ answer: string; sources: { filename: string; chunk: string }[] }>(
      "/api/knowledge/ask",
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

    return fetch(`${API_BASE}/api/knowledge/ask/stream?${params}`, {
      headers,
      signal: abortSignal,
    }).then(async (response) => {
      if (!response.ok) {
        onError?.(`HTTP ${response.status}`);
        return;
      }
      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";

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
              if (data.text) onToken?.(data.text);
              if (data.model) onDone?.(data.model);
            } catch {
              // ignore parse errors for partial chunks
            }
          }
        }
      }
    }).catch((err) => {
      if (err.name !== "AbortError") {
        onError?.(err.message);
      }
    });
  },
};

// Health
export const system = {
  health: () =>
    request<{ status: string; chromadb: string; database: string; llm: string }>(
      "/health"
    ),
};
