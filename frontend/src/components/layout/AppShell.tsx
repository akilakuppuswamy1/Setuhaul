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
  const { healthOk, healthError, facility, driver, shipment } = useOps();
  const [open, setOpen] = useState(false);

  return (
    <div className="app-shell">
      <div className={`overlay${open ? " show" : ""}`} onClick={() => setOpen(false)} role="button" tabIndex={open ? 0 : -1} aria-label="Close menu" />
      <aside className={`sidebar${open ? " open" : ""}`}>
        <div>
          <div className="brand-mark">SETUHAUL</div>
          <div className="brand-sub">Intelligent Driver Operations</div>
        </div>
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
        <header className="topbar">
          <div className="topbar-context">
            <button type="button" className="btn secondary menu-btn" onClick={() => setOpen(true)} aria-label="Open menu">
              Menu
            </button>
            <div>
              <div className="kicker">Facility context</div>
              <strong>{facility?.name ?? "No facility loaded"}</strong>
            </div>
            <div>
              <div className="kicker">Driver</div>
              <strong>{driver?.name ?? "—"}</strong>
            </div>
            <div>
              <div className="kicker">Shipment</div>
              <strong>{shipment?.shipment_number ?? "—"}</strong>
            </div>
          </div>
          <div aria-live="polite" title={healthError ?? undefined}>
            <span className={`dot ${healthOk ? "ok" : "off"}`} />{" "}
            {healthOk ? "SetuHaul API online" : healthError ?? (healthOk === false ? "API offline" : "Checking API")}
          </div>
        </header>
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
