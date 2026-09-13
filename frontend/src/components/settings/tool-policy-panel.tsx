"use client";

/**
 * 项目工具权限（三态门控配置）
 *
 * Agent Loop 执行 Builder 验证命令时的三层门控：
 * - 第1层 文件黑名单（.env / secrets / payments / terraform…）：写死，命中即硬拒（本面板仅展示说明）
 * - 第2层 命令写死名单（rm / curl / bash…）+ 非安全程序：不可自动执行，需人工同意
 * - 第3层 项目白名单（本面板可配）：
 *     · 自动执行清单 auto_commands：命中前缀 → 直接执行
 *     · 需人工同意清单 approval_commands：命中前缀 → 暂停等用户确认（优先级高于自动清单）
 *   其余命令默认需人工同意。
 *
 * 配置按「用户 + 项目目录」保存到后端，下次 loop 开始时生效。
 */

import { useState, useEffect, useCallback } from "react";
import { agents } from "@/lib/api";
import { ShieldCheck, Loader2, Save, RotateCcw, AlertTriangle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

function linesToArr(s: string): string[] {
  return s.split("\n").map((x) => x.trim()).filter(Boolean);
}

function arrToLines(a: string[]): string {
  return (a || []).join("\n");
}

export function ToolPolicyPanel() {
  const [projectDir, setProjectDir] = useState("");
  const [autoText, setAutoText] = useState("");
  const [approvalText, setApprovalText] = useState("");
  const [defaultAuto, setDefaultAuto] = useState<string[]>([]);
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async (dir: string) => {
    setLoading(true);
    setErr("");
    setMsg("");
    try {
      const p = await agents.getToolPolicy(dir);
      setAutoText(arrToLines(p.auto_commands));
      setApprovalText(arrToLines(p.approval_commands));
      setDefaultAuto(p.default_auto_commands || []);
      setIsDefault(p.is_default);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load("");
  }, [load]);

  const save = async () => {
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      await agents.setToolPolicy({
        project_dir: projectDir.trim(),
        auto_commands: linesToArr(autoText),
        approval_commands: linesToArr(approvalText),
      });
      setMsg("已保存，下次 loop 开始时生效");
      setIsDefault(false);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const resetToDefault = () => {
    setAutoText(arrToLines(defaultAuto));
    setApprovalText("");
    setMsg("已填入默认清单（gate.yaml），点击「保存」后生效");
  };

  const textareaCls =
    "w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs font-mono " +
    "placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30 resize-y";

  return (
    <section>
      <h3 className="flex items-center gap-2 text-sm font-medium mb-1">
        <ShieldCheck className="h-4 w-4 text-muted" />
        项目工具权限
        {!isDefault && (
          <span className="text-[10px] bg-primary/15 text-primary px-1.5 py-0.5 rounded-full">
            已自定义
          </span>
        )}
      </h3>
      <p className="text-[11px] text-muted mb-3">
        Agent 执行验证命令时的三态门控：自动执行 / 需人工同意 / 拒绝。配置按「用户 + 项目」保存。
      </p>

      <div className="space-y-4 rounded-xl border border-border/50 bg-surface/30 p-4">
        {/* 项目目录 */}
        <div>
          <label className="block text-xs font-medium text-muted mb-1">项目目录</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={projectDir}
              onChange={(e) => setProjectDir(e.target.value)}
              onBlur={() => load(projectDir.trim())}
              placeholder="项目的 project_dir（留空 = 全局默认）"
              className="flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-xs
                         placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
            <button
              onClick={() => load(projectDir.trim())}
              className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs text-muted
                         hover:text-foreground transition-colors cursor-pointer"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
              加载
            </button>
          </div>
        </div>

        {/* 第1层说明（写死） */}
        <div className="flex items-start gap-2 rounded-lg border border-error/30 bg-error/5 px-3 py-2">
          <AlertTriangle className="h-3.5 w-3.5 text-error shrink-0 mt-0.5" />
          <p className="text-[11px] text-muted leading-relaxed">
            <span className="text-error/90 font-medium">第 1 层 · 文件黑名单（写死，不可配置）</span>
            ：<code className="font-mono">.env</code> / <code className="font-mono">secrets/</code> /{" "}
            <code className="font-mono">payments/</code> / <code className="font-mono">terraform/</code> 等，
            命中即<strong className="text-error/90">硬拒并终止任务</strong>，无法人工放行。
          </p>
        </div>

        {/* 自动执行清单 */}
        <div>
          <label className="flex items-center gap-1.5 text-xs font-medium mb-1">
            <span className="inline-block h-2 w-2 rounded-full bg-success" />
            自动执行清单（每行一条命令前缀）
          </label>
          <textarea
            value={autoText}
            onChange={(e) => setAutoText(e.target.value)}
            rows={7}
            placeholder={"python -m pytest\nnpm test\ngit status"}
            className={textareaCls}
          />
          <p className="mt-1 text-[10px] text-muted/60">
            命中这些前缀的命令<strong>直接执行</strong>。默认来自 gate.yaml 的 allowed_commands。
          </p>
        </div>

        {/* 需人工同意清单 */}
        <div>
          <label className="flex items-center gap-1.5 text-xs font-medium mb-1">
            <span className="inline-block h-2 w-2 rounded-full bg-yellow-500" />
            需人工同意清单（每行一条命令前缀）
          </label>
          <textarea
            value={approvalText}
            onChange={(e) => setApprovalText(e.target.value)}
            rows={4}
            placeholder={"git push\nnpm run deploy"}
            className={textareaCls}
          />
          <p className="mt-1 text-[10px] text-muted/60">
            命中这些前缀的命令<strong>暂停等你确认</strong>后才能执行（优先级高于自动执行清单，可将原本自动的命令
            「降级」为需同意）。第 2 层的危险/非安全命令（如 <code className="font-mono">rm</code>、
            <code className="font-mono">curl</code>）以及未列入任何清单的命令，默认也走人工同意。
          </p>
        </div>

        {/* 操作 */}
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={save}
            disabled={saving || loading}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium
                       text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            保存
          </button>
          <button
            onClick={resetToDefault}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs text-muted
                       hover:text-foreground transition-colors cursor-pointer"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            恢复默认
          </button>
          {msg && <span className="text-[11px] text-success">{msg}</span>}
          {err && <span className="text-[11px] text-error">{err}</span>}
        </div>
      </div>
    </section>
  );
}
