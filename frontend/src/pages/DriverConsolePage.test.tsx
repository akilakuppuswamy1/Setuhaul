import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import "@/styles/global.css";
import { DriverConsolePage } from "./DriverConsolePage";

const send = vi.fn();
const setComposer = vi.fn();

const baseOps: any = {
  messages: [
    {
      id: "drv-1",
      role: "driver" as const,
      content: "Please get a dispatcher on this.",
      sentAt: "2026-08-16T10:00:00Z",
    },
    {
      id: "asst-1",
      role: "assistant" as const,
      content:
        "I cannot complete this from available options. A human operations reviewer has been requested and has not acted yet.",
      sentAt: "2026-08-16T10:00:01Z",
      intent: "HUMAN_ESCALATION",
      toolCalls: [{ name: "request_human_escalation", success: true }],
    },
  ],
  loading: false,
  loadingLabel: null,
  lastIntent: "HUMAN_ESCALATION",
  options: [],
  proposal: null,
  selectedOptionIndex: null,
  docks: [],
  timezone: "America/Chicago",
  confirming: false,
  conflict: null,
  requiresHuman: true,
  escalationReason:
    "No feasible dock window remains after ASK_OPTIONS → get_available_options; SupercalifragilisticexpialidociousEscalationReasonWithoutBreaks-and-a-very-long-operational-note",
  error: null,
  composer: "",
  setComposer,
  send,
  driver: { id: "d1", name: "Jordan Hale" },
  shipment: { id: "s1", shipment_number: "SH-1024" },
  etaHistory: [],
  latestEta: null,
  facility: { name: "South Gate DC", timezone: "America/Chicago" },
  originalSlot: null,
  originalAppointment: undefined,
  currentAppointment: undefined,
  currentSlot: null,
  rescheduled: false,
  appointments: [],
  shipments: [],
  selectShipment: vi.fn(),
  exceptions: [],
  proposalSlot: null,
  proposalDock: null,
  selectOption: vi.fn(),
  confirmProposal: vi.fn(),
  rejectCurrentProposal: vi.fn(),
  findNewOptions: vi.fn(),
};

vi.mock("@/state/OpsProvider", () => ({
  useOps: () => baseOps,
}));

