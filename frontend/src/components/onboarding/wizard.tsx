"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  ChevronRight, ChevronLeft, CheckCircle2,
  Code2, Briefcase, GraduationCap, User, Building2,
} from "lucide-react";
import { cn } from "@/lib/utils";

const roles = [
  { id: "developer", label: "开发者", icon: Code2, desc: "写代码、调试、架构设计" },
  { id: "pm", label: "产品经理", icon: Briefcase, desc: "需求分析、产品规划" },
  { id: "manager", label: "管理者", icon: Building2, desc: "团队管理、项目协调" },
  { id: "student", label: "学生", icon: GraduationCap, desc: "学习、研究、论文" },
  { id: "other", label: "其他", icon: User, desc: "通用场景" },
];

const skills = {
  developer: ["review", "master", "pipeline-e2e-auditor"],
  pm: ["sage", "logos", "project-launcher"],
  manager: ["sage", "logos", "project-launcher"],
  student: ["logos", "sage"],
  other: ["logos", "sage", "review"],
};

interface WizardProps {
  onComplete: (role: string) => void;
}

export function OnboardingWizard({ onComplete }: WizardProps) {
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  const handleComplete = () => {
    if (selected) {
      onComplete(selected);
    }
  };

  return (
    <div className="flex h-full items-center justify-center px-4">
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 12 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -12 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          className="w-full max-w-md"
        >
          {step === 0 && (
            <div className="space-y-5">
              <div className="text-center">
                <h2 className="text-xl font-semibold tracking-tight">欢迎使用 Orbit</h2>
                <p className="mt-2 text-sm text-muted leading-relaxed">
                  AI Agent 端到端系统，帮你从想法到交付
                </p>
              </div>

              <div className="space-y-2">
                <div className="flex items-start gap-3 rounded-lg border border-border/50 bg-surface/30 px-4 py-3">
                  <MessageIcon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div>
                    <p className="text-sm font-medium">自然语言交互</p>
                    <p className="text-xs text-muted">像和人聊天一样描述你的需求</p>
                  </div>
                </div>
                <div className="flex items-start gap-3 rounded-lg border border-border/50 bg-surface/30 px-4 py-3">
                  <BookIcon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div>
                    <p className="text-sm font-medium">知识库增强</p>
                    <p className="text-xs text-muted">上传文档，AI 基于你的知识回答</p>
                  </div>
                </div>
                <div className="flex items-start gap-3 rounded-lg border border-border/50 bg-surface/30 px-4 py-3">
                  <AgentIcon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div>
                    <p className="text-sm font-medium">Agent 自动执行</p>
                    <p className="text-xs text-muted">AI 自动规划、编码、审查、交付</p>
                  </div>
                </div>
              </div>

              <button
                onClick={() => setStep(1)}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white
                           hover:bg-primary-hover active:scale-[0.98] transition-all duration-150 cursor-pointer"
              >
                开始
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-5">
              <div className="text-center">
                <h2 className="text-xl font-semibold tracking-tight">选择你的角色</h2>
                <p className="mt-2 text-sm text-muted">Orbit 会为你推荐合适的 Skill 组合</p>
              </div>

              <div className="space-y-2">
                {roles.map((role) => (
                  <button
                    key={role.id}
                    onClick={() => setSelected(role.id)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-all duration-150 cursor-pointer",
                      selected === role.id
                        ? "border-primary/40 bg-primary/10"
                        : "border-border/50 bg-surface/30 hover:border-primary/20"
                    )}
                  >
                    <div className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                      selected === role.id ? "bg-primary/20 text-primary" : "bg-surface text-muted"
                    )}>
                      <role.icon className="h-4.5 w-4.5" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">{role.label}</p>
                      <p className="text-xs text-muted">{role.desc}</p>
                    </div>
                    {selected === role.id && (
                      <CheckCircle2 className="ml-auto h-4 w-4 text-primary" />
                    )}
                  </button>
                ))}
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => setStep(0)}
                  className="flex items-center gap-1 rounded-lg border border-border px-4 py-2.5 text-xs text-muted
                             hover:text-foreground transition-colors duration-150 cursor-pointer"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  上一步
                </button>
                <button
                  onClick={handleComplete}
                  disabled={!selected}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white
                             hover:bg-primary-hover active:scale-[0.98] transition-all duration-150 cursor-pointer
                             disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  开始使用
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

function MessageIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

function BookIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
    </svg>
  );
}

function AgentIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
    </svg>
  );
}
