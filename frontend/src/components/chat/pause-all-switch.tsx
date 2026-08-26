"use client";

import { useEffect, useState } from "react";
import { agents } from "@/lib/api";
import { Pause, Play, Loader2 } from "lucide-react";

/**
 * 全局 loop 暂停开关（kill switch）。
 * 开启后新的 Agent Loop 会被暂停，用于紧急止损。
 */
export function PauseAllSwitch() {
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    agents
      .getPauseAll()
      .then((r) => setPaused(r.value))
      .catch(() => setPaused(false));
  }, []);

  const toggle = async () => {
    setLoading(true);
    try {
      const r = await agents.setPauseAll(!paused);
      setPaused(r.value);
    } catch {
      /* 保持原状态，避免 UI 与后端不一致 */
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={toggle}
      disabled={loading}
      role="switch"
      aria-checked={paused}
      aria-label="全局暂停 Agent Loop"
      title={
        paused
          ? "全局暂停已开启：新的 Agent Loop 将不会执行"
          : "开启后新的 Agent Loop 将被暂停（紧急止损开关）"
      }
      className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5
                  text-[0.6875rem] font-medium transition-all duration-200
                  disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer
        ${
          paused
            ? "border-error/40 bg-error-soft text-error hover:bg-error/20"
            : "border-border bg-surface-sunken text-muted hover:border-border-strong hover:text-foreground-muted"
        }`}
    >
      {loading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : paused ? (
        <>
          {/* 暂停中：脉冲点提示状态活跃 */}
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-error opacity-70" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-error" />
          </span>
          暂停中
        </>
      ) : (
        <>
          <Pause className="h-3.5 w-3.5" />
          全局暂停
        </>
      )}
    </button>
  );
}
