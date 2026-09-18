import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { apiFetch, getTokens, setTokens, tokenPayload, type Tokens } from "./api";

type AuthState = {
  /** id и роль из access-токена; null если не залогинен */
  user: { id: string; role: string } | null;
  mustChangePassword: boolean;
  login: (login: string, password: string) => Promise<void>;
  logout: () => void;
  passwordChanged: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

/** Флаг храним рядом с tokens в localStorage, чтобы Guard переживал F5. */
function setMustChangeStored(v: boolean) {
  v ? localStorage.setItem("must_change_password", "1") : localStorage.removeItem("must_change_password");
}

function readMustChange(): boolean {
  return getTokens() !== null && localStorage.getItem("must_change_password") === "1";
}

function readUser(): { id: string; role: string } | null {
  const t = getTokens();
  if (!t) return null;
  try {
    const p = tokenPayload(t.access);
    return { id: p.sub, role: p.role };  // sub — строковый ObjectId
  } catch {
    setTokens(null);
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState(readUser);
  const [mustChangePassword, setMustChange] = useState(readMustChange);

  const login = useCallback(async (loginName: string, password: string) => {
    const res = await apiFetch<Tokens & { must_change_password: boolean }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ login: loginName, password }),
    });
    setTokens({ access: res.access, refresh: res.refresh });
    setMustChangeStored(res.must_change_password);
    setUser(readUser());
    setMustChange(res.must_change_password);
  }, []);

  const logout = useCallback(() => {
    setTokens(null);
    setMustChangeStored(false);
    setUser(null);
    setMustChange(false);
  }, []);

  const passwordChanged = useCallback(() => {
    setMustChangeStored(false);
    setMustChange(false);
  }, []);

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
