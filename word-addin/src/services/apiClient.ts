/**
 * Thin typed-JSON wrapper over `authenticatedFetch` (../taskpane/auth.ts).
 *
 * `authenticatedFetch` already handles bearer-token attachment, the
 * `/api/v1` path prefix, and single-flight 401-refresh-retry — it just
 * returns the raw `Response`. This module is additive to it (not a
 * replacement): every call site under `services/*Client.ts` would
 * otherwise duplicate `if (!res.ok) throw ...` / `res.json()` / typing.
 *
 * Deliberately smaller than the web app's `web/src/lib/lq-ai/api/client.ts`
 * — no pagination cursoring, no multipart helpers, no
 * PasswordChangeRequiredError-style specialization. Extend additively if
 * those become load-bearing here.
 */
import { authenticatedFetch } from "@/taskpane/auth";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Normalizes FastAPI's `{"detail": ...}` error envelope. `detail` may be
 *  a plain string, a structured `{code, message}` object, or (on 422) a
 *  Pydantic validation array — only the string/object shapes are common
 *  on the endpoints this client calls, so the array case falls back to
 *  the generic message below rather than being parsed in detail. */
function messageFor(body: unknown, status: number): { code: string; message: string } {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") {
    return { code: "error", message: detail };
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const d = detail as { code?: string; message?: string };
    return { code: d.code ?? "error", message: d.message ?? `Request failed (${status})` };
  }
  return { code: "error", message: `Request failed (${status})` };
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authenticatedFetch(path, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const { code, message } = messageFor(body, res.status);
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Returns the raw streaming `Response` for the caller to pipe into
 *  `../domain/chat.ts`'s `consumeMessageStream`. Only the pre-stream
 *  failure case (a non-2xx status before any bytes arrive) is normalized
 *  here — mid-stream failures arrive as an `error` SSE frame instead. */
export async function apiStreamRequest(path: string, init?: RequestInit): Promise<Response> {
  const res = await authenticatedFetch(path, {
    ...init,
    headers: { ...init?.headers, Accept: "text/event-stream" },
  });
  if (!res.ok) {
    throw new ApiError(res.status, "stream_failed", `Stream request failed (${res.status})`);
  }
  return res;
}
