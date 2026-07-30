"use client";

import { Eye, Clock, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";

const mockTimeline = [
  { agent: "Master", status: "completed", time: "12:03", detail: "需求对齐完成 — 输出结构化 Spec" },
  { agent: "Planner", status: "completed", time: "12:05", detail: "执行计划产出 — 3 模块, 0 风险" },
  { agent: "Builder", status: "running", time: "12:07", detail: "正在执行代码修改..." },
  { agent: "Reviewer", status: "pending", time: "-", detail: "等待 Builder 完成后开始审查" },
];

const statusIcon = (status: string) => {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-4 w-4 text-success" />;
    case "running":
      return <Clock className="h-4 w-4 text-accent animate-pulse" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-error" />;
    default:
      return <AlertTriangle className="h-4 w-4 text-muted/40" />;
  }
};

export function AgentPanel() {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border/50 px-6 py-4">
        <h2 className="text-base font-semibold tracking-tight">Agent 观察台</h2>
        <p className="mt-1 text-xs text-muted">实时查看 Agent Loop 执行状态</p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="space-y-0">
          {mockTimeline.map((entry, i) => (
            <div key={i} className="flex gap-3">
              {/* Timeline line + dot */}
              <div className="flex flex-col items-center">
                <div className="mt-1.5">{statusIcon(entry.status)}</div>
                {i < mockTimeline.length - 1 && (
                  <div className="w-px flex-1 bg-border/50 my-0.5" />
                )}
              </div>
              {/* Content */}
              <div className={entry.status === "pending" ? "opacity-40" : ""}>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{entry.agent}</span>
                  <span className="text-[11px] text-muted/60">{entry.time}</span>
                </div>
                <p className="text-xs text-muted mt-0.5">{entry.detail}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Placeholder for Phase 2 */}
        <div className="mt-8 rounded-xl border border-border/50 bg-surface/30 px-4 py-8 text-center">
          <Eye className="mx-auto h-6 w-6 text-muted/30" />
          <p className="mt-2 text-sm text-muted/50">
            Phase 2 将支持：计划卡片预览、代码 Diff 对比、审查报告
          </p>
        </div>
      </div>
    </div>
  );
}
