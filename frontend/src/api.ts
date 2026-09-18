const base = import.meta.env.VITE_API_URL ?? "/api";

export type Tokens = { access: string; refresh: string };

let tokens: Tokens | null = JSON.parse(localStorage.getItem("tokens") ?? "null");

export function getTokens() {
  return tokens;
}

export function setTokens(t: Tokens | null) {
  tokens = t;
  if (t) localStorage.setItem("tokens", JSON.stringify(t));
  else localStorage.removeItem("tokens");
}

export async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(base + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(tokens ? { Authorization: `Bearer ${tokens.access}` } : {}),
      ...opts.headers,
    },
  });
  if (r.status === 401 && tokens) {
    const rr = await fetch(base + "/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh: tokens.refresh }),
    });
    if (rr.ok) {
      setTokens(await rr.json());
      return apiFetch<T>(path, opts);
    }
    setTokens(null);
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `HTTP ${r.status}`);
  return r.json();
}

/** То же, что apiFetch, но возвращает blob (планы этажей — с Authorization, не по прямой ссылке). */
export async function apiBlob(path: string): Promise<Blob> {
  const r = await fetch(base + path, {
    headers: tokens ? { Authorization: `Bearer ${tokens.access}` } : {},
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.blob();
}

/** Декодирует payload JWT без проверки подписи — роль и id нужны только для UI. */
export function tokenPayload(token: string): { sub: string; role: string } {
  const payload = JSON.parse(atob(token.split(".")[1]));
  return { sub: payload.sub, role: payload.role };
}
