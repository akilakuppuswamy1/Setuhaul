import { NavLink, Outlet } from "react-router-dom";
import { useState } from "react";
import { useOps } from "@/state/OpsProvider";

const LINKS = [
  { to: "/", label: "Driver Console" },
  { to: "/shipments", label: "Shipments" },
  { to: "/appointments", label: "Appointments" },
  { to: "/facility-schedule", label: "Facility Schedule" },
  { to: "/demo", label: "Demo Scenarios" },
  { to: "/concurrency", label: "Concurrency" },
];

export function AppShell() {
  const {
    healthOk,
    healthError,
    facility,
    driver,
    shipment,
    shipments,
    selectShipment,
    connecting,
    connectionError,
    retryBootstrap,
  } = useOps();
  const [open, setOpen] = useState(false);
  const orderedShipments = [...shipments].sort((left, right) => {
    const leftDemo = left.shipment_number.startsWith("SHP-DEMO") ? 0 : 1;
    const rightDemo = right.shipment_number.startsWith("SHP-DEMO") ? 0 : 1;
    return leftDemo - rightDemo || left.shipment_number.localeCompare(right.shipment_number);
  });
  const statusLabel = connecting
    ? "Connecting to SetuHaul API..."
    : connectionError
      ? "SetuHaul API temporarily unavailable"
      : healthOk
        ? "SetuHaul API online"
        : (healthError ?? (healthOk === false ? "API offline" : "Checking API"));
  const statusDot = connecting ? "wait" : connectionError ? "off" : healthOk ? "ok" : "off";

  return (
    <div className="app-shell">
      <div
        className={`overlay${open ? " show" : ""}`}
        onClick={() => setOpen(false)}
        role="button"
        tabIndex={open ? 0 : -1}
        aria-label="Close menu"
      />
      <header className="topbar">
        <button type="button" className="btn secondary menu-btn" onClick={() => setOpen(true)} aria-label="Open menu">
          Menu
        </button>
        <div className="brand">
          <div className="brand-mark">SETUHAUL</div>
          <div className="brand-sub">Intelligent Driver Operations</div>
        </div>
        <div className="topbar-context">
          <div className="context-item">
            <div className="kicker">Facility</div>
            <strong>{facility?.name ?? "No facility loaded"}</strong>
          </div>
          <div className="context-item">
            <div className="kicker">Driver</div>
            <strong>{driver?.name ?? "—"}</strong>
          </div>
          <div className="context-item">
            <div className="kicker">Shipment</div>
            {orderedShipments.length ? (
              <select
                aria-label="Select shipment"
                className="shipment-select"
                value={shipment?.id ?? ""}
                onChange={(event) => {
                  void selectShipment(event.target.value);
                }}
              >
                {orderedShipments.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.shipment_number}
                  </option>
                ))}
              </select>
            ) : (
              <strong>
                {connecting
                  ? "Connecting…"
                  : connectionError
                    ? "Unavailable"
                    : (shipment?.shipment_number ?? "—")}
              </strong>
            )}
          </div>
        </div>
        <div className="topbar-status" aria-live="polite" title={healthError ?? undefined} data-testid="api-connection-status">
          <span className={`dot ${statusDot}`} />
          <span className="topbar-status-label">{statusLabel}</span>
          {connectionError && !connecting ? (
            <button type="button" className="btn secondary" onClick={() => void retryBootstrap()}>
              Retry
            </button>
          ) : null}
        </div>
      </header>
      <aside className={`sidebar${open ? " open" : ""}`}>
        <nav className="nav" aria-label="Primary">
          {LINKS.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.to === "/"} onClick={() => setOpen(false)}>
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">Classroom / demo context. No authentication.</div>
      </aside>
      <div className="workspace">
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
