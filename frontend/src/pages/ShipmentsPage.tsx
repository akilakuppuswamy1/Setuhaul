import { useEffect, useState } from "react";
import { listShipments } from "@/api";
import type { Shipment } from "@/api/types";
import { ApiError } from "@/api/client";

export function ShipmentsPage() {
  const [items, setItems] = useState<Shipment[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listShipments()
      .then((page) => setItems(page.items))
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Unable to load shipments."));
  }, []);

  return (
    <div>
      <h1 className="page-title">Shipments</h1>
      <p className="lede">Live records from GET /shipments. Status values are backend facts.</p>
      {error && <div className="alert-card" role="alert">{error}</div>}
      <div className="card table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Shipment</th>
              <th>Origin</th>
              <th>Destination</th>
              <th>Status</th>
              <th>Active</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{item.shipment_number}</td>
                <td>{item.origin_location}</td>
                <td>{item.destination_location}</td>
                <td>
                  <span className="badge info">{item.status}</span>
                </td>
                <td>{item.is_active ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && !error ? <div className="empty">No shipments returned.</div> : null}
      </div>
    </div>
  );
}
