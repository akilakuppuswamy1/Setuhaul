import { ApiError } from "@/api/client";

export const BOOTSTRAP_TIMEOUT_MS = 60_000;
export const BOOTSTRAP_RETRY_DELAYS_MS = [0, 2_000, 4_000];

export function isRetryableBootstrapError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  if (error.code === "timeout" || error.code === "network") return true;
  if (error.code === "wrong_host" || error.code === "empty_shipments" || error.code === "superseded") return false;
  if (error.status === 408 || error.status === 429) return true;
  if (error.status === 502 || error.status === 503 || error.status === 504) return true;
  return false;
}

export async function retryBootstrap<T>(
  operation: () => Promise<T>,
  options: { isCurrent?: () => boolean; delaysMs?: number[] } = {},
): Promise<T> {
  const delays = options.delaysMs ?? BOOTSTRAP_RETRY_DELAYS_MS;
  let lastError: unknown;
  for (let attempt = 0; attempt < delays.length; attempt += 1) {
    const waitMs = delays[attempt] ?? 0;
    if (waitMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }
    if (options.isCurrent && !options.isCurrent()) {
      throw lastError ?? new ApiError(0, "Bootstrap superseded.", "superseded");
    }
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      const hasRetryLeft = attempt < delays.length - 1;
      if (!hasRetryLeft || !isRetryableBootstrapError(error) || (options.isCurrent && !options.isCurrent())) {
        throw error;
      }
    }
  }
  throw lastError;
}
