"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { CurrentUser, SystemInfo } from "./types";

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  system: SystemInfo | null;
  login: (email: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const booted = useRef(false);

  const loadSystem = useCallback(async () => {
    try {
      setSystem(await api<SystemInfo>("/api/v1/system/info"));
    } catch {
      setSystem(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const me = await api<CurrentUser>("/api/v1/auth/me");
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void loadSystem();
    void refresh();
    const onUnauthorized = () => setUser(null);
    window.addEventListener("aurora:unauthorized", onUnauthorized);
    return () => window.removeEventListener("aurora:unauthorized", onUnauthorized);
  }, [loadSystem, refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const me = await api<CurrentUser>("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
    });
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/api/v1/auth/logout", { method: "POST" });
    } catch {
      /* even if the request fails, clear the local session */
    }
    setUser(null);
  }, []);

  const can = useCallback(
    (permission: string) => Boolean(user?.permissions.includes(permission)),
    [user],
  );

  const value = useMemo(
    () => ({ user, loading, system, login, logout, refresh, can }),
    [user, loading, system, login, logout, refresh, can],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
