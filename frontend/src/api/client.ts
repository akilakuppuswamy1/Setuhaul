export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, message: string, code = "http_error") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export const DEFAULT_TIMEOUT_MS = 25_000;

function baseUrl(): string {
  const value = import.meta.env.VITE_API_BASE_URL?.trim();
  return value && value.length > 0 ? value.replace(/\/$/, "") : "http://127.0.0.1:8010";
}

function humanMessage(status: number, detail: unknown): string {
  if (status === 409) {
    return extractDetail(detail) ?? "This option is no longer available.";
  }
  if (status === 404) {
    return extractDetail(detail) ?? "The requested record was not found.";
  }
  if (status === 400 || status === 422) {
    return extractDetail(detail) ?? "The request could not be processed.";
  }
  if (status >= 500) {
    return "The operations service is unavailable. Try again in a moment.";
  }
  return extractDetail(detail) ?? "Something went wrong.";
}

function extractDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return sanitize(detail);
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first === "object" && "msg" in first) {
      return sanitize(String((first as { msg: unknown }).msg));
    }
  }
  if (detail && typeof detail === "object" && "detail" in detail) {
    return extractDetail((detail as { detail: unknown }).detail);
  }
  return null;
}

function sanitize(text: string): string {
  const blocked = [/traceback/i, /sqlalchemy/i, /psycopg/i, /password/i, /api[_-]?key/i];
  if (blocked.some((pattern) => pattern.test(text))) {
    return "The operations service returned an error.";
  }
  return text.slice(0, 400);
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, headers, ...rest } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${baseUrl()}${path}`, {
      ...rest,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(rest.body ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
    });
    const text = await response.text();
    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text) as unknown;
      } catch {
        payload = { detail: text };
      }
    }
    if (!response.ok) {
      const detail =
        payload && typeof payload === "object" && "detail" in payload
          ? (payload as { detail: unknown }).detail
          : payload;
      const code = response.status === 409 ? "conflict" : `http_${response.status}`;
      throw new ApiError(response.status, humanMessage(response.status, detail), code);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (
      (error instanceof DOMException && error.name === "AbortError") ||
      (error instanceof Error && error.name === "AbortError")
    ) {
      throw new ApiError(408, "The request timed out.", "timeout");
    }
    throw new ApiError(0, "Unable to reach the SetuHaul API. Confirm the backend is running.", "network");
  } finally {
    clearTimeout(timer);
  }
}

export function getApiBaseUrl(): string {
  return baseUrl();
}
