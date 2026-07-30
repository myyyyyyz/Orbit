"use client";

import { useState } from "react";
import { Wrench, ChevronDown, ChevronUp, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { cn } from "@/lib/utils";

export interface ToolCall {
  id: string;
  tool: string;
  status: "pending" | "running" | "success" | "error";
  input?: Record<string, unknown>;
  output?: string;
}

interface ToolCallCardProps {
  call: ToolCall;
}

const statusIcon = {
  pending:  <Loader2 className="h-3.5 w-3.5 text-muted/50" />,
  running:  <Loader2 className="h-3.5 w-3.5 text-accent animate-spin" />,
  success:  <CheckCircle2 className="h-3.5 w-3.5 text-success" />,
  error:    <XCircle className="h-3.5 w-3.5 text-error" />,
};

const statusLabel = {
  pending: "等待",
  running: "执行中",
  success: "完成",
  error: "失败",
};

export function ToolCallCard({ call }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = call.input || call.output;

  return (
    <div className="my-2">
      <button
        onClick={() => hasDetail && setExpanded(!expanded)}
        className={cn(
          "flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors duration-150",
          call.status === "running"
            ? "border-accent/30 bg-accent/5"
            : "border-border/50 bg-surface/40",
          hasDetail && "cursor-pointer hover:border-primary/20"
        )}
      >
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10">
          <Wrench className="h-3 w-3 text-primary" />
        </div>
        <span className="text-xs font-medium flex-1">
          {call.tool}
        </span>
        <span className="flex items-center gap-1 text-[11px] text-muted/60">
          {statusIcon[call.status]}
          {statusLabel[call.status]}
        </span>
        {hasDetail && (
          expanded
            ? <ChevronUp className="h-3 w-3 text-muted/40" />
            : <ChevronDown className="h-3 w-3 text-muted/40" />
        )}
      </button>

      <AnimatePresence>
        {expanded && hasDetail && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="ml-11 mt-1 space-y-1.5">
              {call.input && (
                <div className="rounded-md border border-border/30 bg-[#0a0f1a] px-3 py-1.5">
                  <p className="text-[10px] font-medium text-muted/50 uppercase tracking-wider mb-1">
                    输入参数
                  </p>
                  <pre className="text-[11px] text-muted font-mono leading-relaxed whitespace-pre-wrap">
                    {JSON.stringify(call.input, null, 2)}
                  </pre>
                </div>
              )}
              {call.output && (
                <div className="rounded-md border border-border/30 bg-[#0a0f1a] px-3 py-1.5">
                  <p className="text-[10px] font-medium text-muted/50 uppercase tracking-wider mb-1">
                    返回结果
                  </p>
                  <pre className="text-[11px] text-muted font-mono leading-relaxed whitespace-pre-wrap line-clamp-6">
                    {call.output}
                  </pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
