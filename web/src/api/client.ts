// The one door to the API.
//
// In dev the Vite server proxies /api to http://localhost:8000 and strips the prefix; in the
// production image the API serves this build itself (WEB_DIST), so the same paths are reached with
// no prefix at all. Either way it is one origin, so the session cookie rides along untouched -
// `credentials: "include"` is set anyway so a split-origin deployment keeps working.

const DEFAULT_BASE = import.meta.env.DEV ? "/api" : "";

export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? DEFAULT_BASE).replace(/\/$/, "");

/** A URL on the API itself, for links the browser follows (sign-in, connect an account). */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export type Query = Record<string, string | number | boolean | null | undefined>;

/** Everything the API refused, with the body it refused with. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly body: unknown;

  constructor(status: number, detail: unknown, body: unknown) {
    super(ApiError.messageFor(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }

  private static messageFor(status: number, detail: unknown): string {
    if (typeof detail === "string" && detail) return detail;
    if (detail && typeof detail === "object") {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === "string" && message) return message;
    }
    return `Request failed (${status})`;
  }

  /** The structured detail a 409 carries: clashes, a rebuilt preview, the fresh tab. */
  get payload(): Record<string, unknown> {
    return this.detail && typeof this.detail === "object" && !Array.isArray(this.detail)
      ? (this.detail as Record<string, unknown>)
      : {};
  }

  get isAuth(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }
}

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(withQuery(path, query)), {
      method,
      credentials: "include",
      headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError(0, "The API is not reachable. Is it running on port 8000?", cause);
  }

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text) as unknown;
    } catch {
      parsed = text;
    }
  }

  if (!response.ok) {
    const detail =
      parsed && typeof parsed === "object" && "detail" in (parsed as object)
        ? (parsed as { detail: unknown }).detail
        : parsed;
    throw new ApiError(response.status, detail, parsed);
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, body ?? {}, query),
  patch: <T>(path: string, body: unknown, query?: Query) => request<T>("PATCH", path, body, query),
  del: <T>(path: string, query?: Query) => request<T>("DELETE", path, undefined, query),
};
