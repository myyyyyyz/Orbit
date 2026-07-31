"use client";

import { useState, useEffect, useCallback } from "react";
import { system } from "@/lib/api";
import {
  Settings, Cpu, Database, CheckCircle2, XCircle, Loader2,
  Plus, ChevronDown, ChevronUp, Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ModelConfig {
  name: string;
  apiKey: string;
  enabled: boolean;
}

function loadModels(): ModelConfig[] {
  if (typeof window === "undefined") return [{ name: "deepseek-chat", apiKey: "", enabled: true }];
  try {
    const saved = localStorage.getItem("orbit_llm_models_v2");
    if (saved) return JSON.parse(saved) as ModelConfig[];
  } catch { /* ignore */ }
  // migrate legacy
  const legacyModels: string[] = JSON.parse(localStorage.getItem("orbit_llm_models") || '["deepseek-chat"]');
  const activeModel = localStorage.getItem("orbit_llm_active_model") || "deepseek-chat";
  return legacyModels.map((name) => ({
    name,
    apiKey: name === activeModel ? (localStorage.getItem("orbit_llm_key") || "") : "",
    enabled: name === activeModel,
  }));
}

export function SettingsPanel() {
  const [health, setHealth] = useState<Record<string, string> | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);

  const [models, setModels] = useState<ModelConfig[]>(loadModels);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

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

  const persist = useCallback((m: ModelConfig[]) => {
    localStorage.setItem("orbit_llm_models_v2", JSON.stringify(m));
    // legacy compat
    const enabled = m.find((x) => x.enabled);
    if (enabled) {
      localStorage.setItem("orbit_llm_active_model", enabled.name);
      localStorage.setItem("orbit_llm_model", enabled.name);
      localStorage.setItem("orbit_llm_key", enabled.apiKey);
    }
  }, []);

  const toggle = (i: number) => {
    setExpandedIndex((prev) => {
      if (prev === i) {
        // collapsing - auto-remove if empty name
        if (!models[i].name.trim()) {
          removeModel(i);
          return null;
        }
        return null;
      }
      return i;
    });
  };

  const updateModel = (i: number, patch: Partial<ModelConfig>) => {
    const updated = models.map((m, idx) => (idx === i ? { ...m, ...patch } : m));
    // if enabling this model, disable others
    if (patch.enabled) {
      updated.forEach((m, idx) => { if (idx !== i) m.enabled = false; });
    }
    setModels(updated);
    persist(updated);
  };

  const addModel = () => {
    const updated = [...models, { name: "", apiKey: "", enabled: false }];
    setModels(updated);
    setExpandedIndex(updated.length - 1);
    persist(updated);
  };

  const removeModel = (i: number) => {
    if (models.length <= 1) return;
    const updated = models.filter((_, idx) => idx !== i);
    if (expandedIndex === i) setExpandedIndex(null);
    if (models[i].enabled && updated.length > 0) {
      updated[0].enabled = true;
    }
    setModels(updated);
    persist(updated);
  };

  const enabledModel = models.find((m) => m.enabled);

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
        <p className="mt-1 text-xs text-muted">配置模型与系统状态</p>
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

        {/* Model Management */}
        <section>
          <h3 className="flex items-center gap-2 text-sm font-medium mb-3">
            <Cpu className="h-4 w-4 text-muted" />
            模型管理
            {enabledModel && (
              <span className="text-[10px] bg-primary/15 text-primary px-1.5 py-0.5 rounded-full">
                {enabledModel.name}
              </span>
            )}
          </h3>

          <div className="space-y-2">
            {models.map((m, i) => {
              const isExpanded = expandedIndex === i;
              return (
                <div key={i}>
                  {/* Card header */}
                  <button
                    onClick={() => toggle(i)}
                    className={cn(
                      "flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left transition-all duration-200 cursor-pointer",
                      m.enabled
                        ? "border-primary/40 bg-primary/5 shadow-[0_0_0_1px_var(--primary)]"
                        : "border-border/50 bg-surface/30 hover:border-primary/20"
                    )}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span className={cn(
                        "text-sm truncate",
                        m.enabled ? "text-primary font-medium" : "text-muted"
                      )}>
                        {m.name || "未命名模型"}
                      </span>
                      {m.enabled && (
                        <span className="shrink-0 text-[10px] bg-primary/20 text-primary px-1.5 py-0.5 rounded-full">
                          使用中
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {m.apiKey && (
                        <span className="hidden sm:inline text-[10px] text-muted/50">API Key 已配置</span>
                      )}
                      {models.length > 1 && (
                        <button
                          onClick={(e) => { e.stopPropagation(); removeModel(i); }}
                          className="rounded-md p-1 text-muted/30 hover:text-error hover:bg-error/10
                                     transition-all duration-150 cursor-pointer"
                          title="删除模型"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {isExpanded
                        ? <ChevronUp className="h-4 w-4 text-muted/40" />
                        : <ChevronDown className="h-4 w-4 text-muted/40" />
                      }
                    </div>
                  </button>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div className="mt-1.5 rounded-xl border border-border/50 bg-surface/20 px-4 py-3 space-y-3">
                      {/* API Key */}
                      <div>
                        <label className="block text-xs font-medium text-muted mb-1">
                          API Key
                        </label>
                        <input
                          type="password"
                          value={m.apiKey}
                          onChange={(e) => updateModel(i, { apiKey: e.target.value })}
                          placeholder="sk-..."
                          className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs
                                     placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30
                                     transition-[border-color,box-shadow] duration-200"
                        />
                      </div>

                      {/* Model Name */}
                      <div>
                        <label className="block text-xs font-medium text-muted mb-1">
                          模型名称
                        </label>
                        <input
                          type="text"
                          value={m.name}
                          onChange={(e) => updateModel(i, { name: e.target.value })}
                          placeholder="如 deepseek-chat"
                          className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs
                                     placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30
                                     transition-[border-color,box-shadow] duration-200"
                        />
                      </div>

                      {/* Enable toggle */}
                      <div className="flex items-center">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <button
                            role="switch"
                            aria-checked={m.enabled}
                            onClick={() => updateModel(i, { enabled: !m.enabled })}
                            className={cn(
                              "relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 cursor-pointer",
                              m.enabled ? "bg-primary" : "bg-surface border-border"
                            )}
                          >
                            <span
                              className={cn(
                                "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform duration-200",
                                m.enabled ? "translate-x-4" : "translate-x-0"
                              )}
                            />
                          </button>
                          <span className="text-xs text-muted">启用此模型</span>
                        </label>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Add button */}
          <button
            onClick={addModel}
            className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed
                       border-border/50 py-3 mt-2 text-xs text-muted hover:text-foreground hover:border-primary/30
                       transition-colors duration-150 cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5" />
            添加
          </button>
        </section>
      </div>
    </div>
  );
}
