import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import { isRetryableBootstrapError, retryBootstrap } from "./bootstrapRetry";

describe("bootstrap retry", () => {
  it("retries timeout then succeeds", async () => {
    const operation = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(408, "The request timed out.", "timeout"))
      .mockResolvedValueOnce("ok");

    await expect(retryBootstrap(operation, { delaysMs: [0, 0, 0] })).resolves.toBe("ok");
    expect(operation).toHaveBeenCalledTimes(2);
  });

  it("does not retry a wrong-host or validation failure", async () => {
    const operation = vi.fn().mockRejectedValue(new ApiError(400, "bad request", "http_400"));
    await expect(retryBootstrap(operation, { delaysMs: [0, 0, 0] })).rejects.toMatchObject({ status: 400 });
    expect(operation).toHaveBeenCalledTimes(1);
  });

  it("stops retrying once a newer bootstrap generation is active", async () => {
    let current = 1;
    const operation = vi.fn().mockRejectedValue(new ApiError(408, "The request timed out.", "timeout"));
    await expect(
      retryBootstrap(operation, {
        delaysMs: [0, 0, 0],
        isCurrent: () => current === 1,
      }),
    ).rejects.toMatchObject({ code: "timeout" });
    current = 2;
    expect(isRetryableBootstrapError(new ApiError(408, "The request timed out.", "timeout"))).toBe(true);
    expect(isRetryableBootstrapError(new ApiError(422, "invalid", "http_422"))).toBe(false);
  });
});
