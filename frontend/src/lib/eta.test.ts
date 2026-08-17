import { describe, expect, it } from "vitest";
import { deriveEtaDisplay } from "./eta";
import type { ETAUpdate } from "@/api/types";

function row(partial: Partial<ETAUpdate> & Pick<ETAUpdate, "id" | "new_eta">): ETAUpdate {
  return {
    shipment_id: "ship-1",
    previous_eta: null,
    update_timestamp: "2026-08-13T18:00:00Z",
    source: "driver",
    reason: null,
    created_at: "2026-08-13T18:00:00Z",
    ...partial,
  };
}

describe("deriveEtaDisplay", () => {
  it("uses previous_eta from the latest row as the original ETA", () => {
    const history = [
      row({
        id: "1",
        source: "dispatch",
        new_eta: "2026-08-14T00:30:00Z",
        reason: "Original scheduled arrival",
      }),
      row({
        id: "2",
        previous_eta: "2026-08-14T00:30:00Z",
        new_eta: "2026-08-14T02:30:00Z",
        reason: "I will be 2 hours late",
      }),
    ];
    const display = deriveEtaDisplay(history);
    expect(display.originalEta).toBe("2026-08-14T00:30:00Z");
    expect(display.updatedEta).toBe("2026-08-14T02:30:00Z");
    expect(display.delayLabel).toBe("+2h");
  });

  it("falls back to dispatch ETA when previous_eta is missing", () => {
    const history = [
      row({
        id: "1",
        source: "dispatch",
        new_eta: "2026-08-14T00:30:00Z",
      }),
      row({
        id: "2",
        new_eta: "2026-08-14T02:30:00Z",
      }),
    ];
    const display = deriveEtaDisplay(history);
    expect(display.originalEta).toBe("2026-08-14T00:30:00Z");
    expect(display.updatedEta).toBe("2026-08-14T02:30:00Z");
  });
});
