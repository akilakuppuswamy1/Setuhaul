import { describe, expect, it } from "vitest";
import { deriveStage, completedTimelineSteps } from "./timeline";

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

  it("marks confirmed from persisted appointment state after reload", () => {
    expect(
      deriveStage({
        appointmentStatus: "confirmed",
        hasEtaUpdate: true,
        optionCount: 0,
        proposalStatus: null,
      }),
    ).toBe("confirmed");
  });

  it("completes proposal and confirmation from persisted records without a live chat session", () => {
    expect(
      completedTimelineSteps({
        hasEtaUpdate: true,
        hasException: true,
        hasProposalRecord: true,
        appointmentStatus: "confirmed",
        optionCount: 0,
        proposalStatus: null,
      }),
    ).toEqual([
      "exception_reported",
      "eta_updated",
      "options_found",
      "proposal_created",
      "awaiting_confirmation",
      "confirmed",
    ]);
  });

  it("labels a superseded appointment as confirmed", () => {
    expect(deriveStage({ appointmentStatus: "confirmed", rescheduled: true })).toBe("confirmed");
  });
});
