import { describe, expect, it } from "vitest";
import { formatDelay, loadingCopy } from "./format";

describe("formatDelay", () => {
  it("renders a two-hour gap from backend timestamps", () => {
    expect(formatDelay("2026-08-13T23:30:00Z", "2026-08-14T01:30:00Z")).toBe("+2h");
  });
});

describe("loadingCopy", () => {
  it("labels a status question as read-only", () => {
    expect(loadingCopy("Has it been confirmed?")).toMatch(/read-only/i);
  });
});
