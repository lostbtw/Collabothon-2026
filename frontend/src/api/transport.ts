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

function withQuery(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== "") params.set(k, String(v));
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/** One function for every call. Mock and live differ only here. */
export async function http<T>(method: "GET" | "POST" | "PATCH", path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
  const url = withQuery(path, opts.query);
  if (API_MODE === "mock") return mockRequest<T>(method, url, opts.body);
  const res = await fetch(API_BASE + url, {
    method,
    headers: opts.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  if (!res.ok) throw new ApiError(res.status, `${method} ${url} failed with ${res.status}`);
  return (await res.json()) as T;
}
