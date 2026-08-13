import { useEffect, useState } from "react";
import { getAppointmentSlot, getDock, listAppointments } from "@/api";
import { ApiError } from "@/api/client";
import type { Appointment } from "@/api/types";
import { formatWindow } from "@/lib/format";
import { useOps } from "@/state/OpsProvider";

interface Row extends Appointment {
  window?: string;
  dockName?: string;
}

export function AppointmentsPage() {
  const { facility, timezone } = useOps();
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const page = await listAppointments(facility ? { facility_id: facility.id } : {});
        const enriched: Row[] = [];
        for (const item of page.items) {
          const slot = item.appointment_slot_id ? await getAppointmentSlot(item.appointment_slot_id) : null;
          const dock = item.dock_id ? await getDock(item.dock_id) : null;
          enriched.push({
            ...item,
            window: slot ? formatWindow(slot.start_time, slot.end_time, timezone) : undefined,
            dockName: dock?.name,
          });
        }
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
      <p className="lede">GET /appointments for the current facility. This page does not create or confirm bookings.</p>
      {error && <div className="alert-card" role="alert">{error}</div>}
      <div className="card table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Shipment ID</th>
              <th>Slot</th>
              <th>Dock</th>
              <th>Status</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.shipment_id.slice(0, 8)}</td>
                <td>{row.window ?? "—"}</td>
                <td>{row.dockName ?? "—"}</td>
                <td>
                  <span className={`badge ${row.status === "confirmed" ? "success" : row.status === "requested" ? "warning" : "neutral"}`}>
                    {row.status}
                  </span>
                </td>
                <td>{row.notes ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
