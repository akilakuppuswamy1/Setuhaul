import { formatDelay, formatTime, formatWindow } from "@/lib/format";
import { deriveStage, TIMELINE_STEPS } from "@/lib/timeline";
import { useOps } from "@/state/OpsProvider";
import type { PresentedOption } from "@/api/types";

export function DriverConsolePage() {
  const ops = useOps();

  return (
    <div className="console">
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
              <div>{message.content}</div>
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
        </div>

        {ops.lastIntent === "ASK_STATUS" && (
          <div className="option-grid">
            <div className="alert-card">
              <div className="kicker">Status check</div>
              <strong>Read-only</strong>
              <p style={{ margin: "8px 0 0", color: "var(--muted)" }}>
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
              <p style={{ color: "var(--muted)" }}>Status: Awaiting confirmation. Selecting did not book this slot.</p>
              <div style={{ display: "flex", gap: 8 }}>
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

        {ops.proposal?.status === "confirmed" && (
          <div className="option-grid">
            <div className="proposal-card" style={{ borderColor: "var(--success)" }}>
              <div className="kicker">Appointment confirmed</div>
              <strong>{formatWindow(ops.proposalSlot?.start_time, ops.proposalSlot?.end_time, ops.timezone)}</strong>
              {ops.proposalDock?.name ? <div>{ops.proposalDock.name}</div> : null}
              <p>{ops.proposal.message}</p>
              <ul>
                <li>Feasibility check ✓</li>
                <li>Capacity check ✓</li>
                <li>Dock check ✓</li>
                <li>Allocation ✓</li>
              </ul>
              <small style={{ color: "var(--muted)" }}>Shown only after backend confirmation.</small>
            </div>
          </div>
        )}

        {ops.conflict && (
          <div className="option-grid">
            <div className="alert-card" style={{ borderColor: "var(--danger)" }}>
              <div className="kicker">Appointment no longer available</div>
              <p>{ops.conflict.message}</p>
              <p style={{ color: "var(--muted)" }}>This option became unavailable before confirmation.</p>
              <button type="button" className="btn" onClick={ops.findNewOptions} aria-label="Find new appointment options">
                Find new options
              </button>
            </div>
          </div>
        )}

        {ops.requiresHuman && (
          <div className="option-grid">
            <div className="alert-card">
              <div className="kicker">Human escalation recorded</div>
              <p>Reason: {ops.escalationReason ?? "Human operations review requested."}</p>
              <p style={{ color: "var(--muted)" }}>
                A human has not yet acted unless backend evidence says otherwise.
              </p>
            </div>
          </div>
        )}

        {ops.error && (
          <div className="option-grid">
            <div className="alert-card" role="alert">
              {ops.error}
            </div>
          </div>
        )}

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
            disabled={ops.loading || !ops.threadId}
          />
          <button type="submit" className="btn" disabled={ops.loading || !ops.composer.trim()}>
            Send
          </button>
        </form>
      </section>

      <aside className="stack">
        <ShipmentCard />
        <EtaCard />
        <TimelineCard />
      </aside>
    </div>
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
  return (
    <section className="card card-pad">
      <div className="kicker">Shipment</div>
      <h2 className="page-title" style={{ fontSize: 28 }}>{ops.shipment?.shipment_number ?? "—"}</h2>
      <dl className="kv">
        <dt>Driver</dt>
        <dd>{ops.driver?.name ?? "—"}</dd>
        <dt>Facility</dt>
        <dd>{ops.facility?.name ?? "—"}</dd>
        <dt>Current ETA</dt>
        <dd>{formatTime(ops.latestEta, ops.timezone)}</dd>
        <dt>Original appointment</dt>
        <dd>{ops.originalSlot ? formatTime(ops.originalSlot.start_time, ops.timezone) : "—"}</dd>
        <dt>Appointment status</dt>
        <dd>{ops.proposal?.status ?? ops.originalAppointment?.status ?? "—"}</dd>
        <dt>Active exception</dt>
        <dd>
          {ops.exceptions.find((item) => item.status === "open" || item.status === "acknowledged")?.exception_type ??
            "None"}
        </dd>
        <dt>Proposal status</dt>
        <dd>{ops.proposal?.status ?? "None"}</dd>
      </dl>
      {latestDriverEta?.reason ? (
        <p style={{ color: "var(--muted)", marginBottom: 0 }}>Latest ETA reason: {latestDriverEta.reason}</p>
      ) : null}
    </section>
  );
}

function EtaCard() {
  const ops = useOps();
  const latest = ops.etaHistory.at(-1);
  const original = ops.etaHistory[0]?.new_eta ?? latest?.previous_eta;
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
        <dt>Original ETA</dt>
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
  const stage = deriveStage({
    loading: ops.loading,
    loadingKind: ops.confirming ? "confirm" : null,
    hasEtaUpdate: ops.etaHistory.length > 1 || Boolean(ops.latestEta),
    optionCount: ops.options.length,
    proposalStatus: ops.proposal?.status,
    intent: ops.lastIntent,
    conversationStatus: ops.lastStatus,
    conflict: Boolean(ops.conflict),
    escalated: ops.requiresHuman,
  });
  const order = TIMELINE_STEPS.map((step) => step.id);
  const currentIndex = order.indexOf(stage as (typeof order)[number]);
  return (
    <section className="card card-pad">
      <div className="kicker">Operational timeline</div>
      <div className="timeline">
        {TIMELINE_STEPS.map((step, index) => {
          const done = currentIndex > index || stage === "confirmed";
          const current = step.id === stage;
          return (
            <div key={step.id} className={`timeline-step${done ? " done" : ""}${current ? " current" : ""}`}>
              <span className="mark" />
              <span>{step.label}</span>
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
      </div>
    </section>
  );
}
