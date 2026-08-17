import { describe, expect, it } from "vitest";
import { ApiError, DEFAULT_TIMEOUT_MS } from "./client";
import { BOOTSTRAP_TIMEOUT_MS } from "@/lib/bootstrapRetry";

describe("ApiError mapping", () => {
  it("maps 409 to a conflict without leaking internals", () => {
    const error = new ApiError(409, "This option is no longer available.", "conflict");
    expect(error.status).toBe(409);
    expect(error.message).not.toMatch(/traceback/i);
    expect(error.message).not.toMatch(/sqlalchemy/i);
  });

  it("keeps a longer bootstrap timeout than the default request timeout", () => {
    expect(DEFAULT_TIMEOUT_MS).toBe(25_000);
    expect(BOOTSTRAP_TIMEOUT_MS).toBe(60_000);
    expect(BOOTSTRAP_TIMEOUT_MS).toBeGreaterThan(DEFAULT_TIMEOUT_MS);
  });
});
