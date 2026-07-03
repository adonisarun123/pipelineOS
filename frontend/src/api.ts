import type { Auth } from "./types";

// Production: set VITE_API_BASE to the Django host (e.g. https://api.pipelineos.example)
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export function getAuth(): Auth | null {
  const raw = localStorage.getItem("auth");
  return raw ? (JSON.parse(raw) as Auth) : null;
}

export function setAuth(a: Auth | null): void {
  if (a) localStorage.setItem("auth", JSON.stringify(a));
  else localStorage.removeItem("auth");
}

export class ApiError extends Error {
  constructor(public status: number, public body: string) {
    super(`HTTP ${status}`);
  }
}

export async function api<T>(
  path: string,
  opts: { method?: string; body?: unknown } = {},
): Promise<T> {
  const auth = getAuth();
  const r = await fetch(`${BASE}/api/v1${path}`, {
    method: opts.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(auth ? { Authorization: `Token ${auth.token}` } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (r.status === 401) {
    setAuth(null);
    window.location.reload();
  }
  if (!r.ok) throw new ApiError(r.status, await r.text());
  return (await r.json()) as T;
}

export const inr = (v: string | number): string =>
  `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
