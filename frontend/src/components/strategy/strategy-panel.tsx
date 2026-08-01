"use client";

import { useState, useEffect, useCallback } from "react";
import { Sliders, Save, RotateCcw, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { strategy } from "@/lib/api";

interface StrategyState {
  chunk_size: number;
  chunk_overlap: number;
  top_k: number;
  embedding_model: string;
  search_mode: string;
  rerank_enabled: boolean;
}

async function fetchStrategy(): Promise<StrategyState> {
  return strategy.get();
}

async function updateStrategy(patch: Partial<StrategyState>): Promise<void> {
  const data = await strategy.patch(patch as Record<string, unknown>);
  if (!data.status) throw new Error("Update failed");
}

const defaults: StrategyState = {
  chunk_size: 500,
  chunk_overlap: 50,
  top_k: 5,
  embedding_model: "sentence-transformers",
  search_mode: "hybrid",
  rerank_enabled: false,
};

export function StrategyPanel() {
  const [strategy, setStrategy] = useState<StrategyState>(defaults);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [error, setError] = useState("");

  useEffect(() => {
    fetchStrategy()
      .then(setStrategy)
      .catch(() => {/* use defaults */})
      .finally(() => setLoading(false));
  }, []);

  const update = useCallback((key: keyof StrategyState, value: number | string | boolean) => {
    setStrategy((prev) => ({ ...prev, [key]: value }));
    setStatus("idle");
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setStatus("idle");
    try {
      await updateStrategy(strategy);
      setStatus("success");
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }, [strategy]);

  const handleReset = useCallback(() => {
    setStrategy(defaults);
    setStatus("idle");
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 text-primary animate-spin" />
      </div>
    );
  }

  const sliderClass = "w-full h-2 rounded-full appearance-none bg-surface border border-border cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary [&::-webkit-slider-thumb]:cursor-pointer";

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <h2 className="text-base font-semibold tracking-tight">RAG 策略配置</h2>
        <p className="mt-1 text-xs text-muted">调整检索增强生成的参数以优化问答效果</p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
        {/* Chunk Size */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium">Chunk 大小</label>
            <span className="text-xs font-mono text-primary">{strategy.chunk_size}</span>
          </div>
          <input
            type="range"
            min={100}
            max={2000}
            step={50}
            value={strategy.chunk_size}
            onChange={(e) => update("chunk_size", Number(e.target.value))}
            className={sliderClass}
          />
          <p className="mt-1 text-[11px] text-muted/60">每个文本块的字符数，越大上下文越多但精度越低</p>
        </section>

        {/* Chunk Overlap */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium">Chunk 重叠</label>
            <span className="text-xs font-mono text-primary">{strategy.chunk_overlap}</span>
          </div>
          <input
            type="range"
            min={0}
            max={200}
            step={10}
            value={strategy.chunk_overlap}
            onChange={(e) => update("chunk_overlap", Number(e.target.value))}
            className={sliderClass}
          />
          <p className="mt-1 text-[11px] text-muted/60">相邻块之间的重叠字符数，防止关键信息被切断</p>
        </section>

        {/* Top-K */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium">检索数量 (Top-K)</label>
            <span className="text-xs font-mono text-primary">{strategy.top_k}</span>
          </div>
          <input
            type="range"
            min={1}
            max={20}
            step={1}
            value={strategy.top_k}
            onChange={(e) => update("top_k", Number(e.target.value))}
            className={sliderClass}
          />
          <p className="mt-1 text-[11px] text-muted/60">每次查询返回的最相关文档片段数</p>
        </section>

        {/* Embedding Model */}
        <section>
          <label className="text-sm font-medium block mb-2">Embedding 模型</label>
          <select
            value={strategy.embedding_model}
            onChange={(e) => update("embedding_model", e.target.value)}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm
                       focus:outline-none focus:ring-2 focus:ring-primary/30 cursor-pointer
                       transition-[border-color,box-shadow] duration-200"
          >
            <option value="sentence-transformers">sentence-transformers (轻量本地)</option>
            <option value="bge-m3">BGE-M3 (中文最优)</option>
            <option value="openai">OpenAI text-embedding-3</option>
          </select>
        </section>

        {/* Search Mode */}
        <section>
          <label className="text-sm font-medium block mb-2">检索模式</label>
          <div className="grid grid-cols-3 gap-2">
            {(["vector", "bm25", "hybrid"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => update("search_mode", mode)}
                className={cn(
                  "rounded-lg border px-3 py-2 text-xs font-medium transition-all duration-150 cursor-pointer",
                  strategy.search_mode === mode
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "border-border/50 bg-surface/30 text-muted hover:border-primary/20"
                )}
              >
                {mode === "vector" ? "向量检索" : mode === "bm25" ? "BM25" : "混合检索"}
              </button>
            ))}
          </div>
        </section>

        {/* Rerank */}
        <section className="flex items-center justify-between">
          <div>
            <label className="text-sm font-medium">Rerank 重排序</label>
            <p className="text-[11px] text-muted/60 mt-0.5">对检索结果二次排序，提升精度</p>
          </div>
          <button
            role="switch"
            aria-checked={strategy.rerank_enabled}
            onClick={() => update("rerank_enabled", !strategy.rerank_enabled)}
            className={cn(
              "relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 cursor-pointer",
              strategy.rerank_enabled ? "bg-primary" : "bg-surface border-border"
            )}
          >
            <span
              className={cn(
                "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform duration-200",
                strategy.rerank_enabled ? "translate-x-4" : "translate-x-0"
              )}
            />
          </button>
        </section>

        {/* Actions */}
        <div className="flex items-center gap-2 pt-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-white
                       hover:bg-primary-hover active:scale-[0.98] transition-all duration-150 cursor-pointer
                       disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            保存
          </button>
          <button
            onClick={handleReset}
            className="flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-xs
                       text-muted hover:text-foreground hover:border-primary/20 transition-all duration-150 cursor-pointer"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            重置
          </button>

          {status === "success" && (
            <span className="flex items-center gap-1 text-xs text-success ml-auto">
              <CheckCircle2 className="h-3.5 w-3.5" />
              已保存
            </span>
          )}
          {status === "error" && (
            <span className="flex items-center gap-1 text-xs text-error ml-auto">
              <AlertCircle className="h-3.5 w-3.5" />
              {error}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
