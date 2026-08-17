import { describe, expect, it } from "vitest";
import type { Appointment } from "@/api/types";
import {
  appointmentStatusLabel,
  pickCurrentAppointment,
  pickOriginalAppointment,
} from "./appointments";

function row(partial: Partial<Appointment> & Pick<Appointment, "id" | "status">): Appointment {
  return {
    shipment_id: "ship-1",
    facility_id: "fac-1",
    appointment_slot_id: "slot-1",
    dock_id: null,
    notes: null,
    shipment_number: "SHP-DEMO-001",
    created_at: "2026-08-13T18:00:00Z",
    updated_at: "2026-08-13T18:00:00Z",
    ...partial,
  };
}

describe("appointment identifiers and history", () => {
  it("keeps a superseded original distinct from the current confirmed appointment", () => {
    const original = row({
      id: "old",
      status: "cancelled",
      notes: "DEMO:RESCHEDULE original 6:30 PM\nsuperseded_by=new",
      created_at: "2026-08-13T17:00:00Z",
    });
    const current = row({
      id: "new",
      status: "confirmed",
      notes: "",
      created_at: "2026-08-13T20:00:00Z",
      appointment_slot_id: "slot-2",
    });
    const appointments = [original, current];
    expect(pickOriginalAppointment(appointments)?.id).toBe("old");
    expect(pickCurrentAppointment(appointments)?.id).toBe("new");
    expect(appointmentStatusLabel(original)).toBe("Cancelled / Superseded");
    expect(appointmentStatusLabel(current)).toBe("Confirmed");
  });

  it("labels a live proposal as Proposed rather than Confirmed", () => {
    const proposed = row({
      id: "prop",
      status: "requested",
      notes: "STEP7_PROPOSAL\nCreated via conversational proposal tool",
    });
    expect(appointmentStatusLabel(proposed)).toBe("Proposed");
    expect(pickCurrentAppointment([proposed])).toBeUndefined();
  });
});
