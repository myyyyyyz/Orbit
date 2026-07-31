"use client";

import { useState, useEffect, useCallback } from "react";
import { system } from "@/lib/api";
import { Settings, Cpu, Database, Zap, CheckCircle2, XCircle, Loader2, Save, Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";

function loadModels(): string[] {
  if (typeof window === "undefined") return ["deepseek-chat"];
  try {
    return JSON.parse(localStorage.getItem("orbit_llm_models") || '["deepseek-chat"]');
  } catch {
    return ["deepseek-chat"];
  }
}

function loadActiveModel(): string {
  if (typeof window === "undefined") return "deepseek-chat";
  return localStorage.getItem("orbit_llm_active_model") || "deepseek-chat";
}

function getSavedApiKey(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("orbit_llm_key")
    || process.env.NEXT_PUBLIC_LLM_API_KEY
    || "";
}

export function SettingsPanel() {
  const [health, setHealth] = useState<Record<string, string> | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [apiKey, setApiKey] = useState(getSavedApiKey);
  const [keySaved, setKeySaved] = useState(false);
  const [keyMasked, setKeyMasked] = useState(true);

  // Model management
  const [models, setModels] = useState<string[]>(loadModels);
  const [activeModel, setActiveModel] = useState(loadActiveModel);
  const [newModel, setNewModel] = useState("");

  const checkHealth = async () => {
    setHealthLoading(true);
    try {
      const res = await system.health();
      setHealth(res);
    } catch {
      setHealth({ status: "unreachable" });
    } finally {
      setHealthLoading(false);
    }
  };

  useEffect(() => {
    checkHealth();
  }, []);

  const persist = useCallback((m: string[], active: string) => {
    localStorage.setItem("orbit_llm_models", JSON.stringify(m));
    localStorage.setItem("orbit_llm_active_model", active);
    localStorage.setItem("orbit_llm_model", active); // legacy compat
  }, []);

  const saveApiKey = useCallback(() => {
    localStorage.setItem("orbit_llm_key", apiKey);
    setKeySaved(true);
    setTimeout(() => setKeySaved(false), 2000);
  }, [apiKey]);

  const selectModel = useCallback((name: string) => {
    setActiveModel(name);
    persist(models, name);
  }, [models, persist]);

  const addModel = useCallback(() => {
    const name = newModel.trim();
    if (!name || models.includes(name)) return;
    const updated = [...models, name];
    setModels(updated);
    setNewModel("");
    persist(updated, activeModel);
  }, [newModel, models, activeModel, persist]);

  const removeModel = useCallback((name: string) => {
    if (models.length <= 1) return;
    const updated = models.filter((m) => m !== name);
    setModels(updated);
    const nextActive = activeModel === name ? updated[0] : activeModel;
    setActiveModel(nextActive);
    persist(updated, nextActive);
  }, [models, activeModel, persist]);

  const handleNewKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") addModel();
  };

  const hasKey = apiKey.length > 0;

  const StatusIcon = ({ ok }: { ok: boolean }) =>
    ok ? (
      <CheckCircle2 className="h-3.5 w-3.5 text-success" />
    ) : (
      <XCircle className="h-3.5 w-3.5 text-error" />
    );

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <h2 className="text-base font-semibold tracking-tight">设置</h2>
        <p className="mt-1 text-xs text-muted">配置 API Key、模型列表和系统状态</p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
        {/* System Health */}
        <section>
          <h3 className="flex items-center gap-2 text-sm font-medium mb-3">
            <Database className="h-4 w-4 text-muted" />
            系统状态
          </h3>
          <div className="rounded-xl border border-border bg-surface/50 p-4 space-y-2.5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted">API 服务</span>
              {healthLoading ? (
                <Loader2 className="h-3.5 w-3.5 text-muted animate-spin" />
              ) : (
                <span className={cn(
                  "flex items-center gap-1.5 text-xs",
                  health?.status === "ok" ? "text-success" : "text-error"
                )}>
                  <StatusIcon ok={health?.status === "ok"} />
                  {health?.status === "ok" ? "正常" : health?.status || "不可达"}
                </span>
              )}
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted">ChromaDB</span>
              <span className="flex items-center gap-1.5 text-xs">
                <StatusIcon ok={health?.chromadb === "ok"} />
                {health?.chromadb === "ok" ? "正常" : "异常"}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted">SQLite</span>
              <span className="flex items-center gap-1.5 text-xs">
                <StatusIcon ok={health?.database === "ok"} />
                {health?.database === "ok" ? "正常" : "异常"}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted">LLM 可达性</span>
              <span className="flex items-center gap-1.5 text-xs">
                <StatusIcon ok={health?.llm === "reachable"} />
                {health?.llm === "reachable" ? "可达" : "不可达"}
              </span>
            </div>
            <button
              onClick={checkHealth}
              className="mt-1 text-xs text-primary hover:underline cursor-pointer"
            >
              刷新检查
            </button>
          </div>
        </section>

        {/* API Key */}
        <section>
          <h3 className="flex items-center gap-2 text-sm font-medium mb-3">
            <Settings className="h-4 w-4 text-muted" />
            API Key
          </h3>
          <div>
            <div className="flex gap-2">
              <input
                type={keyMasked ? "password" : "text"}
                value={apiKey}
                onChange={(e) => { setApiKey(e.target.value); setKeySaved(false); }}
                placeholder="sk-..."
                className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm
                           placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30
                           transition-[border-color,box-shadow] duration-200"
              />
              <button
                onClick={saveApiKey}
                className="flex items-center gap-1 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-white
                           hover:bg-primary-hover active:scale-[0.98] transition-all duration-150 cursor-pointer shrink-0"
              >
                {keySaved ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
                {keySaved ? "已保存" : "保存"}
              </button>
            </div>
            <div className="flex items-center justify-between mt-1">
              <p className="text-[11px] text-muted/60">
                密钥仅保存在浏览器本地 {hasKey && <span className="text-success">(已配置)</span>}
              </p>
              <button
                onClick={() => setKeyMasked(!keyMasked)}
                className="text-[11px] text-primary hover:underline cursor-pointer"
              >
                {keyMasked ? "显示" : "隐藏"}
              </button>
            </div>
          </div>
        </section>

        {/* Model Config */}
        <section>
          <h3 className="flex items-center gap-2 text-sm font-medium mb-3">
            <Cpu className="h-4 w-4 text-muted" />
            模型管理
          </h3>

          {/* Add model */}
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={newModel}
              onChange={(e) => setNewModel(e.target.value)}
              onKeyDown={handleNewKeyDown}
              placeholder="输入模型名称，如 deepseek-chat"
              className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm
                         placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30
                         transition-[border-color,box-shadow] duration-200"
            />
            <button
              onClick={addModel}
              disabled={!newModel.trim() || models.includes(newModel.trim())}
              className="flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs
                         text-muted hover:text-foreground hover:border-primary/30 disabled:opacity-30
                         transition-all duration-150 cursor-pointer shrink-0"
            >
              <Plus className="h-3.5 w-3.5" />
              添加
            </button>
          </div>

          {/* Model list */}
          <div className="space-y-1.5">
            {models.map((name) => {
              const isActive = name === activeModel;
              return (
                <button
                  key={name}
                  onClick={() => selectModel(name)}
                  className={cn(
                    "flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-left transition-all duration-150 cursor-pointer",
                    isActive
                      ? "border-primary/40 bg-primary/10 shadow-[0_0_0_1px_var(--primary)]"
                      : "border-border/50 bg-surface/30 hover:border-primary/20"
                  )}
                >
                  <span className={cn(
                    "text-sm",
                    isActive ? "text-primary font-medium" : "text-muted"
                  )}>
                    {name}
                    {isActive && (
                      <span className="ml-2 text-[10px] bg-primary/20 text-primary px-1.5 py-0.5 rounded-full">
                        使用中
                      </span>
                    )}
                  </span>
                  {models.length > 1 && (
                    <button
                      onClick={(e) => { e.stopPropagation(); removeModel(name); }}
                      className="rounded p-1 text-muted/30 hover:text-error hover:bg-error/10
                                 transition-all duration-150 cursor-pointer"
                      title="删除模型"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
