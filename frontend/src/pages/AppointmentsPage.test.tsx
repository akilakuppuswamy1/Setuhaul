import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppointmentsPage } from "./AppointmentsPage";

const listAppointments = vi.fn();
const listShipments = vi.fn();
const listDrivers = vi.fn();
const listFacilities = vi.fn();
const getAppointmentSlot = vi.fn();
const getDock = vi.fn();

vi.mock("@/state/OpsProvider", () => ({
  useOps: () => ({
    facility: { id: "fac-1", name: "Chicago Cross-Dock", timezone: "America/Chicago" },
    timezone: "America/Chicago",
  }),
}));

vi.mock("@/api", () => ({
  listAppointments: (...args: unknown[]) => listAppointments(...args),
  listShipments: (...args: unknown[]) => listShipments(...args),
  listDrivers: (...args: unknown[]) => listDrivers(...args),
  listFacilities: (...args: unknown[]) => listFacilities(...args),
  getAppointmentSlot: (...args: unknown[]) => getAppointmentSlot(...args),
  getDock: (...args: unknown[]) => getDock(...args),
}));

describe("Appointments table identifiers", () => {
  beforeEach(() => {
    listAppointments.mockResolvedValue({
      items: [
        {
          id: "8a31f000-0000-0000-0000-000000000001",
          shipment_id: "ship-1",
          shipment_number: "SHP-DEMO-001",
          facility_id: "fac-1",
          appointment_slot_id: "slot-1",
          dock_id: "dock-1",
          status: "confirmed",
          notes: "",
          created_at: "2026-08-13T20:00:00Z",
          updated_at: "2026-08-13T20:00:00Z",
        },
      ],
    });
    listShipments.mockResolvedValue({
      items: [{ id: "ship-1", shipment_number: "SHP-DEMO-001", driver_id: "drv-1" }],
    });
    listDrivers.mockResolvedValue({ items: [{ id: "drv-1", name: "Alex Driver" }] });
    listFacilities.mockResolvedValue({
      items: [{ id: "fac-1", name: "Chicago Cross-Dock", timezone: "America/Chicago" }],
    });
    getAppointmentSlot.mockResolvedValue({
      start_time: "2026-08-14T01:00:00Z",
      end_time: "2026-08-14T02:00:00Z",
    });
    getDock.mockResolvedValue({ name: "Dock A" });
  });

  it("shows shipment number, driver, facility, local time, and status instead of a truncated UUID as the primary id", async () => {
    render(<AppointmentsPage />);
    await waitFor(() => {
      expect(screen.getByText("SHP-DEMO-001")).toBeTruthy();
    });
    expect(screen.getByText("Alex Driver")).toBeTruthy();
    expect(screen.getAllByText("Chicago Cross-Dock").length).toBeGreaterThan(0);
    expect(screen.getByText(/8:00\sPM/)).toBeTruthy();
    expect(screen.getByText("Confirmed")).toBeTruthy();
    expect(screen.queryByText(/^8a31f\.\.\.$/)).toBeNull();
  });
});
