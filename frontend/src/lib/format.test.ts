import { describe, expect, it } from "vitest";
import { formatDelay, formatWindow, loadingCopy } from "./format";

describe("formatDelay", () => {
  it("renders a two-hour gap from backend timestamps", () => {
    expect(formatDelay("2026-08-13T23:30:00Z", "2026-08-14T01:30:00Z")).toBe("+2h");
  });
});

describe("formatWindow", () => {
  it("renders facility-local evening times instead of UTC clock labels", () => {
    const text = formatWindow("2026-08-14T00:30:00Z", "2026-08-14T01:30:00Z", "America/Chicago");
    expect(text).toMatch(/7:30\sPM/);
    expect(text).toMatch(/8:30\sPM/);
    expect(text).not.toMatch(/00:30/);
    expect(text).not.toMatch(/UTC/);
  });
});

describe("loadingCopy", () => {
  it("labels a status question as read-only", () => {
    expect(loadingCopy("Has it been confirmed?")).toMatch(/read-only/i);
  });
});