describe("Driver Console human escalation layout", () => {
  beforeEach(() => {
    send.mockReset();
    setComposer.mockReset();
  });

  it("keeps the escalation card in the conversation scroll flow below the assistant reply", () => {
    render(<DriverConsolePage />);

    const log = screen.getByRole("log");
    const assistant = within(log).getByText(/human operations reviewer has been requested/i);
    const escalation = within(log).getByTestId("human-escalation");

    expect(assistant.compareDocumentPosition(escalation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(escalation).toHaveTextContent(/Human escalation recorded/i);
    expect(escalation).toHaveTextContent(baseOps.escalationReason);

    const composer = screen.getByLabelText("Driver message").closest("form");
    expect(composer).toBeTruthy();
    expect(log.contains(composer)).toBe(false);
    expect(log.compareDocumentPosition(composer!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("does not absolutely or fixedly position the escalation card over chat messages", () => {
    render(<DriverConsolePage />);

    const escalation = screen.getByTestId("human-escalation");
    const card = escalation.querySelector(".alert-card") as HTMLElement;
    const conversation = document.querySelector(".conversation") as HTMLElement;
    const messages = document.querySelector(".messages") as HTMLElement;
    const composer = document.querySelector(".composer") as HTMLElement;

    for (const node of [escalation, card, conversation, messages, composer]) {
      const position = getComputedStyle(node).position;
      expect(position).not.toBe("absolute");
      expect(position).not.toBe("fixed");
    }
  });

  it("wraps long escalation reasons inside the conversation column", () => {
    render(<DriverConsolePage />);

    const reason = screen.getByText(/No feasible dock window remains/i);
    expect(reason).toHaveClass("wrap-text");
    expect(reason.textContent).toContain("SupercalifragilisticexpialidociousEscalationReasonWithoutBreaks");

    const grid = screen.getByTestId("human-escalation");
    expect(grid).toHaveClass("option-grid");
    expect(grid.querySelector(".alert-card")).not.toBeNull();
    expect(grid.parentElement).toHaveClass("messages");
  });
});

describe("Driver Console stale / conflict representation", () => {
  afterEach(() => {
    baseOps.conflict = null;
    baseOps.proposal = null;
    baseOps.currentAppointment = undefined;
  });

  it("does not show a confirmed booking card for a 409 loser", () => {
    baseOps.conflict = new ApiError(409, "Proposal is stale: slot no longer available", "stale");
    baseOps.proposal = { status: "stale", message: "stale" };
    baseOps.currentAppointment = { status: "confirmed" };
    render(<DriverConsolePage />);
    expect(screen.queryByTestId("confirmation-summary")).toBeNull();
    expect(screen.getByTestId("stale-conflict")).toHaveTextContent(
      /another confirmation was completed first/i,
    );
    expect(screen.queryByRole("button", { name: /find new appointment options/i })).toBeNull();
  });

  it("does not auto-select another option after a conflict", () => {
    baseOps.conflict = new ApiError(409, "stale", "stale");
    baseOps.options = [];
    render(<DriverConsolePage />);
    expect(screen.queryByTestId("confirmation-summary")).toBeNull();
    expect(screen.queryByRole("button", { name: /select option/i })).toBeNull();
  });
});

describe("Driver Console proposal vs confirmation", () => {
  afterEach(() => {
    baseOps.proposal = null;
    baseOps.currentAppointment = undefined;
    baseOps.proposalSlot = null;
  });

  it("shows a proposed appointment without claiming it is confirmed", () => {
    baseOps.proposal = { status: "proposed", message: "Say confirm to book it." };
    baseOps.proposalSlot = { start_time: "2026-08-14T01:30:00Z", end_time: "2026-08-14T02:00:00Z" };
    render(<DriverConsolePage />);
    expect(screen.getByText(/Proposed appointment/i)).toBeTruthy();
    expect(screen.getAllByText(/Awaiting confirmation/i).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("confirmation-summary")).toBeNull();
  });
});

describe("Driver Console shipment context", () => {
  it("shows read-only shipment context without a card-level selector", () => {
    baseOps.shipments = [
      { id: "s1", shipment_number: "SHP-DEMO-001" },
      { id: "s2", shipment_number: "SHP-DEMO-NOCAP" },
    ];
    baseOps.shipment = { id: "s1", shipment_number: "SHP-DEMO-001" };
    baseOps.driver = { id: "d1", name: "Alex Driver" };
    baseOps.facility = { name: "Chicago Cross-Dock", timezone: "America/Chicago" };
    baseOps.latestEta = "2026-08-14T01:30:00Z";
    baseOps.currentAppointment = { id: "a1", status: "confirmed" };
    baseOps.currentSlot = { start_time: "2026-08-14T01:30:00Z", end_time: "2026-08-14T02:00:00Z" };
    render(<DriverConsolePage />);

    expect(screen.queryByLabelText("Bound shipment")).toBeNull();
    const card = screen.getByTestId("shipment-context-card");
    expect(within(card).getByRole("heading", { level: 2, name: "SHP-DEMO-001" })).toBeTruthy();
    expect(within(card).getByText("Alex Driver")).toBeTruthy();
    expect(within(card).getByText("Chicago Cross-Dock")).toBeTruthy();
    expect(within(card).getByText("Confirmed")).toBeTruthy();
    expect(within(card).getByText("None")).toBeTruthy();
  });
});

describe("Driver Console timeline persistence", () => {
  afterEach(() => {
    baseOps.currentAppointment = undefined;
    baseOps.appointments = [];
    baseOps.etaHistory = [];
    baseOps.exceptions = [];
    baseOps.proposal = null;
    baseOps.rescheduled = false;
    baseOps.latestEta = null;
    baseOps.originalAppointment = undefined;
  });

  it("marks appointment confirmed from persisted backend state without a live proposal card session", () => {
    baseOps.currentAppointment = { id: "a1", status: "confirmed", notes: "" };
    baseOps.appointments = [
      {
        id: "p1",
        status: "cancelled",
        notes: "STEP7_PROPOSAL",
        created_at: "2026-08-13T20:00:00Z",
        updated_at: "2026-08-13T20:10:00Z",
      },
      { id: "a1", status: "confirmed", notes: "", created_at: "2026-08-13T20:10:00Z", updated_at: "2026-08-13T20:10:00Z" },
    ];
    baseOps.etaHistory = [{ id: "e1", new_eta: "2026-08-14T01:30:00Z", source: "driver" }];
    baseOps.exceptions = [{ id: "x1", status: "open", exception_type: "delay" }];
    baseOps.latestEta = "2026-08-14T01:30:00Z";
    render(<DriverConsolePage />);
    expect(screen.getByTestId("confirmation-summary")).toBeTruthy();
    expect(screen.getByText("Exception reported")).toBeTruthy();
    expect(screen.getByText("ETA updated")).toBeTruthy();
  });

  it("represents a persisted reschedule as original superseded plus a new confirmed appointment", () => {
    baseOps.rescheduled = true;
    baseOps.originalAppointment = { id: "old", status: "cancelled", notes: "superseded_by=new" };
    baseOps.currentAppointment = { id: "new", status: "confirmed", notes: "" };
    baseOps.appointments = [baseOps.originalAppointment, baseOps.currentAppointment];
    render(<DriverConsolePage />);
    expect(screen.getByText("Original appointment")).toBeTruthy();
    expect(screen.getByText("Reschedule")).toBeTruthy();
    expect(screen.getByText("New appointment confirmed")).toBeTruthy();
    expect(screen.getByText("Original superseded")).toBeTruthy();
  });
});

describe("Driver Console option timezone", () => {
  afterEach(() => {
    baseOps.options = [];
  });

  it("renders option windows in the facility timezone, not UTC clock labels", () => {
    baseOps.options = [
      {
        index: 1,
        slot_id: "slot-1",
        dock_id: "dock-1",
        start_time: "2026-08-14T00:30:00Z",
        end_time: "2026-08-14T01:30:00Z",
      },
    ];
    baseOps.docks = [{ id: "dock-1", name: "Dock 1" }];
    render(<DriverConsolePage />);
    expect(screen.getByText(/7:30\sPM/)).toBeTruthy();
    expect(screen.queryByText(/00:30 UTC/)).toBeNull();
  });
});

describe("Driver Console confirmation summary placement", () => {
  afterEach(() => {
    baseOps.conflict = null;
    baseOps.proposal = null;
    baseOps.currentAppointment = undefined;
    baseOps.currentSlot = null;
    baseOps.proposalSlot = null;
    baseOps.originalSlot = null;
    baseOps.shipment = { id: "s1", shipment_number: "SH-1024" };
    baseOps.exceptions = [];
    baseOps.etaHistory = [];
    baseOps.latestEta = null;
    baseOps.rescheduled = false;
  });

  it("does not render a confirmation summary when the appointment is not confirmed", () => {
    baseOps.proposal = { status: "proposed" };
    baseOps.currentAppointment = { status: "requested" };
    render(<DriverConsolePage />);
    expect(screen.queryByTestId("confirmation-summary")).toBeNull();
    expect(screen.queryByText("Your appointment is confirmed.")).toBeNull();
  });

  it("places the confirmation summary above conversation and outside .messages", () => {
    baseOps.currentAppointment = { id: "a1", status: "confirmed", updated_at: "2026-08-14T01:21:00Z" };
    baseOps.currentSlot = { start_time: "2026-08-14T01:30:00Z", end_time: "2026-08-14T02:00:00Z" };
    render(<DriverConsolePage />);

    const summary = screen.getByTestId("confirmation-summary");
    const conversation = screen.getByLabelText("Driver conversation");
    const messages = document.querySelector(".messages") as HTMLElement;
    const composer = document.querySelector(".composer") as HTMLElement;

    expect(messages.contains(summary)).toBe(false);
    expect(summary.compareDocumentPosition(conversation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(summary.contains(composer)).toBe(false);
    expect(conversation.contains(composer)).toBe(true);
    expect(messages.contains(composer)).toBe(false);
    expect(summary).toHaveTextContent(/8:30\sPM/);
    expect(summary).toHaveTextContent(/9:00\sPM/);
    expect(screen.getByTestId("appointment-time-panel")).toHaveTextContent(/8:30\sPM/);
    expect(screen.getByText("Appointment").nextElementSibling).toHaveTextContent(/8:30\sPM/);
    expect(screen.getByText("Status").nextElementSibling).toHaveTextContent("Confirmed");
  });

  it("does not absolutely or fixedly position the confirmation summary over the composer", () => {
    baseOps.currentAppointment = { status: "confirmed" };
    baseOps.currentSlot = { start_time: "2026-08-14T01:30:00Z", end_time: "2026-08-14T02:00:00Z" };
    render(<DriverConsolePage />);

    const summary = screen.getByTestId("confirmation-summary");
    const conversation = document.querySelector(".conversation") as HTMLElement;
    const messages = document.querySelector(".messages") as HTMLElement;
    const composer = document.querySelector(".composer") as HTMLElement;
    const main = document.querySelector(".console-main") as HTMLElement;

    for (const node of [summary, conversation, messages, composer, main]) {
      const position = getComputedStyle(node).position;
      expect(position).not.toBe("absolute");
      expect(position).not.toBe("fixed");
    }
  });

  it("keeps verification details collapsed until Show details is clicked", () => {
    baseOps.currentAppointment = { status: "confirmed" };
    baseOps.currentSlot = { start_time: "2026-08-14T01:30:00Z", end_time: "2026-08-14T02:00:00Z" };
    render(<DriverConsolePage />);

    const summary = screen.getByTestId("confirmation-summary");
    expect(within(summary).queryByTestId("confirmation-details")).toBeNull();
    expect(within(summary).queryByText(/Feasibility checked/i)).toBeNull();
    expect(within(summary).queryByText(/Capacity checked/i)).toBeNull();
    expect(within(summary).queryByText(/Dock availability checked/i)).toBeNull();
    expect(within(summary).queryByText(/Appointment allocated/i)).toBeNull();
    expect(screen.queryByText(/Feasibility check/i)).toBeNull();
    expect(screen.queryByText(/Capacity check/i)).toBeNull();
    expect(screen.queryByText(/Dock check/i)).toBeNull();
    expect(screen.queryByText(/^Allocation$/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /show details/i }));
    const details = within(summary).getByTestId("confirmation-details");
    expect(details).toHaveTextContent(/8:30\sPM/);
    expect(details).toHaveTextContent(/Status: Confirmed/);
    expect(details).not.toHaveTextContent(/Feasibility engine/i);
    expect(details).not.toHaveTextContent(/proposal UUID/i);
    expect(details).not.toHaveTextContent(/appointment UUID/i);

    fireEvent.click(screen.getByRole("button", { name: /hide details/i }));
    expect(within(summary).queryByTestId("confirmation-details")).toBeNull();
  });

  it("hides the confirmation summary when switching to an unconfirmed shipment", () => {
    baseOps.shipment = { id: "s1", shipment_number: "SHP-DEMO-001" };
    baseOps.currentAppointment = { status: "confirmed" };
    baseOps.currentSlot = { start_time: "2026-08-14T01:30:00Z", end_time: "2026-08-14T02:00:00Z" };
    const { rerender } = render(<DriverConsolePage />);
    expect(screen.getByTestId("confirmation-summary")).toBeTruthy();

    baseOps.shipment = { id: "s2", shipment_number: "SHP-DEMO-002" };
    baseOps.currentAppointment = { status: "requested" };
    baseOps.proposal = null;
    baseOps.currentSlot = null;
    rerender(<DriverConsolePage />);
    expect(screen.queryByTestId("confirmation-summary")).toBeNull();
  });

  it("keeps confirmation layout from overflowing at stacked and desktop widths", () => {
    baseOps.currentAppointment = { status: "confirmed" };
    baseOps.currentSlot = { start_time: "2026-08-14T01:30:00Z", end_time: "2026-08-14T02:00:00Z" };
    render(<DriverConsolePage />);

    const consoleEl = document.querySelector(".console") as HTMLElement;
    const main = document.querySelector(".console-main") as HTMLElement;
    const summary = screen.getByTestId("confirmation-summary");
    const body = summary.querySelector(".confirmation-summary-body") as HTMLElement;
    const conversation = document.querySelector(".conversation") as HTMLElement;
    const composer = document.querySelector(".composer") as HTMLElement;

    expect(consoleEl.className).toContain("console");
    expect(main).toHaveClass("console-main");
    expect(summary).toHaveClass("confirmation-summary");
    expect(body).toHaveClass("confirmation-summary-body");
    expect(getComputedStyle(summary).position).not.toBe("absolute");
    expect(getComputedStyle(summary).position).not.toBe("fixed");
    expect(getComputedStyle(conversation).position).not.toBe("absolute");
    expect(getComputedStyle(composer).position).not.toBe("absolute");
  });
});
