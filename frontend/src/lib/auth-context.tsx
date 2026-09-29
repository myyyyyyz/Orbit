"use client";

import { createContext, useContext, useMemo, useCallback, type ReactNode } from "react";
import { auth as authApi, setTokens, clearTokens } from "@/lib/api";
import { useLocalString, setLocalValue, removeLocalValue } from "@/lib/local-storage";

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
  // 令牌/用户名/角色都住在 localStorage 里（外部数据源），用订阅读取而不是
  // 「effect 里读 + setState」——后者既违反 react-hooks/set-state-in-effect，
  // 又会在 api 层自动刷新令牌后与真实值失同步。
  const token = useLocalString("orbit_token");
  const username = useLocalString("orbit_user");
  const role = useLocalString("orbit_role");

  const login = useCallback((user: string, t: string, refreshToken?: string, r?: string) => {
    // 令牌统一由 api 模块写入（access + refresh），避免各处漏存 refresh_token
    setTokens(t, refreshToken);
    setLocalValue("orbit_user", user);
    if (r) setLocalValue("orbit_role", r);
    else removeLocalValue("orbit_role");
  }, []);

  const logout = useCallback(() => {
    // 通知后端立即撤销令牌（失败不阻塞本地清理）
    void authApi.logout();
    clearTokens();
    removeLocalValue("orbit_user");
    removeLocalValue("orbit_role");
  }, []);

  const value = useMemo(() => ({
    token,
    username,
    role,
    isAuthenticated: !!token,
    login,
    logout,
  }), [token, username, role, login, logout]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
