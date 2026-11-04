// Typed fetch wrapper for the FastAPI backend
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type QueryValue = string | number | boolean | null | undefined;

export function buildUrl(path: string, query?: Record<string, QueryValue>, base: string = API_BASE_URL): string {
  const url = new URL(base + (path.startsWith("/") ? path : `/${path}`));
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function parseError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
  }
  const error = (body as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null)
    ?.error;
  if (error?.message) {
    return new ApiError(response.status, error.code ?? "error", error.message, error.details ?? {});
  }
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (Array.isArray(detail)) {
    const message = detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
      .join("; ");
    return new ApiError(response.status, "validation_error", message);
  }
  return new ApiError(response.status, "http_error", `${response.status} ${response.statusText}`);
}

export async function request<T>(
  method: "GET" | "POST",
  path: string,
  options: { query?: Record<string, QueryValue>; body?: unknown; signal?: AbortSignal; fetchImpl?: typeof fetch } = {},
): Promise<T> {
  const fetchImpl = options.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetchImpl(buildUrl(path, options.query), {
      method,
      headers: options.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "network_error", `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`);
  }
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}
