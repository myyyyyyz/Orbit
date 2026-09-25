"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { auth } from "@/lib/api";
import { motion } from "motion/react";
import { User, Lock, ArrowRight, Loader2, AlertCircle } from "lucide-react";

interface AuthFormProps {
  /** 匿名试用入口；不传则不显示 */
  onSkip?: () => void;
}

export function AuthForm({ onSkip }: AuthFormProps) {
  const { login } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const fn = isRegister ? auth.register : auth.login;
      const res = await fn(username, password);
      // 后端返回 access_token + refresh_token（refresh 用于到期自动续期）
      login(username, res.access_token, res.refresh_token, res.role);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-6 py-12">
      {/* 背景氛围：网格纹理 + 双色光斑 */}
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-[0.35]" aria-hidden />
      <div
        className="ambient-glow"
        style={{ width: 520, height: 520, top: -180, left: "50%", marginLeft: -260, background: "var(--primary)" }}
        aria-hidden
      />
      <div
        className="ambient-glow"
        style={{ width: 340, height: 340, bottom: -140, right: "12%", background: "var(--accent)", opacity: 0.22 }}
        aria-hidden
      />

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="relative w-full max-w-[400px]"
      >
        {/* 品牌区 */}
        <div className="mb-8 text-center">
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.05, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-2xl border border-border-strong
                       bg-surface-elevated ring-highlight"
            style={{ boxShadow: "var(--shadow-glow)" }}
          >
            <OrbitMark />
          </motion.div>

          <h1 className="text-[1.75rem] font-semibold leading-tight tracking-tight">
            <span className="text-gradient">Orbit</span>
          </h1>
          <p className="mt-2 text-sm text-muted">
            {isRegister ? "创建你的 AI Agent 工作空间" : "登录以继续你的工作"}
          </p>
        </div>

        {/* 表单卡片 */}
        <div className="glass ring-highlight rounded-2xl p-6 sm:p-7" style={{ boxShadow: "var(--shadow-lg)" }}>
          {/* 登录 / 注册 切换 */}
          <div
            className="mb-6 grid grid-cols-2 gap-1 rounded-lg border border-border bg-surface-sunken p-1"
            role="tablist"
          >
            {([false, true] as const).map((registerMode) => {
              const active = isRegister === registerMode;
              return (
                <button
                  key={String(registerMode)}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => {
                    setIsRegister(registerMode);
                    setError("");
                  }}
                  className={`relative rounded-md py-2 text-sm font-medium transition-colors duration-200 cursor-pointer
                    ${active ? "text-foreground" : "text-muted hover:text-foreground-muted"}`}
                >
                  {active && (
                    <motion.span
                      layoutId="auth-tab"
                      className="absolute inset-0 rounded-md border border-border-strong bg-surface-elevated"
                      transition={{ type: "spring", stiffness: 380, damping: 32 }}
                    />
                  )}
                  <span className="relative">{registerMode ? "注册" : "登录"}</span>
                </button>
              );
            })}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <Field
              id="username"
              label="用户名"
              icon={<User className="h-4 w-4" />}
              type="text"
              value={username}
              onChange={setUsername}
              placeholder="输入用户名"
              autoComplete="username"
            />

            <Field
              id="password"
              label="密码"
              icon={<Lock className="h-4 w-4" />}
              type="password"
              value={password}
              onChange={setPassword}
              placeholder={isRegister ? "至少 8 位字符" : "输入密码"}
              autoComplete={isRegister ? "new-password" : "current-password"}
            />

            {error && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                className="flex items-start gap-2 rounded-lg border border-error/25 bg-error-soft px-3 py-2.5"
                role="alert"
              >
                <AlertCircle className="mt-px h-4 w-4 shrink-0 text-error" />
                <p className="text-[0.8125rem] leading-relaxed text-error">{error}</p>
              </motion.div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="group flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5
                         text-sm font-medium text-white transition-all duration-200
                         hover:bg-primary-hover hover:shadow-[0_6px_20px_-6px_var(--primary-glow)]
                         active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-55
                         cursor-pointer"
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  处理中
                </>
              ) : (
                <>
                  {isRegister ? "创建账号" : "登录"}
                  <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
                </>
              )}
            </button>
          </form>

          {onSkip && (
            <>
              <div className="my-5 flex items-center gap-3">
                <span className="h-px flex-1 bg-border" />
                <span className="text-[0.6875rem] uppercase tracking-wider text-muted-subtle">或</span>
                <span className="h-px flex-1 bg-border" />
              </div>

              <button
                type="button"
                onClick={onSkip}
                className="w-full rounded-lg border border-border bg-transparent px-4 py-2.5 text-sm
                           text-foreground-muted transition-colors duration-200
                           hover:border-border-strong hover:bg-surface-elevated hover:text-foreground
                           cursor-pointer"
              >
                以访客身份试用
              </button>
              <p className="mt-3 text-center text-[0.6875rem] leading-relaxed text-muted-subtle">
                访客模式可体验知识检索与问答，
                <br />
                长期记忆与 Agent Loop 需登录后使用
              </p>
            </>
          )}
        </div>
      </motion.div>
    </div>
  );
}

/* ── 带图标的输入字段 ── */

function Field({
  id,
  label,
  icon,
  type,
  value,
  onChange,
  placeholder,
  autoComplete,
}: {
  id: string;
  label: string;
  icon: React.ReactNode;
  type: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  autoComplete: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-[0.8125rem] font-medium text-foreground-muted">
        {label}
      </label>
      <div className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-subtle">
          {icon}
        </span>
        <input
          id={id}
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
          placeholder={placeholder}
          autoComplete={autoComplete}
          className="w-full rounded-lg border border-border bg-surface-sunken py-2.5 pl-10 pr-3.5 text-sm
                     transition-all duration-200 placeholder:text-muted-subtle
                     hover:border-border-strong
                     focus:border-primary/60 focus:bg-surface focus:outline-none
                     focus:ring-[3px] focus:ring-primary-soft"
        />
      </div>
    </div>
  );
}

/* ── 品牌标识：轨道环绕 ── */

function OrbitMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden>
      {/* 外轨道 */}
      <ellipse
        cx="13"
        cy="13"
        rx="11"
        ry="5.5"
        stroke="var(--primary)"
        strokeWidth="1.4"
        opacity="0.75"
        transform="rotate(-28 13 13)"
      />
      {/* 内核 */}
      <circle cx="13" cy="13" r="3.6" fill="var(--primary)" />
      {/* 卫星 */}
      <circle cx="22.2" cy="8.4" r="2" fill="var(--accent)" />
    </svg>
  );
}
