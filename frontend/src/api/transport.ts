import { API_BASE, API_MODE } from "../config";
import { mockRequest } from "./mock";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export type Query = Record<string, string | number | undefined>;

/** Mock errors carry an HTTP status; make them the same ApiError live mode throws. */
function asApiError(e: unknown): never {
  const status = (e as { status?: unknown })?.status;
  throw typeof status === "number" && !(e instanceof ApiError) ? new ApiError(status, (e as Error).message) : e;
}

function withQuery(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== "") params.set(k, String(v));
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/** One function for every call. Mock and live differ only here. */
export async function http<T>(method: "GET" | "POST" | "PATCH" | "DELETE", path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
  const url = withQuery(path, opts.query);
  if (API_MODE === "mock") return mockRequest<T>(method, url, opts.body).catch(asApiError);
  const res = await fetch(API_BASE + url, {
    method,
    headers: opts.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  if (!res.ok) throw new ApiError(res.status, `${method} ${url} failed with ${res.status}`);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** A multipart upload (a receipt photo or PDF). */
export async function httpForm<T>(path: string, form: FormData, query?: Query): Promise<T> {
  const url = withQuery(path, query);
  if (API_MODE === "mock") {
    const fields: Record<string, string> = {};
    form.forEach((v, k) => { fields[k] = typeof v === "string" ? v : v.name; });
    return mockRequest<T>("POST", url, fields).catch(asApiError);
  }
  const res = await fetch(API_BASE + url, { method: "POST", body: form });
  if (!res.ok) throw new ApiError(res.status, `POST ${url} failed with ${res.status}`);
  return (await res.json()) as T;
}

/**
 * A call to an endpoint the backend has promised but may not serve yet (role 1 is adding them).
 * "Not there" (404, 405, 501) becomes null, so the screen can say so instead of failing.
 */
export async function optional<T>(call: Promise<T>): Promise<T | null> {
  try {
    return await call;
  } catch (e) {
    if (e instanceof ApiError && [404, 405, 501].includes(e.status)) return null;
    throw e;
  }
}
