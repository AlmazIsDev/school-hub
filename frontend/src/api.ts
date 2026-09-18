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

async function rawFetch(path: string, opts: RequestInit): Promise<Response> {
  const r = await fetch(base + path, {
    ...opts,
    headers: {
      // FormData выставляет свой multipart Content-Type с boundary — не трогаем
      ...(opts.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
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
      return rawFetch(path, opts);
    }
    setTokens(null);
  }
  return r;
}

async function unwrapError(r: Response): Promise<never> {
  throw new Error((await r.json().catch(() => ({})))?.detail ?? `HTTP ${r.status}`);
}

export async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await rawFetch(path, opts);
  if (!r.ok) return unwrapError(r);
  return r.json();
}

/** То же, что apiFetch, но возвращает blob (планы этажей — с Authorization, не по прямой ссылке). */
export async function apiBlob(path: string): Promise<Blob> {
  const r = await rawFetch(path, {});
  if (!r.ok) return unwrapError(r);
  return r.blob();
}

/** Декодирует payload JWT без проверки подписи — роль и id нужны только для UI. */
export function tokenPayload(token: string): { sub: string; role: string } {
  const payload = JSON.parse(atob(token.split(".")[1]));
  return { sub: payload.sub, role: payload.role };
}
