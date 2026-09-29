"use client";

import { useState, useCallback, useRef } from "react";
import { Search, FileText, Loader2, ExternalLink } from "lucide-react";
import { knowledge } from "@/lib/api";
import { motion, AnimatePresence } from "motion/react";

interface SearchResult {
  // Bug #16: 与后端 /api/knowledge/search 对齐（text/score/metadata.source）
  text: string;
  content?: string;
  metadata: Record<string, string> & { source?: string; filename?: string };
  score: number;
  similarity?: number;
}

export function SearchPanel() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  // IME 组字状态跟踪：中文/日文输入法拼音确认期间为 true
  const isComposingRef = useRef(false);

  // 直接依赖 query，不再用 ref 镜像它——渲染期写 ref 会被 React Compiler 判违规，
  // 而且 ref 镜像本来就是为了让 useCallback 保持空依赖，得不偿失。
  const handleSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;

    setLoading(true);
    setSearched(true);

    try {
      const res = await knowledge.search(q);
      setResults(res.results);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // 中文输入法 composing 期间（如拼音确认）不触发搜索，仅确认候选词
    if (isComposingRef.current || e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter") handleSearch();
  };

  const similarityColor = (sim: number) => {
    if (sim >= 0.85) return "text-success";
    if (sim >= 0.7) return "text-accent";
    return "text-muted/60";
  };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <h2 className="text-base font-semibold tracking-tight">搜索知识库</h2>
        <p className="mt-1 text-xs text-muted">语义检索你的专属知识</p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {/* Search Input */}
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            onCompositionStart={() => { isComposingRef.current = true; }}
            onCompositionEnd={(e) => {
              isComposingRef.current = false;
              setQuery(e.currentTarget.value);
            }}
            placeholder="输入关键词搜索..."
            className="w-full rounded-lg border border-border bg-surface py-2.5 pl-9 pr-16 text-sm
                       placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30
                       transition-[border-color,box-shadow] duration-200"
          />
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/50" />
          <button
            onClick={handleSearch}
            disabled={!query.trim() || loading}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md bg-primary px-3 py-1
                       text-[11px] font-medium text-white hover:bg-primary-hover
                       transition-colors duration-150 cursor-pointer
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : "搜索"}
          </button>
        </div>

        {/* Results */}
        <AnimatePresence mode="wait">
          {loading ? (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center py-12"
            >
              <Loader2 className="h-6 w-6 text-primary animate-spin" />
              <p className="mt-3 text-sm text-muted">搜索中...</p>
            </motion.div>
          ) : searched && results.length === 0 ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-xl border border-border/50 bg-surface/30 px-4 py-10 text-center"
            >
              <Search className="mx-auto h-6 w-6 text-muted/30" />
              <p className="mt-2 text-sm text-muted">未找到相关结果</p>
              <p className="mt-0.5 text-xs text-muted/60">尝试不同的关键词</p>
            </motion.div>
          ) : results.length > 0 ? (
            <motion.div
              key="results"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="space-y-2"
            >
              <p className="text-xs font-medium text-muted/70">
                找到 {results.length} 条结果
              </p>
              {results.map((r, i) => {
                // Bug #16: 后端字段为 text/score/metadata.source（非 content/similarity/filename）
                const content = (r.text as string) ?? (r.content as string);
                const score = (r.score as number) ?? (r.similarity as number);
                const meta = (r.metadata || {}) as Record<string, unknown>;
                const filename = (meta.source ?? meta.filename) as string;
                return (
                  <motion.div
                    key={`${filename || "result"}-${i}`}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className="rounded-lg border border-border/50 bg-surface/30 p-3.5
                               hover:border-primary/20 transition-colors duration-150 cursor-pointer"
                  >
                    <div className="flex items-start gap-2.5">
                      <FileText className="h-4 w-4 shrink-0 text-primary/60 mt-0.5" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm leading-relaxed text-foreground/85 line-clamp-3">
                          {content || "(无内容)"}
                        </p>
                        <div className="mt-2 flex items-center gap-3">
                          {filename && (
                            <span className="flex items-center gap-1 text-[11px] text-primary/70">
                              <ExternalLink className="h-2.5 w-2.5" />
                              {filename}
                            </span>
                          )}
                          <span className={similarityColor(score)}>
                            {typeof score === "number" ? `${Math.round(score * 100)}% 匹配` : "—"}
                          </span>
                        </div>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>
          ) : !searched ? (
            <div className="rounded-xl border border-border/50 bg-surface/30 px-4 py-10 text-center">
              <Search className="mx-auto h-6 w-6 text-muted/30" />
              <p className="mt-2 text-sm text-muted">输入关键词搜索知识库</p>
            </div>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  );
}
