"use client";

import { useState, useEffect, useCallback } from "react";
import { system, agents } from "@/lib/api";
import {
  Cpu, Database, CheckCircle2, XCircle, Loader2,
  Plus, ChevronDown, ChevronUp, Trash2, Sparkles, Clock, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ToolPolicyPanel } from "./tool-policy-panel";

// C4: 缓存命中率面板数据结构
interface CacheStats {
  total_entries: number;
  active_entries: number;
  max_size: number;
  hit_count: number;
  miss_count: number;
  hit_rate: number;
  index_enabled: boolean;
  index_ntotal: number;
  history: Array<{ ts: number; hit: boolean }>;
}

interface ModelConfig {
  name: string;
  apiKey: string;
  enabled: boolean;
}

// P4: per-role 模型配置（Agent Loop 各角色独立模型，存 orbit_llm_roles_v1）
const ROLE_LABELS: Record<string, string> = {
  planner: "Planner（规划）",
  builder: "Builder（执行）",
  reviewer: "Reviewer（审查）",
};

function loadRoleModels(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const saved = localStorage.getItem("orbit_llm_roles_v1");
    if (saved) return JSON.parse(saved) as Record<string, string>;
  } catch { /* ignore */ }
  return {};
}

function loadModels(): ModelConfig[] {
  if (typeof window === "undefined") return [{ name: "deepseek-chat", apiKey: "", enabled: true }];
  try {
    const saved = localStorage.getItem("orbit_llm_models_v2");
    if (saved) return JSON.parse(saved) as ModelConfig[];
  } catch { /* ignore */ }
  // migrate legacy（保护损坏的旧数据不崩溃）
  let legacyModels: string[] = ["deepseek-chat"];
  try {
    const raw = localStorage.getItem("orbit_llm_models");
    if (raw) legacyModels = JSON.parse(raw) as string[];
  } catch { /* corrupted legacy data, fallback to default */ }
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

  // C4: 缓存命中率
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null);
  const [cacheLoading, setCacheLoading] = useState(false);
  const [clearing, setClearing] = useState(false);

  const [models, setModels] = useState<ModelConfig[]>(loadModels);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  const [roleModels, setRoleModels] = useState<Record<string, string>>(loadRoleModels);

  // P5: Schedule 管理
  const [schedules, setSchedules] = useState<Array<{
    id: number; project_name: string; task_prompt: string; cron_expr: string;
    mode: "L1" | "L2"; enabled: boolean; next_run_at?: string;
  }>>([]);
  const [scheduleForm, setScheduleForm] = useState({
    project_name: "",
    task_prompt: "",
    cron_expr: "0 9 * * *",
    mode: "L1" as "L1" | "L2",
  });
  const [scheduleLoading, setScheduleLoading] = useState(false);

  const updateRoleModel = useCallback((role: string, model: string) => {
    setRoleModels((prev) => {
      const next = { ...prev, [role]: model };
      localStorage.setItem("orbit_llm_roles_v1", JSON.stringify(next));
      return next;
    });
  }, []);

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

  // C4: 缓存命中率
  const refreshCacheStats = async () => {
    setCacheLoading(true);
    try {
      setCacheStats(await system.cacheStats());
    } catch {
      setCacheStats(null);
    } finally {
      setCacheLoading(false);
    }
  };

  const clearCache = async () => {
    setClearing(true);
    try {
      await system.cacheClear();
      await refreshCacheStats();
    } finally {
      setClearing(false);
    }
  };

  useEffect(() => {
    checkHealth();
    refreshCacheStats();
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
    const willCollapse = expandedIndex === i;
    if (willCollapse) {
      // 折叠时若模型名为空则自动移除（在事件处理顶层处理，避免在 state updater 中触发其他 state 更新导致渲染警告）
      if (!models[i].name.trim()) {
        removeModel(i);
      } else {
        setExpandedIndex(null);
      }
    } else {
      setExpandedIndex(i);
    }
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

  useEffect(() => {
    agents.listSchedules().then((r) => setSchedules(r.schedules)).catch(() => setSchedules([]));
  }, []);

  const refreshSchedules = async () => {
    const r = await agents.listSchedules();
    setSchedules(r.schedules);
  };

  const createSchedule = async () => {
    if (!scheduleForm.project_name.trim() || !scheduleForm.task_prompt.trim()) return;
    setScheduleLoading(true);
    try {
      await agents.createSchedule({
        project_name: scheduleForm.project_name.trim(),
        task_prompt: scheduleForm.task_prompt.trim(),
        cron_expr: scheduleForm.cron_expr.trim(),
        mode: scheduleForm.mode,
      });
      setScheduleForm({ project_name: "", task_prompt: "", cron_expr: "0 9 * * *", mode: "L1" });
      await refreshSchedules();
    } finally {
      setScheduleLoading(false);
    }
  };

  const toggleSchedule = async (id: number, enabled: boolean) => {
    await agents.updateSchedule(id, { enabled });
    await refreshSchedules();
  };

  const deleteSchedule = async (id: number) => {
    await agents.deleteSchedule(id);
    await refreshSchedules();
  };

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
                <StatusIcon ok={health?.sqlite === "ok"} />
                {health?.sqlite === "ok" ? "正常" : "异常"}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted">LLM 可达性</span>
              <span className="flex items-center gap-1.5 text-xs">
                <StatusIcon ok={health?.llm_api === "ok"} />
                {health?.llm_api === "ok" ? "可达" : "不可达"}
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

        {/* C4: 缓存命中率趋势面板 */}
        <section>
          <h3 className="flex items-center gap-2 text-sm font-medium mb-3">
            <Zap className="h-4 w-4 text-muted" />
            缓存命中率
            <span className="text-[10px] bg-primary/15 text-primary px-1.5 py-0.5 rounded-full">
              {cacheStats ? `命中率 ${(cacheStats.hit_rate * 100).toFixed(1)}%` : "—"}
            </span>
          </h3>
          <div className="rounded-xl border border-border bg-surface/50 p-4 space-y-3">
            {cacheLoading ? (
              <div className="flex items-center gap-2 text-xs text-muted py-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载中…
              </div>
            ) : !cacheStats ? (
              <div className="text-xs text-error py-1">无法获取缓存统计（后端未启动？）</div>
            ) : (
              <>
                {/* 累计指标 */}
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-lg bg-surface p-2">
                    <div className="text-base font-semibold">{cacheStats.hit_count}</div>
                    <div className="text-[10px] text-muted mt-0.5">命中</div>
                  </div>
                  <div className="rounded-lg bg-surface p-2">
                    <div className="text-base font-semibold">{cacheStats.miss_count}</div>
                    <div className="text-[10px] text-muted mt-0.5">未命中</div>
                  </div>
                  <div className="rounded-lg bg-surface p-2">
                    <div className="text-base font-semibold">{cacheStats.total_entries}<span className="text-xs text-muted font-normal">/{cacheStats.max_size}</span></div>
                    <div className="text-[10px] text-muted mt-0.5">缓存条目</div>
                  </div>
                </div>

                {/* 命中率进度条 */}
                <div className="space-y-1.5">
                  <div className="flex justify-between text-[10px] text-muted">
                    <span>累计命中率</span>
                    <span>{(cacheStats.hit_rate * 100).toFixed(1)}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-border/60 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary transition-all duration-500"
                      style={{ width: `${Math.min(cacheStats.hit_rate * 100, 100)}%` }}
                    />
                  </div>
                </div>

                {/* 最近查询趋势条（绿色=命中，红色=未命中） */}
                {cacheStats.history.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-[10px] text-muted">
                      <span>最近 {cacheStats.history.length} 次查询</span>
                      <span>{cacheStats.index_enabled ? "Faiss 索引已启用" : "暴力搜索（索引不可用）"}</span>
                    </div>
                    <div className="flex gap-[3px] h-4 items-end">
                      {cacheStats.history.map((h, i) => (
                        <div
                          key={i}
                          title={h.hit ? "命中" : "未命中"}
                          className={cn(
                            "flex-1 rounded-sm transition-all",
                            h.hit ? "bg-success/70" : "bg-error/60"
                          )}
                          style={{ height: h.hit ? "100%" : "45%" }}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* 操作 */}
                <div className="flex items-center justify-between pt-1">
                  <button
                    onClick={refreshCacheStats}
                    className="text-xs text-primary hover:underline cursor-pointer"
                  >
                    刷新
                  </button>
                  <button
                    onClick={clearCache}
                    disabled={clearing}
                    className={cn(
                      "text-xs cursor-pointer transition-colors",
                      clearing ? "text-muted" : "text-error hover:underline"
                    )}
                  >
                    {clearing ? "清空中…" : "清空缓存"}
                  </button>
                </div>
              </>
            )}
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

        {/* P4: Agent 角色模型 */}
        <section>
          <h3 className="flex items-center gap-2 text-sm font-medium mb-1">
            <Sparkles className="h-4 w-4 text-muted" />
            Agent 角色模型
          </h3>
          <p className="text-[11px] text-muted mb-3">
            Agent Loop 各角色独立模型（可选）。留空则使用上方启用的默认模型。
          </p>
          <div className="space-y-3 rounded-xl border border-border/50 bg-surface/30 p-4">
            {Object.entries(ROLE_LABELS).map(([role, label]) => (
              <div key={role}>
                <label className="block text-xs font-medium text-muted mb-1">
                  {label}
                </label>
                <input
                  type="text"
                  value={roleModels[role] || ""}
                  onChange={(e) => updateRoleModel(role, e.target.value)}
                  placeholder="留空 = 默认模型"
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs
                             placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30
                             transition-[border-color,box-shadow] duration-200"
                />
              </div>
            ))}
            <p className="text-[10px] text-muted/50">
              例：Planner 用 gpt-4o-mini（便宜）、Builder 用 deepseek-chat、Reviewer 用 deepseek-reasoner（推理强）。
            </p>
          </div>
        </section>

        {/* 项目工具权限（三态门控配置） */}
        <ToolPolicyPanel />

        {/* P5: Schedule 管理 */}
        <section>
          <h3 className="flex items-center gap-2 text-sm font-medium mb-3">
            <Clock className="h-4 w-4 text-muted" />
            定时触发器
          </h3>
          <div className="space-y-3 rounded-xl border border-border/50 bg-surface/30 p-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <input
                type="text"
                value={scheduleForm.project_name}
                onChange={(e) => setScheduleForm({ ...scheduleForm, project_name: e.target.value })}
                placeholder="项目名"
                className="rounded-lg border border-border bg-surface px-3 py-2 text-xs
                           placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              <select
                value={scheduleForm.mode}
                onChange={(e) => setScheduleForm({ ...scheduleForm, mode: e.target.value as "L1" | "L2" })}
                className="rounded-lg border border-border bg-surface px-3 py-2 text-xs"
              >
                <option value="L1">L1 报告（只读分析+更新STATE）</option>
                <option value="L2">L2 行动（用户确认后落盘）</option>
              </select>
            </div>
            <input
              type="text"
              value={scheduleForm.cron_expr}
              onChange={(e) => setScheduleForm({ ...scheduleForm, cron_expr: e.target.value })}
              placeholder="cron: m h dom mon dow（例：0 9 * * *）"
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs
                         placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
            <textarea
              value={scheduleForm.task_prompt}
              onChange={(e) => setScheduleForm({ ...scheduleForm, task_prompt: e.target.value })}
              placeholder="每次触发时给 agent 的任务描述"
              rows={2}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs
                         placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none"
            />
            <button
              onClick={createSchedule}
              disabled={scheduleLoading || !scheduleForm.project_name.trim() || !scheduleForm.task_prompt.trim()}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground
                         hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {scheduleLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              创建 schedule
            </button>

            {schedules.length > 0 && (
              <div className="space-y-2 pt-2 border-t border-border/50">
                {schedules.map((s) => (
                  <div key={s.id} className="flex items-start justify-between gap-2 text-xs">
                    <div className="min-w-0">
                      <div className="font-medium truncate">{s.project_name}</div>
                      <div className="text-muted truncate">{s.task_prompt}</div>
                      <div className="text-[10px] text-muted/70">
                        {s.cron_expr} · {s.mode} · 下次 {s.next_run_at || "未计算"}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => toggleSchedule(s.id, !s.enabled)}
                        className={cn(
                          "rounded px-2 py-1 transition-colors",
                          s.enabled
                            ? "bg-success-soft text-success"
                            : "bg-surface-elevated text-muted"
                        )}
                      >
                        {s.enabled ? "启用" : "禁用"}
                      </button>
                      <button
                        onClick={() => deleteSchedule(s.id)}
                        className="rounded p-1 text-muted/50 hover:text-error hover:bg-error/10"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
