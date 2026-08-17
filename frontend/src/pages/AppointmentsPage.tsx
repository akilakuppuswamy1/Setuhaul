import { useEffect, useState } from "react";
import { getAppointmentSlot, getDock, listAppointments, listDrivers, listFacilities, listShipments } from "@/api";
import { ApiError } from "@/api/client";
import type { Appointment, Driver, Facility, Shipment } from "@/api/types";
import { appointmentStatusLabel, isProposalAppointment } from "@/lib/appointments";
import { formatWindow } from "@/lib/format";
import { useOps } from "@/state/OpsProvider";

interface Row extends Appointment {
  window?: string;
  dockName?: string;
  driverName?: string;
  facilityName?: string;
}

export function AppointmentsPage() {
  const { facility, timezone } = useOps();
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [page, shipments, drivers, facilities] = await Promise.all([
          listAppointments(facility ? { facility_id: facility.id } : {}),
          listShipments(),
          listDrivers(),
          listFacilities(),
        ]);
        const shipmentById = new Map<string, Shipment>(shipments.items.map((item) => [item.id, item]));
        const driverById = new Map<string, Driver>(drivers.items.map((item) => [item.id, item]));
        const facilityById = new Map<string, Facility>(facilities.items.map((item) => [item.id, item]));
        const enriched: Row[] = await Promise.all(
          page.items.map(async (item) => {
            const [slot, dock] = await Promise.all([
              item.appointment_slot_id ? getAppointmentSlot(item.appointment_slot_id) : Promise.resolve(null),
              item.dock_id ? getDock(item.dock_id) : Promise.resolve(null),
            ]);
            const shipment = shipmentById.get(item.shipment_id);
            const driver = shipment?.driver_id ? driverById.get(shipment.driver_id) : undefined;
            return {
              ...item,
              window: slot ? formatWindow(slot.start_time, slot.end_time, timezone ?? facility?.timezone) : undefined,
              dockName: dock?.name,
              driverName: driver?.name,
              facilityName: facilityById.get(item.facility_id)?.name,
            };
          }),
        );
        setRows(enriched);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Unable to load appointments.");
      }
    }
    void load();
  }, [facility, timezone]);

  return (
    <div>
      <h1 className="page-title">Appointments</h1>
      <p className="lede">
        Live GET /appointments for the bound facility. Operational identifiers are shown first; record UUIDs remain as
        secondary detail.
      </p>
      {error && <div className="alert-card" role="alert">{error}</div>}
      <div className="card table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Shipment number</th>
              <th>Driver</th>
              <th>Facility</th>
              <th>Appointment time</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} title={`Appointment ${row.id}`}>
                <td>
                  <div>{row.shipment_number ?? "—"}</div>
                  <div className="secondary-id">{row.shipment_id}</div>
                </td>
                <td>{row.driverName ?? "—"}</td>
                <td>{row.facilityName ?? "—"}</td>
                <td>{row.window ?? "—"}</td>
                <td>
                  <span
                    className={`badge ${
                      row.status === "confirmed"
                        ? "success"
                        : row.status === "requested"
                          ? isProposalAppointment(row)
                            ? "info"
                            : "warning"
                          : "neutral"
                    }`}
                  >
                    {appointmentStatusLabel(row)}
                  </span>
                  {row.dockName ? <div className="secondary-id">{row.dockName}</div> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
