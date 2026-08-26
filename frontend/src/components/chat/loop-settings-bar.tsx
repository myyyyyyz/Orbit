"use client";

import { useState } from "react";
import {
  FolderOpen,
  Coins,
  Gauge,
  Layers,
  SlidersHorizontal,
  ChevronDown,
} from "lucide-react";

interface Props {
  projectName: string;
  projectDir: string;
  mode: "interactive" | "L1" | "L2";
  budgetLimit: number;
  onProjectNameChange: (v: string) => void;
  onProjectDirChange: (v: string) => void;
  onModeChange: (v: "interactive" | "L1" | "L2") => void;
  onBudgetChange: (v: number) => void;
  /** 右侧插槽：全局暂停开关等 */
  actions?: React.ReactNode;
}

const MODE_HINT: Record<Props["mode"], string> = {
  interactive: "交互模式：每个关键节点等待你确认",
  L1: "L1 报告：只读分析并更新 STATE，不落盘",
  L2: "L2 行动：确认后由 Builder 实际写入文件",
};

const MODE_LABEL: Record<Props["mode"], string> = {
  interactive: "交互",
  L1: "L1 报告",
  L2: "L2 行动",
};

/** 紧凑显示 token 量级：100000 → 100K */
function shortTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 ? 1 : 0)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 ? 1 : 0)}K`;
  return String(n);
}

/**
 * Agent Loop 运行配置。
 * 默认收起为一行摘要（这些配置不需要每轮对话都调整），
 * 点击展开后编辑，避免占用输入区的垂直空间。
 */
export function LoopSettingsBar({
  projectName,
  projectDir,
  mode,
  budgetLimit,
  onProjectNameChange,
  onProjectDirChange,
  onModeChange,
  onBudgetChange,
  actions,
}: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="w-full">
      {/* 摘要行 */}
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="group flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-[0.6875rem]
                     text-muted transition-colors duration-150
                     hover:bg-surface hover:text-foreground-muted cursor-pointer"
        >
          <SlidersHorizontal className="h-3.5 w-3.5 shrink-0" />
          <span className="shrink-0 font-medium">Loop 配置</span>

          {/* 收起时展示关键信息摘要 */}
          {!expanded && (
            <span className="flex min-w-0 items-center gap-1.5 text-muted-subtle">
              <Chip>{MODE_LABEL[mode]}</Chip>
              <Chip>{shortTokens(budgetLimit)} tok</Chip>
              {projectName ? (
                <Chip title={projectName}>
                  <span className="max-w-[7rem] truncate">{projectName}</span>
                </Chip>
              ) : (
                <span className="text-muted-subtle">未设项目</span>
              )}
            </span>
          )}

          <ChevronDown
            className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${
              expanded ? "rotate-180" : ""
            }`}
          />
        </button>

        {actions}
      </div>

      {/* 展开的编辑区 */}
      {expanded && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
          <Field icon={<Layers className="h-3.5 w-3.5" />} label="项目">
            <input
              type="text"
              value={projectName}
              onChange={(e) => onProjectNameChange(e.target.value)}
              placeholder="STATE 脊柱标识"
              className="w-[8rem] bg-transparent text-xs text-foreground outline-none
                         placeholder:text-muted-subtle"
            />
          </Field>

          <Field icon={<FolderOpen className="h-3.5 w-3.5" />} label="目录">
            <input
              type="text"
              value={projectDir}
              onChange={(e) => onProjectDirChange(e.target.value)}
              placeholder="绝对路径（Builder 落盘）"
              className="w-[12rem] bg-transparent text-xs text-foreground outline-none
                         placeholder:text-muted-subtle"
            />
          </Field>

          {/* 模式：三段式分段控件，比原生 select 更直观 */}
          <div
            className="flex items-center gap-0.5 rounded-lg border border-border bg-surface-sunken p-0.5"
            role="radiogroup"
            aria-label="执行模式"
          >
            <Gauge className="ml-1.5 mr-0.5 h-3.5 w-3.5 shrink-0 text-muted-subtle" />
            {(["interactive", "L1", "L2"] as const).map((m) => {
              const active = mode === m;
              return (
                <button
                  key={m}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => onModeChange(m)}
                  title={MODE_HINT[m]}
                  className={`rounded-md px-2 py-1 text-[0.6875rem] font-medium transition-all duration-150 cursor-pointer
                    ${
                      active
                        ? "bg-primary/18 text-primary"
                        : "text-muted hover:bg-surface-elevated hover:text-foreground-muted"
                    }`}
                >
                  {m === "interactive" ? "交互" : m}
                </button>
              );
            })}
          </div>

          <Field icon={<Coins className="h-3.5 w-3.5" />} label="预算">
            <input
              type="number"
              min={1000}
              step={1000}
              value={budgetLimit}
              onChange={(e) =>
                onBudgetChange(Math.max(1000, parseInt(e.target.value || "0", 10)))
              }
              aria-label="Token 预算上限"
              className="w-[5.5rem] bg-transparent text-xs tabular text-foreground outline-none
                         [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none
                         [&::-webkit-outer-spin-button]:appearance-none"
            />
            <span className="shrink-0 text-[0.6875rem] text-muted-subtle">tok</span>
          </Field>
        </div>
      )}
    </div>
  );
}

/** 摘要行的信息胶囊 */
function Chip({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="rounded border border-border bg-surface px-1.5 py-0.5 text-[0.625rem] text-muted"
    >
      {children}
    </span>
  );
}

/** 统一字段容器：图标 + 标签 + 内容，focus 时整体高亮 */
function Field({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label
      className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-sunken px-2.5 py-1.5
                 transition-colors duration-150
                 hover:border-border-strong
                 focus-within:border-primary/50 focus-within:bg-surface"
    >
      <span className="shrink-0 text-muted-subtle">{icon}</span>
      <span className="shrink-0 text-[0.6875rem] text-muted">{label}</span>
      {children}
    </label>
  );
}
