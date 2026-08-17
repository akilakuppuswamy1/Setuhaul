import { useState } from "react";
import { appointmentStatusLabel } from "@/lib/appointments";
import { formatDelay, formatTime, formatWindow } from "@/lib/format";
import { completedTimelineSteps, deriveStage, TIMELINE_STEPS } from "@/lib/timeline";
import { useOps } from "@/state/OpsProvider";
import type { PresentedOption } from "@/api/types";

export function DriverConsolePage() {
  const ops = useOps();
  const staleProposal = Boolean(ops.conflict) || ops.proposal?.status === "stale";
  const showConfirmedBooking =
    !staleProposal &&
    (ops.proposal?.status === "confirmed" || ops.currentAppointment?.status === "confirmed");
  const confirmedStart = ops.currentSlot?.start_time ?? ops.proposalSlot?.start_time;
  const confirmedEnd = ops.currentSlot?.end_time ?? ops.proposalSlot?.end_time;
  const showEscalation =
    ops.requiresHuman ||
    (ops.lastIntent === "ASK_OPTIONS" &&
      ops.options.length === 0 &&
      !ops.proposal &&
      !showConfirmedBooking);

  return (
    <div className="console">
      <div className="console-main">
        {showConfirmedBooking ? (
          <ConfirmationSummary
            key={ops.shipment?.id ?? "confirmed"}
            rescheduled={ops.rescheduled}
            windowLabel={formatWindow(confirmedStart, confirmedEnd, ops.timezone)}
            facilityName={ops.facility?.name}
            dockName={ops.proposalDock?.name}
          />
        ) : null}
      <section className="card conversation" aria-label="Driver conversation">
        <div className="card-pad" style={{ borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div className="kicker">Driver conversation</div>
            <strong>Operational assistant</strong>
          </div>
          <span className="badge info">Live API</span>
        </div>
        <div className="messages" role="log" aria-live="polite">
          {ops.messages.length === 0 && (
            <div className="empty">Start the hero flow from Demo Scenarios, or type a driver message.</div>
          )}
          {ops.messages.map((message) => (
            <article key={message.id} className={`bubble ${message.role}`}>
              <div className="bubble-text">{message.content}</div>
              <div className="msg-meta">
                {message.role === "driver" ? "Driver" : "Assistant"}
                {message.intent ? ` · ${message.intent}` : ""}
                {message.readOnlyStatus ? " · STATUS CHECK · read-only" : ""}
                {message.toolCalls?.length
                  ? ` · ${message.toolCalls.map((call) => call.name).join(", ")}`
                  : ""}
              </div>
            </article>
          ))}
          {ops.loading && (
            <div className="bubble assistant" aria-busy="true">
              {ops.loadingLabel ?? "Working…"}
            </div>
          )}

          {ops.lastIntent === "ASK_STATUS" && (
            <div className="option-grid">
              <div className="alert-card">
                <div className="kicker">Status check</div>
                <strong>Read-only</strong>
                <p className="wrap-text" style={{ margin: "8px 0 0", color: "var(--muted)" }}>
                  This turn used get_proposal or get_shipment_status. Accept / allocate were not requested by the UI.
                </p>
              </div>
            </div>
          )}

          {ops.options.length > 0 && ops.proposal?.status !== "confirmed" && (
            <div className="option-grid" aria-label="Feasible options from Step 5">
              <div className="kicker">Available options · showing is not booking</div>
              {ops.options.map((option) => (
                <OptionCard
                  key={`${option.slot_id}-${option.index}`}
                  option={option}
                  dockName={ops.docks.find((dock) => dock.id === option.dock_id)?.name}
                  timezone={ops.timezone}
                  selected={ops.selectedOptionIndex === option.index}
                  disabled={ops.loading || ops.proposal?.status === "proposed"}
                  onSelect={() => void ops.selectOption(option)}
                />
              ))}
            </div>
          )}

          {ops.proposal && ops.proposal.status === "proposed" && !ops.conflict && (
            <div className="option-grid">
              <div className="proposal-card">
                <div className="kicker">Proposed appointment</div>
                <strong>{formatWindow(ops.proposalSlot?.start_time, ops.proposalSlot?.end_time, ops.timezone)}</strong>
                <div>{ops.proposalDock?.name ?? "Dock assigned after proposal"}</div>
                <p className="wrap-text" style={{ color: "var(--muted)" }}>Status: Awaiting confirmation. Selecting did not book this slot.</p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button type="button" className="btn" onClick={() => void ops.confirmProposal()} disabled={ops.loading} aria-label="Confirm proposed appointment">
                    Confirm
                  </button>
                  <button type="button" className="btn secondary" onClick={() => void ops.rejectCurrentProposal()} disabled={ops.loading} aria-label="Reject proposed appointment">
                    Reject
                  </button>
                </div>
              </div>
            </div>
          )}

          {ops.confirming && (
            <div className="option-grid">
              <div className="alert-card">Revalidating through Step 7 → Step 5 → Step 6…</div>
            </div>
          )}

          {ops.conflict && (
            <div className="option-grid">
              <div className="alert-card" style={{ borderColor: "var(--danger)" }} data-testid="stale-conflict">
                <div className="kicker">Appointment no longer available</div>
                <p className="wrap-text">
                  That appointment is no longer available because another confirmation was completed first.
                </p>
                <p className="wrap-text" style={{ color: "var(--muted)" }}>
                  {ops.conflict.message}
                </p>
                <p className="wrap-text" style={{ color: "var(--muted)" }}>
                  The appointment was not confirmed for this request. No other slot was selected automatically.
                </p>
              </div>
            </div>
          )}

          {showEscalation && (
            <div className="option-grid conversation-followup" data-testid="human-escalation">
              <div className="alert-card">
                <div className="kicker">Human escalation recorded</div>
                <p className="wrap-text">Reason: {ops.escalationReason ?? "Human operations review requested."}</p>
                <p className="wrap-text" style={{ color: "var(--muted)" }}>
                  A human has not yet acted unless backend evidence says otherwise.
                </p>
              </div>
            </div>
          )}

          {ops.error && (
            <div className="option-grid">
              <div className="alert-card wrap-text" role="alert">
                {ops.error}
              </div>
            </div>
          )}
        </div>

        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            void ops.send();
          }}
        >
          <label className="sr-only" htmlFor="driver-message">
            Driver message
          </label>
          <textarea
            id="driver-message"
            value={ops.composer}
            onChange={(event) => ops.setComposer(event.target.value)}
            placeholder="Message the operations assistant…"
            disabled={!ops.driver || !ops.shipment || (ops.loading && ops.loadingLabel !== "Opening conversation…")}
          />
          <button type="submit" className="btn" disabled={ops.loading || !ops.composer.trim() || !ops.driver || !ops.shipment}>
            Send
          </button>
        </form>
      </section>
      </div>

      <aside className="ops-panel stack">
        <ShipmentCard />
        <AppointmentTimeCard />
        <EtaCard />
        <TimelineCard />
      </aside>
    </div>
  );
}

