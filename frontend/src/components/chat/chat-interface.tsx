"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Message, MessageItem } from "./message-item";
import { InputBox } from "./input-box";
import { AgentLoopCard, AgentStep } from "./agent-loop-card";
import { knowledge, agents, LoopEvent } from "@/lib/api";
import { PauseAllSwitch } from "./pause-all-switch";
import { LoopSettingsBar } from "./loop-settings-bar";
import { FileText, Search, Workflow } from "lucide-react";

interface LoopViewState {
  loopId: number;
  task: string;
  steps: AgentStep[];
  checkpoint: { title: string; options: string[]; kind?: string; commands?: { command: string; reason: string }[] } | null;
  finished: boolean;
  outcome: "done" | "failed" | null;   // Bug #12: 区分"完成/失败"（避免 failed 显示"已完成"）
  failInfo: { verdict: string; fail_reason: string; fix_direction: string } | null;
  expandedId: string | null;           // 受控展开：父组件直接控制避免 useEffect 时序
}

// 把后端事件流转为 AgentStep 列表（落地文档 §7.3 对话内卡片）
// 注意：事件可能因 SSE 回放 + getLoop 双源而重复，用 seq 去重（幂等）
function buildSteps(events: LoopEvent[]): AgentStep[] {
  const seen = new Set<number>();
  const steps: AgentStep[] = [];
  const stepByName = (name: string) => steps.find((s) => s.agent === name);

  const spawn = (name: string, model?: string) => {
    if (!stepByName(name)) {
      steps.push({ id: name, agent: name, status: "running", detail: "正在执行...", model });
    } else if (model) {
      // 已有步骤但模型信息更新（spawn 事件可能重复，幂等）
      const s = stepByName(name);
      if (s && !s.model) s.model = model;
    }
  };
  const complete = (name: string, detail: string, expanded?: AgentStep["expanded"]) => {
    const s = stepByName(name);
    if (s) {
      s.status = "completed";
      s.detail = detail;
      if (expanded) s.expanded = expanded;
    }
  };

  for (const ev of events) {
    // 去重：同一 seq 的事件只处理一次
    if (typeof ev.seq === "number" && seen.has(ev.seq)) continue;
    if (typeof ev.seq === "number") seen.add(ev.seq);

    const p = (ev.payload || {}) as Record<string, unknown>;
    switch (ev.event_type) {
      case "spawn": {
        // 后端 payload 可能为 {"agent": "planner"} 或平铺 "agent": "planner"
        const agent = (p.agent as string) || ev.agent;
        const model = (p.model as string) || undefined;
        if (agent && agent !== "loop" && agent !== "system") spawn(agent, model);
        break;
      }
      case "master_done":
        // Bug #15: Master 冷启动完成 → 标记 master 步骤 completed
        complete("master", "需求对齐完成");
        break;
      case "plan": {
        const stepsList = (p.steps as unknown[]) || [];
        complete("planner", `产出 ${stepsList.length} 步执行计划`, {
          type: "plan",
          title: "Planner 执行计划",
          content: JSON.stringify({ steps: p.steps, gates: p.gates }, null, 2),
        });
        spawn("builder");
        break;
      }
      case "builder_done": {
        const files = (p.changed_files as { path?: string }[]) || [];
        const apply = (p.apply as { applied?: number } | undefined);
        const summary = (p.summary as string) || "";
        complete("builder",
          summary || `产出 ${files.length} 个文件变更${typeof apply?.applied === "number" ? `（落盘 ${apply.applied}）` : ""}`,
          {
            type: "code",
            title: "Builder 变更清单",
            content: files.map((f) => `• ${f.path}`).join("\n") || "(无变更)",
          });
        spawn("reviewer");
        break;
      }
      case "retry": {
        const it = (p.iteration as number) || 1;
        const s = stepByName("reviewer");
        if (s) s.status = "pending";
        complete("builder", `根据 Reviewer 意见退回重试（第 ${it} 轮）`);
        const b = stepByName("builder");
        if (b) b.status = "running";
        break;
      }
      case "verdict": {
        const v = (p.verdict as string) || "";
        complete("reviewer", v, {
          type: "review",
          title: "Reviewer 验证结果",
          content: JSON.stringify({ verdict: v, fail_reason: p.fail_reason, stage_results: p.stage_results }, null, 2),
        });
        break;
      }
      case "error":
        // Bug #13a: 失败时同步更新 detail，避免显示"正在执行..."与 failed 状态矛盾
        steps.forEach((s) => {
          if (s.status === "running") {
            s.status = "failed";
            s.detail = "执行失败";
          }
        });
        break;
      case "done":
      case "checkpoint":
      case "user_decision":
        break;
    }
  }
  return steps;
}

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loopView, setLoopView] = useState<LoopViewState | null>(null);

  // P5: loop 运行配置（持久化到 localStorage）
  const [projectName, setProjectName] = useState(() => {
    if (typeof window === "undefined") return "";
    return localStorage.getItem("orbit_loop_project_name") || "";
  });
  const [projectDir, setProjectDir] = useState(() => {
    if (typeof window === "undefined") return "";
    return localStorage.getItem("orbit_loop_project_dir") || "";
  });
  const [loopMode, setLoopMode] = useState<"interactive" | "L1" | "L2">(() => {
    if (typeof window === "undefined") return "interactive";
    const v = localStorage.getItem("orbit_loop_mode");
    return v === "L1" || v === "L2" ? v : "interactive";
  });
  const [budgetLimit, setBudgetLimit] = useState(() => {
    if (typeof window === "undefined") return 100000;
    const v = parseInt(localStorage.getItem("orbit_loop_budget") || "100000", 10);
    return Number.isFinite(v) && v > 0 ? v : 100000;
  });
  const messageIdRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const loopAbortRef = useRef<AbortController | null>(null);
  // 事件累加器：用 ref 持久化，避免闭包过期导致增量状态丢失
  const loopEventsRef = useRef<LoopEvent[]>([]);
  // 当前活跃 loop id（setLoopView callback 用它判断，避免 React 18 batching 时序竞争）
  const activeLoopIdRef = useRef<number | null>(null);
  const sessionIdRef = useRef(`conv-${Date.now()}`);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  // 是否自动滚动到底部（用户上滑阅读时暂停自动滚动，避免打断阅读）
  const shouldAutoScrollRef = useRef(true);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    shouldAutoScrollRef.current = distFromBottom < 120;
  }, []);

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return;
    // 流式输出时用 auto 即时跟随，避免 smooth 动画堆积；非加载时平滑滚动
    messagesEndRef.current?.scrollIntoView({ behavior: isLoading ? "auto" : "smooth" });
  }, [messages.length, messages[messages.length - 1]?.content, loopView, isLoading]);

  // 组件卸载时 abort 进行中的请求
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      loopAbortRef.current?.abort();
    };
  }, []);

  // ── Agent Loop（P2）─────────────────────────────────────────

  const handleAgentLoop = useCallback(async (task: string) => {
    if (loopView) {
      setMessages((prev) => [...prev, {
        id: `msg-${++messageIdRef.current}`,
        role: "assistant",
        content: "当前已有进行中的 Agent Loop，请先等待它完成。",
        timestamp: Date.now(),
      }]);
      return;
    }

    const controller = new AbortController();
    loopAbortRef.current = controller;

    try {
      // P4: 读取 per-role 模型配置（orbit_llm_roles_v1），缺省不传（回退全局模型）
      let roleModels: Record<string, string> | undefined;
      try {
        const saved = localStorage.getItem("orbit_llm_roles_v1");
        if (saved) {
          const parsed = JSON.parse(saved) as Record<string, string>;
          if (Object.values(parsed).some(Boolean)) roleModels = parsed;
        }
      } catch { /* ignore */ }

      // P5: 使用用户配置的 project_name / mode / budget
      const inferredProjectName = projectName.trim() || undefined;
      const opts = {
        projectName: inferredProjectName,
        mode: loopMode,
        budgetLimit,
      };
      const { loop_id } = await agents.runLoop(sessionIdRef.current, task, projectDir.trim(), roleModels, opts);
      // 重置事件累加器
      loopEventsRef.current = [];
      // 存 loop_id 到 ref，setLoopView callback 用它判断（避免 React 18 batching 时序竞争）
      activeLoopIdRef.current = loop_id;
      setLoopView({ loopId: loop_id, task, steps: [], checkpoint: null, finished: false, outcome: null, failInfo: null, expandedId: null });

      await agents.streamLoop(loop_id, {
        onEvent: (ev: LoopEvent) => {
          // 已结束的 loop 不再更新 state
          if (activeLoopIdRef.current !== loop_id) return;
          loopEventsRef.current = [...loopEventsRef.current, ev];
          const newSteps = buildSteps(loopEventsRef.current);
          // plan 事件自动展开 planner（受控）
          const newExpanded = ev.event_type === "plan" ? "planner" : undefined;
          // Bug #12: loop_failed 事件记录失败详情，供 UI 区分"失败"而非"已完成"
          const isFailed = ev.event_type === "loop_failed";
          const failInfo = isFailed
            ? {
                verdict: (ev.payload.verdict as string) || "FAILED",
                fail_reason: (ev.payload.fail_reason as string) || "无具体原因",
                fix_direction: (ev.payload.fix_direction as string) || "",
              }
            : undefined;
          setLoopView((prev) => {
            // prev 可能是 null（首次 setLoopView 还没 commit）——此时用兜底值
            const base = prev ?? { loopId: loop_id, task, steps: [], checkpoint: null, finished: false, outcome: null, failInfo: null, expandedId: null };
            return {
              ...base,
              steps: newSteps,
              ...(newExpanded !== undefined ? { expandedId: newExpanded } : {}),
              ...(failInfo ? { failInfo, outcome: "failed" as const } : {}),
            };
          });
        },
        onCheckpoint: (title, options, payload) => {
          const cmds = Array.isArray(payload?.commands)
            ? (payload?.commands as { command: string; reason: string }[])
            : undefined;
          setLoopView((prev) => prev && prev.loopId === loop_id
            ? { ...prev, checkpoint: { title, options, kind: payload?.kind as string | undefined, commands: cmds } }
            : prev);
        },
        onDone: () => {
          setLoopView((prev) => prev && prev.loopId === loop_id
            ? { ...prev, checkpoint: null, finished: true, outcome: "done" }
            : prev);
        },
        onError: (msg) => {
          console.error("[Orbit] Loop error:", msg);
          setLoopView((prev) => prev && prev.loopId === loop_id
            ? {
                ...prev,
                checkpoint: null,
                finished: true,
                outcome: "failed",
                // Bug #13b: 无 loop_failed 详情时，用 error message 兜底填充
                failInfo: prev.failInfo ?? {
                  verdict: "ERROR",
                  fail_reason: msg,
                  fix_direction: "",
                },
              }
            : prev);
        },
      }, controller.signal);
    } catch (err) {
      console.error("[Orbit] Loop start error:", err);
      setMessages((prev) => [...prev, {
        id: `msg-${++messageIdRef.current}`,
        role: "assistant",
        content: `Agent Loop 启动失败: ${(err as Error).message}`,
        timestamp: Date.now(),
      }]);
      activeLoopIdRef.current = null;
      setLoopView(null);
    }
  }, [loopView, projectName, projectDir, loopMode, budgetLimit]);

  const handleSend = useCallback(async (content: string) => {
    const trimmed = content.trim();
    if (!trimmed) return;

    const userMsg: Message = {
      id: `msg-${++messageIdRef.current}`,
      role: "user",
      content: trimmed,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);

    // /loop 命令 → Agent Loop（落地文档 §7.4 显式触发）
    // 注：不用 /s flag（target < es2018），用 [\s\S] 匹配任意字符含换行
    const loopMatch = trimmed.match(/^\/loop\s+([\s\S]+)/);
    if (loopMatch) {
      handleAgentLoop(loopMatch[1].trim());
      return;
    }

    setIsLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;

    let assistantContent = "";

    const assistantMsg: Message = {
      id: `msg-${++messageIdRef.current}`,
      role: "assistant",
      content: "",
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, assistantMsg]);

    knowledge.streamAsk(
      trimmed,
      5,
      (token: string) => {
        assistantContent += token;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: assistantContent }
              : m
          )
        );
      },
      (model: string) => {
        console.log("[Orbit] Done with model:", model);
        setIsLoading(false);
      },
      (error: string) => {
        console.error("[Orbit] Stream error:", error);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: assistantContent || `错误: ${error}` }
              : m
          )
        );
        setIsLoading(false);
      },
      controller.signal
    );
  }, [handleAgentLoop]);

  const handleLoopDecision = useCallback(async (decision: string, note?: string) => {
    if (!loopView) return;
    try {
      await agents.decision(loopView.loopId, decision, note);
      setLoopView((prev) => prev ? { ...prev, checkpoint: null } : prev);
    } catch (err) {
      console.error("[Orbit] Loop decision error:", err);
      setMessages((prev) => [...prev, {
        id: `msg-${++messageIdRef.current}`,
        role: "assistant",
        content: `决策提交失败: ${(err as Error).message}`,
        timestamp: Date.now(),
      }]);
    }
  }, [loopView]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    loopAbortRef.current?.abort();
    setIsLoading(false);
  }, []);

  return (
    <div className="flex h-full flex-col">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto" ref={scrollContainerRef} onScroll={handleScroll}>
        {messages.length === 0 && !loopView ? (
          <div className="relative flex h-full items-center justify-center px-4">
            {/* 背景氛围光斑，避免大面积空白 */}
            <div
              className="ambient-glow"
              style={{
                width: 460,
                height: 300,
                top: "18%",
                left: "50%",
                marginLeft: -230,
                background: "var(--primary)",
                opacity: 0.16,
              }}
              aria-hidden
            />

            <div className="relative w-full max-w-lg text-center">
              <h1 className="mb-2.5 text-[1.625rem] font-semibold tracking-tight">
                有什么我可以帮助你的？
              </h1>
              <p className="mb-7 text-sm leading-relaxed text-muted">
                查询知识库、分析文档，或用{" "}
                <code className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[0.75rem] text-primary">
                  /loop
                </code>{" "}
                委派 Agent 执行任务
              </p>

              {/* 建议问题：卡片式，带图标与描述，比纯文字胶囊更有引导性 */}
              <div className="grid gap-2 text-left sm:grid-cols-3">
                {[
                  { q: "总结我上传的文档", icon: FileText, hint: "知识库检索" },
                  { q: "这个项目有哪些模块", icon: Search, hint: "语义问答" },
                  { q: "/loop 帮我规划一个新功能", icon: Workflow, hint: "Agent 编排" },
                ].map(({ q, icon: Icon, hint }) => (
                  <button
                    key={q}
                    onClick={() => handleSend(q)}
                    className="group flex flex-col gap-2 rounded-xl border border-border bg-surface/60 p-3
                               text-left transition-all duration-200
                               hover:-translate-y-0.5 hover:border-primary/40 hover:bg-surface
                               hover:shadow-[0_8px_20px_-10px_var(--primary-glow)]
                               cursor-pointer"
                  >
                    <span className="flex items-center gap-1.5 text-[0.625rem] uppercase tracking-wide text-muted-subtle">
                      <Icon className="h-3 w-3 transition-colors duration-200 group-hover:text-primary" />
                      {hint}
                    </span>
                    <span className="text-xs leading-relaxed text-foreground-muted transition-colors duration-200 group-hover:text-foreground">
                      {q}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="group">
            {messages.map((msg) => (
              <MessageItem key={msg.id} message={msg} />
            ))}

            {/* Agent Loop 卡片（对话内嵌，落地文档 §7.3） */}
            {loopView && (
              <div className="px-4 py-2 bg-primary/[0.03]">
                <div className="mx-auto max-w-3xl">
                  <AgentLoopCard
                    task={loopView.task}
                    steps={loopView.steps}
                    checkpoint={loopView.checkpoint}
                    finished={loopView.finished}
                    outcome={loopView.outcome}
                    failInfo={loopView.failInfo}
                    expandedId={loopView.expandedId}
                    onToggleExpand={(id) => setLoopView((prev) => prev ? { ...prev, expandedId: prev.expandedId === id ? null : id } : prev)}
                    onDecision={handleLoopDecision}
                  />
                </div>
              </div>
            )}

            {isLoading && messages[messages.length - 1]?.content === "" && (
              <div className="flex gap-3 px-4 py-5 bg-surface/50">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20">
                  <div className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                </div>
                <div className="flex items-center gap-1.5 py-1">
                  <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* P5: loop 运行配置 + 全局暂停开关（默认收起，点击展开编辑） */}
      <div className="border-t border-border bg-surface-sunken/60 px-4 py-2">
        <div className="mx-auto max-w-3xl">
          <LoopSettingsBar
            projectName={projectName}
            projectDir={projectDir}
            mode={loopMode}
            budgetLimit={budgetLimit}
            onProjectNameChange={(v) => { setProjectName(v); localStorage.setItem("orbit_loop_project_name", v); }}
            onProjectDirChange={(v) => { setProjectDir(v); localStorage.setItem("orbit_loop_project_dir", v); }}
            onModeChange={(v) => { setLoopMode(v); localStorage.setItem("orbit_loop_mode", v); }}
            onBudgetChange={(v) => { setBudgetLimit(v); localStorage.setItem("orbit_loop_budget", String(v)); }}
            actions={<PauseAllSwitch />}
          />
        </div>
      </div>

      {/* Input */}
      <InputBox
        onSend={handleSend}
        isLoading={isLoading}
        onStop={handleStop}
      />
    </div>
  );
}
