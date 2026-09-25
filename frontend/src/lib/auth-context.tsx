"use client";

import { createContext, useContext, useState, useEffect, useMemo, useCallback, type ReactNode } from "react";
import { auth as authApi, setTokens, clearTokens } from "@/lib/api";

interface AuthState {
  token: string | null;
  username: string | null;
  role: string | null;
  isAuthenticated: boolean;
  login: (username: string, token: string, refreshToken?: string, role?: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState>({
  token: null,
  username: null,
  role: null,
  isAuthenticated: false,
  login: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const savedToken = localStorage.getItem("orbit_token");
    const savedUser = localStorage.getItem("orbit_user");
    const savedRole = localStorage.getItem("orbit_role");
    if (savedToken) {
      setToken(savedToken);
      setUsername(savedUser);
      setRole(savedRole);
    }
    setMounted(true);
  }, []);

  const login = useCallback((user: string, t: string, refreshToken?: string, r?: string) => {
    // 令牌统一由 api 模块写入（access + refresh），避免各处漏存 refresh_token
    setTokens(t, refreshToken);
    localStorage.setItem("orbit_user", user);
    if (r) localStorage.setItem("orbit_role", r);
    else localStorage.removeItem("orbit_role");
    setToken(t);
    setUsername(user);
    setRole(r ?? null);
  }, []);

  const logout = useCallback(() => {
    // 通知后端立即撤销令牌（失败不阻塞本地清理）
    void authApi.logout();
    clearTokens();
    localStorage.removeItem("orbit_user");
    localStorage.removeItem("orbit_role");
    setToken(null);
    setUsername(null);
    setRole(null);
  }, []);

  const value = useMemo(() => ({
    token,
    username,
    role,
    isAuthenticated: !!token,
    login,
    logout,
  }), [token, username, role, login, logout]);

  if (!mounted) {
    return <>{children}</>;
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
