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
  setActiveSchool(null);
}

/** Активная школа superadmin'а - бэкенд подставляет её как school_id (X-School-Id). */
export function getActiveSchool(): string | null {
  return localStorage.getItem("active_school");
}

export function setActiveSchool(id: string | null) {
  if (id) localStorage.setItem("active_school", id);
  else localStorage.removeItem("active_school");
}

export type Impersonator = { tokens: Tokens; name: string };

/** Чей аккаунт мы «заняли» - чтобы кнопка «Вернуться» переживала F5. */
export function getImpersonator(): Impersonator | null {
  try {
    const v = JSON.parse(localStorage.getItem("impersonator") ?? "null");
    return v && v.tokens?.access ? v : null;
  } catch {
    return null;
  }
}

/** Зайти как target: своп токенов, сессия админа сохраняется для «Вернуться». */
export function startImpersonation(targetTokens: Tokens, impersonator: Impersonator) {
  localStorage.setItem("impersonator", JSON.stringify(impersonator));
  setTokens(targetTokens);
}

export function stopImpersonation() {
  const imp = getImpersonator();
  localStorage.removeItem("impersonator");
  if (imp) setTokens(imp.tokens);
}

async function rawFetch(path: string, opts: RequestInit): Promise<Response> {
  const r = await fetch(base + path, {
    ...opts,
    headers: {
      // FormData выставляет свой multipart Content-Type с boundary - не трогаем
      ...(opts.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(tokens ? { Authorization: `Bearer ${tokens.access}` } : {}),
      ...(getActiveSchool() ? { "X-School-Id": getActiveSchool()! } : {}),
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
  const detail = (await r.json().catch(() => ({})))?.detail;
  // pydantic 422 отдаёт detail массивом ошибок - склеиваем в читаемый список
  const msg = Array.isArray(detail)
    ? detail.map((e: { msg?: string }) => e.msg ?? JSON.stringify(e)).join("; ")
    : detail;
  throw new Error(msg || `HTTP ${r.status}`);
}

export async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await rawFetch(path, opts);
  if (!r.ok) return unwrapError(r);
  return r.json();
}

/** То же, что apiFetch, но возвращает blob (планы этажей - с Authorization, не по прямой ссылке). */
export async function apiBlob(path: string): Promise<Blob> {
  const r = await rawFetch(path, {});
  if (!r.ok) return unwrapError(r);
  return r.blob();
}

/** Декодирует payload JWT без проверки подписи - роль и id нужны только для UI. */
export function tokenPayload(token: string): { sub: string; role: string } {
  const payload = JSON.parse(atob(token.split(".")[1]));
  return { sub: payload.sub, role: payload.role };
}
