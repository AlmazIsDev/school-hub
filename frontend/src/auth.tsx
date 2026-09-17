import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { apiFetch, getTokens, setTokens, tokenPayload, type Tokens } from "./api";

type AuthState = {
  /** id и роль из access-токена; null если не залогинен */
  user: { id: number; role: string } | null;
  mustChangePassword: boolean;
  login: (login: string, password: string) => Promise<void>;
  logout: () => void;
  passwordChanged: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

function readUser(): { id: number; role: string } | null {
  const t = getTokens();
  if (!t) return null;
  try {
    const p = tokenPayload(t.access);
    return { id: Number(p.sub), role: p.role };
  } catch {
    setTokens(null);
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState(readUser);
  const [mustChangePassword, setMustChange] = useState(false);

  const login = useCallback(async (loginName: string, password: string) => {
    const res = await apiFetch<Tokens & { must_change_password: boolean }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ login: loginName, password }),
    });
    setTokens({ access: res.access, refresh: res.refresh });
    setUser(readUser());
    setMustChange(res.must_change_password);
  }, []);

  const logout = useCallback(() => {
    setTokens(null);
    setUser(null);
    setMustChange(false);
  }, []);

  const passwordChanged = useCallback(() => setMustChange(false), []);

  const value = useMemo(
    () => ({ user, mustChangePassword, login, logout, passwordChanged }),
    [user, mustChangePassword, login, logout, passwordChanged],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth вне AuthProvider");
  return ctx;
}
