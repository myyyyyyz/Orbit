"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { auth } from "@/lib/api";
import { motion } from "motion/react";

export function AuthForm() {
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
      login(username, res.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="mx-auto max-w-sm px-6 pt-24"
    >
      <div className="text-center mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Orbit</h1>
        <p className="mt-2 text-sm text-muted">
          {isRegister ? "创建你的 AI Agent 工作空间" : "登录以继续"}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="username" className="block text-sm font-medium mb-1.5">
            用户名
          </label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            placeholder="输入用户名"
            className="w-full rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm
                       placeholder:text-muted/60 focus:outline-none focus:ring-2 focus:ring-primary/50
                       transition-[border-color,box-shadow] duration-200"
          />
        </div>

        <div>
          <label htmlFor="password" className="block text-sm font-medium mb-1.5">
            密码
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            placeholder="输入密码"
            className="w-full rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm
                       placeholder:text-muted/60 focus:outline-none focus:ring-2 focus:ring-primary/50
                       transition-[border-color,box-shadow] duration-200"
          />
        </div>

        {error && (
          <p className="text-sm text-error text-center">{error}</p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white
                     hover:bg-primary-hover active:scale-[0.98] transition-all duration-150
                     disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {loading ? "处理中..." : isRegister ? "注册" : "登录"}
        </button>

        <p className="text-center text-xs text-muted">
          {isRegister ? "已有账号？" : "没有账号？"}
          <button
            type="button"
            onClick={() => { setIsRegister(!isRegister); setError(""); }}
            className="ml-1 text-primary hover:underline cursor-pointer"
          >
            {isRegister ? "去登录" : "去注册"}
          </button>
        </p>
      </form>
    </motion.div>
  );
}
