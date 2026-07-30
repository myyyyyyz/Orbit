"use client";

import { useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import {
  Eye, CheckCircle2, Clock, XCircle, AlertTriangle,
  ChevronDown, ChevronUp, FileText, Code2, GitBranch, Shield,
} from "lucide-react";
import { cn } from "@/lib/utils";

type AgentStatus = "idle" | "running" | "completed" | "failed" | "pending";

interface AgentStep {
  id: string;
  agent: string;
  icon: typeof Eye;
  status: AgentStatus;
  time?: string;
  detail: string;
  expanded?: {
    type: "plan" | "code" | "review";
    title: string;
    content: string;
  };
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

const mockSteps: AgentStep[] = [
  {
    id: "s1", agent: "Master", icon: Eye, status: "completed", time: "12:03",
    detail: "需求对齐完成，输出结构化 Spec",
    expanded: { type: "plan", title: "Master 需求对齐 Spec", content: "## 用户意图\n构建一个用户管理模块\n\n## 功能边界\n- 用户注册/登录\n- 角色权限\n- 个人资料编辑\n\n## 技术约束\n- React + TypeScript\n- RESTful API" }
  },
  {
    id: "s2", agent: "Planner", icon: FileText, status: "completed", time: "12:05",
    detail: "执行计划产出，3 模块，影响面分析无风险",
    expanded: { type: "plan", title: "Planner 执行计划", content: "## 变更清单\n1. `src/pages/auth/` - 新增登录注册页\n2. `src/components/user/` - 用户资料组件\n3. `src/api/user.ts` - API 封装\n\n## 影响面\n- 路由层：新增 3 条路由\n- 状态层：新增 AuthContext\n- 无破坏性变更" }
  },
  {
    id: "s3", agent: "Builder", icon: Code2, status: "running", time: "12:07",
    detail: "正在执行代码修改...",
    expanded: { type: "code", title: "Builder 代码变更 (进行中)", content: "```tsx\n// src/components/user/ProfileCard.tsx\nexport function ProfileCard({ user }) {\n  return (\n    <Card>\n      <Avatar src={user.avatar} />\n      <h2>{user.name}</h2>\n      <p>{user.bio}</p>\n    </Card>\n  );\n}\n```" }
  },
  {
    id: "s4", agent: "Reviewer", icon: Shield, status: "pending", time: "-",
    detail: "等待 Builder 完成后开始两阶段审查",
  },
];

const AgentIcon = ({ agent }: { agent: string }) => {
  const Icon = agentIcons[agent.toLowerCase()] || Eye;
  return <Icon className="h-4 w-4" />;
};

export function AgentPanel() {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const reduce = useReducedMotion();

  const toggle = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4">
        <h2 className="text-base font-semibold tracking-tight">Agent 观察台</h2>
        <p className="mt-1 text-xs text-muted">实时查看 Agent Loop 执行状态与产出</p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {/* Status Summary */}
        <div className="mb-5 grid grid-cols-4 gap-2">
          {(["completed", "running", "failed", "pending"] as AgentStatus[]).map((s) => {
            const count = mockSteps.filter((step) => step.status === s).length;
            const cfg = statusConfig[s];
            return (
              <div key={s} className="rounded-lg border border-border/50 bg-surface/40 px-3 py-2.5 text-center">
                <cfg.icon className={cn("mx-auto h-4 w-4 mb-1", cfg.color)} />
                <p className="text-[11px] text-muted/60">{cfg.label}</p>
                <p className="text-sm font-semibold">{count}</p>
              </div>
            );
          })}
        </div>

        {/* Timeline */}
        <div className="space-y-0">
          {mockSteps.map((step, i) => {
            const cfg = statusConfig[step.status];
            const isRunning = step.status === "running";
            const isExpanded = expandedId === step.id;

            return (
              <div key={step.id} className="relative">
                {/* Vertical line + dot */}
                <div className="flex gap-3">
                  <div className="flex flex-col items-center pt-0.5">
                    <motion.div
                      animate={isRunning && !reduce ? { scale: [1, 1.3, 1] } : {}}
                      transition={{ repeat: Infinity, duration: 1.5 }}
                    >
                      <cfg.icon className={cn("h-4 w-4 relative z-10", cfg.color)} />
                    </motion.div>
                    {i < mockSteps.length - 1 && (
                      <div
                        className={cn(
                          "w-px flex-1 my-0.5",
                          step.status === "completed" ? "bg-success/30" : "bg-border/30"
                        )}
                      />
                    )}
                  </div>

                  {/* Content */}
                  <div className="flex-1 pb-4">
                    <button
                      onClick={() => step.expanded && toggle(step.id)}
                      className={cn(
                        "w-full text-left rounded-xl border transition-all duration-200",
                        step.status === "pending" ? "opacity-40" : "",
                        step.expanded
                          ? "border-primary/20 bg-primary/5 cursor-pointer hover:border-primary/30"
                          : "border-border/50 bg-surface/30"
                      )}
                    >
                      <div className="flex items-center justify-between px-4 py-3">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span className={cn(
                            "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
                            step.status === "completed" ? "bg-success/15 text-success" :
                            step.status === "running" ? "bg-accent/15 text-accent" :
                            step.status === "failed" ? "bg-error/15 text-error" :
                            "bg-surface text-muted/40"
                          )}>
                            <AgentIcon agent={step.agent} />
                          </span>
                          <div className="min-w-0">
                            <span className="text-sm font-medium">{step.agent}</span>
                            <p className="text-xs text-muted truncate">{step.detail}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <span className="text-[11px] text-muted/60">{step.time}</span>
                          {step.expanded && (
                            isExpanded
                              ? <ChevronUp className="h-3.5 w-3.5 text-muted/50" />
                              : <ChevronDown className="h-3.5 w-3.5 text-muted/50" />
                          )}
                        </div>
                      </div>

                      {/* Expandable detail */}
                      <AnimatePresence>
                        {isExpanded && step.expanded && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                            className="overflow-hidden"
                          >
                            <div className="border-t border-border/50 px-4 py-3">
                              <p className="text-[11px] font-medium text-muted/70 uppercase tracking-wider mb-2">
                                {step.expanded.title}
                              </p>
                              <div className="rounded-lg bg-[#0a0f1a] border border-border/30 p-3">
                                <pre className="text-xs text-muted whitespace-pre-wrap font-mono leading-relaxed overflow-x-auto">
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
      </div>
    </div>
  );
}
