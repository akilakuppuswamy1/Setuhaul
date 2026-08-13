import { describe, expect, it } from "vitest";
import { ApiError } from "./client";

describe("ApiError mapping", () => {
  it("maps 409 to a conflict without leaking internals", () => {
    const error = new ApiError(409, "This option is no longer available.", "conflict");
    expect(error.status).toBe(409);
    expect(error.message).not.toMatch(/traceback/i);
    expect(error.message).not.toMatch(/sqlalchemy/i);
  });
});