function ConfirmationSummary({
  rescheduled,
  windowLabel,
  facilityName,
  dockName,
}: {
  rescheduled: boolean;
  windowLabel: string;
  facilityName?: string;
  dockName?: string;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const details = [
    windowLabel ? `Window: ${windowLabel}` : null,
    facilityName ? `Facility: ${facilityName}` : null,
    dockName ? `Dock: ${dockName}` : null,
    "Status: Confirmed",
  ].filter((item): item is string => Boolean(item));
  return (
    <section
      className="card confirmation-summary"
      data-testid="confirmation-summary"
      aria-label="Appointment confirmation"
    >
      <div className="confirmation-summary-body">
        <div className="confirmation-summary-copy">
          <div className="kicker confirmation-kicker">
            <span className="confirmation-check" aria-hidden="true">
              ✓
            </span>
            {rescheduled ? "Appointment confirmed / rescheduled" : "Appointment confirmed"}
          </div>
          <strong className="confirmation-window">{windowLabel}</strong>
          <p className="confirmation-outcome">Your appointment is confirmed.</p>
          {facilityName ? <div className="confirmation-facility">{facilityName}</div> : null}
        </div>
        {details.length ? (
          <button
            type="button"
            className="confirmation-details-toggle"
            aria-expanded={detailsOpen}
            aria-controls="confirmation-verification"
            onClick={() => setDetailsOpen((open) => !open)}
          >
            {detailsOpen ? "Hide details ▴" : "Show details ▾"}
          </button>
        ) : null}
      </div>
      {detailsOpen ? (
        <div id="confirmation-verification" className="confirmation-details" data-testid="confirmation-details">
          <div className="kicker">Verification</div>
          <ul>
            {details.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function OptionCard({
  option,
  dockName,
  timezone,
  selected,
  disabled,
  onSelect,
}: {
  option: PresentedOption;
  dockName?: string;
  timezone?: string;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <div className={`option-card${selected ? " selected" : ""}`}>
      <div className="kicker">Option {option.index}</div>
      <strong>{formatWindow(option.start_time, option.end_time, timezone)}</strong>
      <div>{dockName ?? "Dock assigned after proposal"}</div>
      <div style={{ margin: "8px 0" }}>
        <span className="badge success">Feasible</span>
        <span className="badge neutral" style={{ marginLeft: 6 }}>
          Available
        </span>
      </div>
      <button type="button" className="btn secondary" onClick={onSelect} disabled={disabled} aria-label={`Select option ${option.index}`}>
        Select option
      </button>
    </div>
  );
}

function ShipmentCard() {
  const ops = useOps();
  const latestDriverEta = ops.etaHistory.at(-1);
  const originalLabel = ops.originalAppointment ? appointmentStatusLabel(ops.originalAppointment) : null;
  const currentLabel = ops.currentAppointment ? appointmentStatusLabel(ops.currentAppointment) : null;
  const showHistory =
    Boolean(ops.originalAppointment) &&
    ops.originalAppointment?.id !== ops.currentAppointment?.id;
  const orderedShipments = [...ops.shipments].sort((left, right) => {
    const leftDemo = left.shipment_number.startsWith("SHP-DEMO") ? 0 : 1;
    const rightDemo = right.shipment_number.startsWith("SHP-DEMO") ? 0 : 1;
    return leftDemo - rightDemo || left.shipment_number.localeCompare(right.shipment_number);
  });
  return (
    <section className="card card-pad">
      <div className="kicker">Shipment</div>
      {orderedShipments.length ? (
        <label className="shipment-bind">
          <span className="sr-only">Bound shipment</span>
          <select
            aria-label="Bound shipment"
            className="shipment-select"
            value={ops.shipment?.id ?? ""}
            onChange={(event) => {
              void ops.selectShipment(event.target.value);
            }}
          >
            {orderedShipments.map((item) => (
              <option key={item.id} value={item.id}>
                {item.shipment_number}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <h2 className="shipment-id">{ops.shipment?.shipment_number ?? "—"}</h2>
      )}
      <dl className="kv">
        <dt>Driver</dt>
        <dd>{ops.driver?.name ?? "—"}</dd>
        <dt>Facility</dt>
        <dd>{ops.facility?.name ?? "—"}</dd>
        <dt>Current ETA</dt>
        <dd>{formatTime(ops.latestEta, ops.timezone)}</dd>
        <dt>Appointment</dt>
        <dd>
          {formatWindow(
            ops.currentSlot?.start_time ?? ops.proposalSlot?.start_time ?? ops.originalSlot?.start_time,
            ops.currentSlot?.end_time ?? ops.proposalSlot?.end_time ?? ops.originalSlot?.end_time,
            ops.timezone,
          )}
        </dd>
        <dt>Status</dt>
        <dd>{currentLabel ?? originalLabel ?? "—"}</dd>
        {showHistory ? (
          <>
            <dt>Original</dt>
            <dd>
              {ops.originalSlot
                ? `${formatWindow(ops.originalSlot.start_time, ops.originalSlot.end_time, ops.timezone)} · ${originalLabel}`
                : originalLabel}
            </dd>
          </>
        ) : null}
        <dt>Exception</dt>
        <dd>
          {labelException(
            ops.exceptions.find((item) => item.status === "open" || item.status === "acknowledged")?.exception_type ??
              (ops.originalSlot && ops.latestEta && new Date(ops.latestEta).getTime() > new Date(ops.originalSlot.start_time).getTime()
                ? "delay"
                : null),
          )}
        </dd>
      </dl>
      {showHistory ? (
        <p className="wrap-text" style={{ color: "var(--muted)", marginBottom: 0 }}>
          Original remains visible as history. It is not a second current appointment.
        </p>
      ) : null}
      {latestDriverEta?.reason ? (
        <p className="wrap-text" style={{ color: "var(--muted)", marginBottom: 0 }}>
          Latest ETA reason: {latestDriverEta.reason}
        </p>
      ) : null}
    </section>
  );
}

function AppointmentTimeCard() {
  const ops = useOps();
  const start = ops.currentSlot?.start_time ?? ops.proposalSlot?.start_time ?? ops.originalSlot?.start_time;
  const end = ops.currentSlot?.end_time ?? ops.proposalSlot?.end_time ?? ops.originalSlot?.end_time;
  if (!start && !end) return null;
  const updatedAt = ops.currentAppointment?.updated_at ?? ops.etaHistory.at(-1)?.update_timestamp;
  return (
    <section className="card card-pad" data-testid="appointment-time-panel">
      <div className="kicker">Appointment time</div>
      <strong className="confirmation-window">{formatWindow(start, end, ops.timezone)}</strong>
      {updatedAt ? (
        <>
          <div className="kicker" style={{ marginTop: 10 }}>
            Last updated
          </div>
          <div>{formatTime(updatedAt, ops.timezone)}</div>
        </>
      ) : null}
    </section>
  );
}

function labelException(value?: string | null): string {
  if (!value) return "None";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function EtaCard() {
  const ops = useOps();
  const latest = ops.etaHistory.at(-1);
  const original = ops.originalSlot?.start_time ?? ops.etaHistory.find((item) => item.source === "dispatch")?.new_eta;
  if (!latest) {
    return (
      <section className="card card-pad">
        <div className="kicker">ETA</div>
        <p className="empty" style={{ padding: 0 }}>
          No ETA history from the backend yet.
        </p>
      </section>
    );
  }
  return (
    <section className="card card-pad">
      <div className="kicker">ETA / exception</div>
      <dl className="kv">
        <dt>Original appointment</dt>
        <dd>{formatTime(original, ops.timezone)}</dd>
        <dt>Updated ETA</dt>
        <dd>{formatTime(latest.new_eta, ops.timezone)}</dd>
        <dt>Delay</dt>
        <dd>{formatDelay(original, latest.new_eta) ?? "—"}</dd>
        <dt>Source</dt>
        <dd>{latest.source}</dd>
        <dt>Reason</dt>
        <dd>{latest.reason ?? "—"}</dd>
      </dl>
    </section>
  );
}

function TimelineCard() {
  const ops = useOps();
  const hasProposalRecord =
    Boolean(ops.proposal) ||
    ops.appointments.some((item) => (item.notes ?? "").includes("STEP7_PROPOSAL"));
  const stage = deriveStage({
    loading: ops.loading,
    loadingKind: ops.confirming ? "confirm" : null,
    hasEtaUpdate: ops.etaHistory.length > 1 || Boolean(ops.latestEta),
    hasException: ops.exceptions.length > 0,
    optionCount: ops.options.length,
    proposalStatus: ops.proposal?.status,
    intent: ops.lastIntent,
    conversationStatus: ops.lastStatus,
    conflict: Boolean(ops.conflict),
    escalated: ops.requiresHuman,
    appointmentStatus: ops.currentAppointment?.status ?? null,
    hasProposalRecord,
    rescheduled: ops.rescheduled,
  });
  const completed = completedTimelineSteps({
    hasException: ops.exceptions.length > 0,
    hasEtaUpdate: ops.etaHistory.length > 1 || Boolean(ops.latestEta),
    optionCount: ops.options.length,
    hasProposalRecord,
    proposalStatus: ops.proposal?.status,
    appointmentStatus: ops.currentAppointment?.status ?? null,
    rescheduled: ops.rescheduled,
  });
  return (
    <section className="card card-pad">
      <div className="kicker">Operational timeline</div>
      <div className="timeline">
        {TIMELINE_STEPS.map((step) => {
          const done = completed.includes(step.id);
          const current = step.id === stage;
          const label =
            step.id === "proposal_created" && ops.rescheduled
              ? "New appointment proposed"
              : step.id === "confirmed" && ops.rescheduled
                ? "New appointment confirmed"
                : step.label;
          return (
            <div key={step.id} className={`timeline-step${done ? " done" : ""}${current ? " current" : ""}`}>
              <span className="mark" />
              <span>{label}</span>
            </div>
          );
        })}
        {stage === "stale" && (
          <div className="timeline-step fail">
            <span className="mark" />
            <span>Stale / conflict</span>
          </div>
        )}
        {stage === "status_check" && (
          <div className="timeline-step current">
            <span className="mark" />
            <span>Status check · read-only</span>
          </div>
        )}
        {ops.rescheduled ? (
          <>
            <div className="timeline-step done">
              <span className="mark" />
              <span>Original appointment</span>
            </div>
            <div className="timeline-step done">
              <span className="mark" />
              <span>Reschedule</span>
            </div>
            {ops.originalAppointment ? (
              <div className="timeline-step done">
                <span className="mark" />
                <span>Original superseded</span>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
