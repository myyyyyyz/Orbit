"use client";

import { createContext, useContext, useMemo, useCallback, type ReactNode } from "react";
import { auth as authApi, setTokens, clearTokens, type Collections } from "@/lib/api";
import { useLocalString, setLocalValue, removeLocalValue } from "@/lib/local-storage";

/** 当前会话所属组织（多租户）。来自注册/登录/加入组织的令牌响应。 */
export interface TenantInfo {
  id?: string | null;
  name?: string | null;
  /** 组织内角色：owner / admin / member */
  role?: string | null;
  invite_code?: string | null;
  collections?: Collections | null;
}

interface AuthState {
  token: string | null;
  username: string | null;
  role: string | null;
  tenant: TenantInfo | null;
  isAuthenticated: boolean;
  /**
   * 写入会话。tenant 传入时会一并持久化组织信息——
   * 注册/登录/加入组织三条路径都走这里，避免各自漏存。
   */
  login: (
    username: string,
    token: string,
    refreshToken?: string,
    role?: string,
    tenant?: TenantInfo | null
  ) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState>({
  token: null,
  username: null,
  role: null,
  tenant: null,
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
  const tenantRaw = useLocalString("orbit_tenant");

  const tenant = useMemo<TenantInfo | null>(() => {
    if (!tenantRaw) return null;
    try {
      return JSON.parse(tenantRaw) as TenantInfo;
    } catch {
      return null; // 损坏数据不应让整个应用崩掉
    }
  }, [tenantRaw]);

  const login = useCallback(
    (user: string, t: string, refreshToken?: string, r?: string, nextTenant?: TenantInfo | null) => {
      // 令牌统一由 api 模块写入（access + refresh），避免各处漏存 refresh_token
      setTokens(t, refreshToken);
      setLocalValue("orbit_user", user);
      if (r) setLocalValue("orbit_role", r);
      else removeLocalValue("orbit_role");
      if (nextTenant) setLocalValue("orbit_tenant", JSON.stringify(nextTenant));
      else removeLocalValue("orbit_tenant");
    },
    []
  );

  const logout = useCallback(() => {
    // 通知后端立即撤销令牌（失败不阻塞本地清理）
    void authApi.logout();
    clearTokens();
    removeLocalValue("orbit_user");
    removeLocalValue("orbit_role");
    removeLocalValue("orbit_tenant");
  }, []);

  const value = useMemo(() => ({
    token,
    username,
    role,
    tenant,
    isAuthenticated: !!token,
    login,
    logout,
  }), [token, username, role, tenant, login, logout]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
