import { describe, expect, it } from "vitest";
import { deriveStage } from "./timeline";

describe("operational timeline", () => {
  it("never marks confirmed from options or a proposal alone", () => {
    expect(
      deriveStage({ optionCount: 2, proposalStatus: "proposed" }),
    ).toBe("awaiting_confirmation");
    expect(deriveStage({ optionCount: 2 })).toBe("options_found");
    expect(deriveStage({ proposalStatus: "confirmed" })).toBe("confirmed");
  });

  it("surfaces stale before success", () => {
    expect(deriveStage({ proposalStatus: "proposed", conflict: true })).toBe("stale");
  });
});
