"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import {
  Eye, CheckCircle2, Clock, XCircle, AlertTriangle,
  ChevronDown, ChevronUp, FileText, Code2, Shield, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── 类型（迁移自 agent-panel.tsx 的 AgentStep schema，落地文档 §7.2）──

export type AgentStatus = "idle" | "running" | "completed" | "failed" | "pending";

export interface AgentStep {
  id: string;
  agent: string;
  status: AgentStatus;
  time?: string;
  detail: string;
  model?: string;              // 该 agent 实际使用的模型（per-role，审计用）
  expanded?: {
    type: "plan" | "code" | "review";
    title: string;
    content: string;
  };
}

interface CheckpointState {
  title: string;
  options: string[];
  kind?: string;                                        // "tool_approval" 时展示待批准命令
  commands?: { command: string; reason: string }[];
}

interface FailInfo {
  verdict: string;
  fail_reason: string;
  fix_direction: string;
}

interface AgentLoopCardProps {
  task: string;
  steps: AgentStep[];
  checkpoint?: CheckpointState | null;
  finished: boolean;
  outcome?: "done" | "failed" | null;   // Bug #12: 区分完成/失败
  failInfo?: FailInfo | null;           // 失败详情
  expandedId?: string | null;           // 受控展开状态（父组件控制）
  onToggleExpand?: (id: string) => void;
  onDecision: (decision: string, note?: string) => void;
}

const statusConfig: Record<AgentStatus, { icon: typeof CheckCircle2; color: string; label: string }> = {
  idle:     { icon: AlertTriangle, color: "text-muted/40", label: "等待" },
  running:  { icon: Clock, color: "text-accent", label: "执行中" },
  completed:{ icon: CheckCircle2, color: "text-success", label: "完成" },
  failed:   { icon: XCircle, color: "text-error", label: "失败" },
  pending:  { icon: AlertTriangle, color: "text-muted/40", label: "待执行" },
};

const agentIcons: Record<string, typeof Eye> = {
  master: Eye,
  planner: FileText,
  builder: Code2,
  reviewer: Shield,
  user: Eye,
};

const AgentIcon = ({ agent }: { agent: string }) => {
  const Icon = agentIcons[agent.toLowerCase()] || Sparkles;
  return <Icon className="h-4 w-4" />;
};

// checkpoint 选项 → 按钮文案（中文化）
const decisionLabels: Record<string, string> = {
  continue: "继续",
  adjust: "调整",
  rollback: "回退",
  approve: "标记完成",
  reject: "拒绝",
};

// 工具审批（tool_approval）场景下 approve/reject 的专属文案
const toolApprovalLabels: Record<string, string> = {
  approve: "允许执行",
  reject: "拒绝执行",
};

function checkpointLabel(opt: string, kind?: string): string {
  if (kind === "tool_approval" && toolApprovalLabels[opt]) return toolApprovalLabels[opt];
  return decisionLabels[opt] || opt;
}

