"use client";

import { createContext, useContext, useState, useEffect, type ReactNode } from "react";

interface AuthState {
  token: string | null;
  username: string | null;
  isAuthenticated: boolean;
  login: (username: string, token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState>({
  token: null,
  username: null,
  isAuthenticated: false,
  login: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const savedToken = localStorage.getItem("orbit_token");
    const savedUser = localStorage.getItem("orbit_user");
    if (savedToken) {
      setToken(savedToken);
      setUsername(savedUser);
    }
    setMounted(true);
  }, []);

  const login = (user: string, t: string) => {
    localStorage.setItem("orbit_token", t);
    localStorage.setItem("orbit_user", user);
    setToken(t);
    setUsername(user);
  };

  const logout = () => {
    localStorage.removeItem("orbit_token");
    localStorage.removeItem("orbit_user");
    setToken(null);
    setUsername(null);
  };

  if (!mounted) {
    return <>{children}</>;
  }

  return (
    <AuthContext.Provider
      value={{
        token,
        username,
        isAuthenticated: !!token,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
