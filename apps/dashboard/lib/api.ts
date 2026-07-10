// Thin client for core-api. In local/CI the `local`-profile Caddy maps
// /api/* → core-api; in production the base is configured per deployment.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

const TOKEN_KEY = "rpim_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

export async function api(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  // FormData bodies (multipart uploads) set their own boundary header —
  // forcing application/json would break them.
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_BASE}${path}`, { ...init, headers });
}

// Best-effort human-readable message from a FastAPI error body: `detail`
// is a string for HTTPException and a list of {msg, ...} for 422s.
export async function readErrorDetail(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    const detail: unknown = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (typeof item?.msg === "string" ? item.msg : ""))
        .filter(Boolean)
        .join(" · ");
    }
  } catch {
    // non-JSON body — fall through
  }
  return "";
}