export function AgentLoopCard({ task, steps, checkpoint, finished, outcome, failInfo, expandedId, onToggleExpand, onDecision }: AgentLoopCardProps) {
  const [note, setNote] = useState("");
  const [adjusting, setAdjusting] = useState(false);  // Bug #14: 点"调整"进入输入模式
  const reduce = useReducedMotion();

  const toggle = (id: string) => {
    onToggleExpand?.(id);
  };

  // 汇总统计（顶部概览）
  const stats = useMemo(() => {
    const s: Record<AgentStatus, number> = { idle: 0, running: 0, completed: 0, failed: 0, pending: 0 };
    steps.forEach((st) => { s[st.status] += 1; });
    return s;
  }, [steps]);

  const handleDecision = (decision: string) => {
    onDecision(decision, note.trim());
    setNote("");
  };

  return (
    <div className="my-2 rounded-xl border border-primary/20 bg-primary/5 overflow-hidden">
      {/* Header */}
      <div className="border-b border-border/40 px-4 py-2.5 flex items-center gap-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/15">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-foreground truncate">Agent Loop · {task}</p>
          <p className="text-[10px] text-muted/60">
            {finished
              ? outcome === "failed"
                ? <span className="text-error font-medium">执行失败</span>
                : "已完成"
              : `${steps.filter((s) => s.status === "running").length ? "执行中" : "进行中"}`}
            {" · "}
            {Object.entries(stats).map(([k, v]) => v > 0 && (
              <span key={k} className="mr-1.5">{statusConfig[k as AgentStatus].label} {v}</span>
            ))}
          </p>
        </div>
      </div>

      {/* Bug #12: 失败详情面板（CRITICAL_FAIL 升级给人） */}
      {finished && outcome === "failed" && failInfo && (
        <div className="mx-4 mb-3 rounded-lg border border-error/30 bg-error/5 px-3 py-2.5">
          <p className="flex items-center gap-1.5 text-xs font-medium text-error">
            <AlertTriangle className="h-3.5 w-3.5" />
            {failInfo.verdict}{failInfo.fix_direction ? " · 已升级给人处理" : ""}
          </p>
          <p className="mt-1 text-[11px] text-muted leading-relaxed">{failInfo.fail_reason}</p>
          {failInfo.fix_direction && (
            <p className="mt-1.5 text-[11px] text-foreground/80">
              <span className="text-muted/60">修复方向：</span>{failInfo.fix_direction}
            </p>
          )}
          <p className="mt-1.5 text-[10px] text-muted/50">
            可重新发起 <span className="font-mono">/loop</span> 调整任务描述后重试。
          </p>
        </div>
      )}

      {/* Timeline */}
      <div className="px-4 py-3">
        <div className="space-y-0">
          {steps.map((step, i) => {
            const cfg = statusConfig[step.status];
            const isRunning = step.status === "running";
            const isExpanded = expandedId === step.id;
            return (
              <div key={step.id} className="relative">
                <div className="flex gap-3">
                  {/* 时间线竖线 + 图标 */}
                  <div className="flex flex-col items-center pt-0.5">
                    <motion.div
                      animate={isRunning && !reduce ? { scale: [1, 1.3, 1] } : {}}
                      transition={{ repeat: Infinity, duration: 1.5 }}
                    >
                      <cfg.icon className={cn("h-4 w-4 relative z-10", cfg.color)} />
                    </motion.div>
                    {i < steps.length - 1 && (
                      <div className={cn(
                        "w-px flex-1 my-0.5",
                        step.status === "completed" ? "bg-success/30" : "bg-border/30"
                      )} />
                    )}
                  </div>

                  {/* 卡片内容 */}
                  <div className="flex-1 pb-3">
                    <button
                      onClick={() => step.expanded && toggle(step.id)}
                      className={cn(
                        "w-full text-left rounded-lg border px-3 py-2 transition-all duration-200",
                        step.status === "pending" ? "opacity-40" : "",
                        step.expanded
                          ? "border-primary/20 bg-primary/5 cursor-pointer hover:border-primary/30"
                          : "border-border/40 bg-surface/30"
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className={cn(
                            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
                            step.status === "completed" ? "bg-success/15 text-success" :
                            step.status === "running" ? "bg-accent/15 text-accent" :
                            step.status === "failed" ? "bg-error/15 text-error" :
                            "bg-surface text-muted/40"
                          )}>
                            <AgentIcon agent={step.agent} />
                          </span>
                          <span className="text-xs font-medium shrink-0">{step.agent}</span>
                          {step.model && (
                            <span className="shrink-0 rounded border border-border/40 bg-surface px-1 py-px text-[9px] text-muted/70 font-mono">
                              {step.model}
                            </span>
                          )}
                          <span className="text-[11px] text-muted truncate">{step.detail}</span>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {step.time && <span className="text-[10px] text-muted/50">{step.time}</span>}
                          {step.expanded && (
                            isExpanded
                              ? <ChevronUp className="h-3 w-3 text-muted/40" />
                              : <ChevronDown className="h-3 w-3 text-muted/40" />
                          )}
                        </div>
                      </div>

                      {/* 展开详情 */}
                      <AnimatePresence>
                        {isExpanded && step.expanded && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                            className="overflow-hidden"
                          >
                            <div className="border-t border-border/40 mt-2 pt-2">
                              <p className="text-[10px] font-medium text-muted/60 uppercase tracking-wider mb-1.5">
                                {step.expanded.title}
                              </p>
                              <div className="rounded-md bg-[#0a0f1a] border border-border/30 p-2.5">
                                <pre className="text-[11px] text-muted font-mono leading-relaxed whitespace-pre-wrap overflow-x-auto max-h-60">
                                  {step.expanded.content}
                                </pre>
                              </div>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Checkpoint 交互区（对话内嵌，落地文档 §7.3） */}
        <AnimatePresence>
          {checkpoint && !finished && (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
              className="rounded-lg border border-accent/30 bg-accent/5 px-3 py-2.5"
            >
              <p className="text-xs font-medium text-foreground flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-accent" />
                {checkpoint.title}
              </p>
              {checkpoint.kind === "tool_approval" && checkpoint.commands && checkpoint.commands.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {checkpoint.commands.map((c, i) => (
                    <li
                      key={i}
                      className="rounded-md border border-border/50 bg-surface/60 px-2 py-1.5 text-[11px]"
                    >
                      <code className="font-mono text-foreground break-all">{c.command}</code>
                      <span className="ml-1.5 text-muted/70">{c.reason}</span>
                    </li>
                  ))}
                </ul>
              )}
              {/* Bug #14: "调整"需要先填意见再提交（两段式），不能点一下就直接继续 */}
              {adjusting && (
                <div className="mt-2">
                  <input
                    autoFocus
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="填写调整意见，例如：第二步不要动 config.py..."
                    className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5
                               text-xs placeholder:text-muted/50 focus:outline-none focus:border-primary/40"
                  />
                  <div className="mt-1.5 flex gap-1.5">
                    <button
                      onClick={() => { onDecision("adjust", note.trim()); setNote(""); setAdjusting(false); }}
                      disabled={!note.trim()}
                      className="rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1
                                 text-[11px] font-medium text-primary hover:bg-primary/20 disabled:opacity-40
                                 transition-colors duration-150 cursor-pointer"
                    >
                      提交调整
                    </button>
                    <button
                      onClick={() => { setNote(""); setAdjusting(false); }}
                      className="rounded-md border border-border/40 px-2.5 py-1
                                 text-[11px] text-muted hover:text-foreground
                                 transition-colors duration-150 cursor-pointer"
                    >
                      取消
                    </button>
                  </div>
                </div>
              )}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {checkpoint.options.map((opt) => (
                  <button
                    key={opt}
                    onClick={() => {
                      if (opt === "adjust") {
                        // 进入输入模式，不直接提交
                        setAdjusting(true);
                      } else {
                        handleDecision(opt);
                      }
                    }}
                    className="rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1
                               text-[11px] font-medium text-primary hover:bg-primary/20
                               transition-colors duration-150 cursor-pointer"
                  >
                    {checkpointLabel(opt, checkpoint.kind)}
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
