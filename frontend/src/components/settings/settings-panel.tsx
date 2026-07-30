"use client";

import { useState, useEffect } from "react";
import { system } from "@/lib/api";
import { Settings, Cpu, Database, Zap, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function SettingsPanel() {
  const [health, setHealth] = useState<Record<string, string> | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [model, setModel] = useState("gpt-4o-mini");
  const [apiKey, setApiKey] = useState("");

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
        <p className="mt-1 text-xs text-muted">配置模型、API Key 和系统状态</p>
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

        {/* Model Config */}
        <section>
          <h3 className="flex items-center gap-2 text-sm font-medium mb-3">
            <Cpu className="h-4 w-4 text-muted" />
            模型配置
          </h3>
          <div className="space-y-3">
            <div>
              <label htmlFor="apikey" className="block text-xs font-medium text-muted mb-1">
                API Key
              </label>
              <input
                id="apikey"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm
                           placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30
                           transition-[border-color,box-shadow] duration-200"
              />
              <p className="mt-1 text-[11px] text-muted/60">
                注意：生产环境中 API Key 通过环境变量配置
              </p>
            </div>
            <div>
              <label htmlFor="model" className="block text-xs font-medium text-muted mb-1">
                模型
              </label>
              <select
                id="model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm
                           focus:outline-none focus:ring-2 focus:ring-primary/30
                           transition-[border-color,box-shadow] duration-200 cursor-pointer"
              >
                <option value="gpt-4o">GPT-4o</option>
                <option value="gpt-4o-mini">GPT-4o-mini</option>
                <option value="gpt-4-turbo">GPT-4 Turbo</option>
                <option value="claude-3-5-sonnet">Claude 3.5 Sonnet</option>
                <option value="ollama">Ollama (本地)</option>
              </select>
            </div>
          </div>
        </section>


      </div>
    </div>
  );
}
