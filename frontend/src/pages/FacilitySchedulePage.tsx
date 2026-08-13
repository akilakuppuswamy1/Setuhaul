import { useState } from "react";
import { evaluateFacilitySchedule, getAppointmentSlot, getDock } from "@/api";
import { ApiError } from "@/api/client";
import type { ScheduleAssignment, ScheduleEvaluateResponse } from "@/api/types";
import { formatWindow } from "@/lib/format";
import { useOps } from "@/state/OpsProvider";

interface DisplayRow extends ScheduleAssignment {
  window?: string;
  dockName?: string;
}

export function FacilitySchedulePage() {
  const { facility, timezone } = useOps();
  const [result, setResult] = useState<ScheduleEvaluateResponse | null>(null);
  const [rows, setRows] = useState<DisplayRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    if (!facility) {
      setError("No facility in current demo context.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await evaluateFacilitySchedule(facility.id);
      setResult(response);
      const enriched: DisplayRow[] = [];
      for (const item of response.proposed_assignments) {
        const slot = item.slot_id ? await getAppointmentSlot(item.slot_id) : null;
        const dock = item.dock_id ? await getDock(item.dock_id) : null;
        enriched.push({
          ...item,
          window: slot ? formatWindow(slot.start_time, slot.end_time, timezone) : undefined,
          dockName: dock?.name,
        });
      }
      setRows(enriched);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Schedule evaluation failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="kicker">Facility scheduling</div>
      <h1 className="page-title">{facility?.name ?? "Facility"}</h1>
      <p className="lede">
        Step 9 proposed ranking. Read-only. Does not reserve capacity. There is no confirm action on this page.
      </p>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <span className="badge warning">Read only</span>
        <span className="badge info">Proposed schedule</span>
        <span className="badge neutral">Does not reserve capacity</span>
      </div>
      <button type="button" className="btn" onClick={() => void run()} disabled={loading || !facility}>
        {loading ? "Evaluating…" : "Evaluate schedule"}
      </button>
      {error && (
        <div className="alert-card" role="alert" style={{ marginTop: 16 }}>
          {error}
        </div>
      )}
      {result && (
        <p className="lede" style={{ marginTop: 16 }}>
          Ranking policy: {result.ranking_policy}. Read-only: {String(result.read_only)}. Commits capacity:{" "}
          {String(result.commits_capacity)}.
        </p>
      )}
      <div className="card table-wrap" style={{ marginTop: 16 }}>
        <table className="data">
          <thead>
            <tr>
              <th>Shipment</th>
              <th>Proposed slot</th>
              <th>Dock</th>
              <th>Score</th>
              <th>Status</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.shipment_id}-${row.rank}`}>
                <td>{row.shipment_number}</td>
                <td>{row.window ?? "—"}</td>
                <td>{row.dockName ?? "—"}</td>
                <td>{row.score ?? "—"}</td>
                <td>
                  <span className="badge info">{row.kind}</span>
                </td>
                <td>{row.reasons.join("; ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {result && rows.length === 0 ? <div className="empty">No proposed assignments in this evaluation.</div> : null}
      </div>
      {result && result.unassigned_shipments.length > 0 && (
        <section className="card card-pad" style={{ marginTop: 16 }}>
          <div className="kicker">Unassigned</div>
          <ul>
            {result.unassigned_shipments.map((item) => (
              <li key={item.shipment_id}>
                {item.shipment_number}: {item.reason} — {item.detail}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
