import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import { OpsProvider, useOps } from "./OpsProvider";

const {
  getHealth,
  listShipments,
  getShipment,
  getLatestEta,
  listShipmentEtaUpdates,
  listShipmentExceptions,
  listShipmentAppointments,
  getDriver,
  getFacility,
  listFacilityDocks,
  getProposal,
  getAppointmentSlot,
  getDock,
  createConversation,
  getChatThread,
  listChatMessages,
} = vi.hoisted(() => ({
  getHealth: vi.fn(),
  listShipments: vi.fn(),
  getShipment: vi.fn(),
  getLatestEta: vi.fn(),
  listShipmentEtaUpdates: vi.fn(),
  listShipmentExceptions: vi.fn(),
  listShipmentAppointments: vi.fn(),
  getDriver: vi.fn(),
  getFacility: vi.fn(),
  listFacilityDocks: vi.fn(),
  getProposal: vi.fn(),
  getAppointmentSlot: vi.fn(),
  getDock: vi.fn(),
  createConversation: vi.fn(),
  getChatThread: vi.fn(),
  listChatMessages: vi.fn(),
}));

vi.mock("@/lib/bootstrapRetry", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/bootstrapRetry")>();
  return {
    ...actual,
    retryBootstrap: (
      operation: () => Promise<unknown>,
      options?: { isCurrent?: () => boolean; delaysMs?: number[] },
    ) => actual.retryBootstrap(operation, { ...options, delaysMs: options?.delaysMs ?? [0, 0, 0] }),
  };
});

vi.mock("@/api", () => ({
  ApiError,
  getHealth,
  listShipments,
  getShipment,
  getLatestEta,
  listShipmentEtaUpdates,
  listShipmentExceptions,
  listShipmentAppointments,
  getDriver,
  getFacility,
  listFacilityDocks,
  getProposal,
  getAppointmentSlot,
  getDock,
  createConversation,
  getChatThread,
  listChatMessages,
  acceptProposal: vi.fn(),
  rejectProposal: vi.fn(),
  sendConversationMessage: vi.fn(),
}));

const demoShipment = {
  id: "shp-1",
  shipment_number: "SHP-DEMO-001",
  driver_id: "drv-1",
  destination_facility_id: "fac-1",
  is_active: true,
};

const confirmedAppointment = {
  id: "apt-1",
  shipment_id: "shp-1",
  status: "confirmed",
  appointment_slot_id: "slot-1",
  dock_id: "dock-1",
  notes: null,
  created_at: "2026-08-17T10:00:00Z",
  updated_at: "2026-08-17T10:00:00Z",
};

function Probe() {
  const ops = useOps();
  return (
    <div>
      <div data-testid="connecting">{String(ops.connecting)}</div>
      <div data-testid="connection-error">{String(ops.connectionError)}</div>
      <div data-testid="health-error">{ops.healthError ?? ""}</div>
      <div data-testid="shipments">{ops.shipments.map((item) => item.shipment_number).join(",")}</div>
      <div data-testid="selected">{ops.shipment?.shipment_number ?? ""}</div>
      <div data-testid="driver">{ops.driver?.name ?? ""}</div>
      <div data-testid="facility">{ops.facility?.name ?? ""}</div>
      <div data-testid="appointment">{ops.currentAppointment?.status ?? ""}</div>
      <div data-testid="thread">{ops.threadId ?? ""}</div>
      <div data-testid="composer-ready">{String(Boolean(ops.driver && ops.shipment && !ops.connecting))}</div>
      <button type="button" onClick={() => void ops.retryBootstrap()}>
        Retry
      </button>
    </div>
  );
}

function renderConsole() {
  return render(
    <OpsProvider>
      <Probe />
    </OpsProvider>,
  );
}

function mockHappyPath() {
  getHealth.mockResolvedValue({ status: "ok", service: "setuhaul" });
  listShipments.mockResolvedValue({ items: [demoShipment], page: 1, page_size: 100, total: 1 });
  getShipment.mockResolvedValue(demoShipment);
  getLatestEta.mockResolvedValue({ latest_eta: "2026-08-17T18:00:00Z" });
  listShipmentEtaUpdates.mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 });
  listShipmentExceptions.mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 });
  listShipmentAppointments.mockResolvedValue({
    items: [confirmedAppointment],
    page: 1,
    page_size: 50,
    total: 1,
  });
  getDriver.mockResolvedValue({ id: "drv-1", name: "Jane Rivera" });
  getFacility.mockResolvedValue({ id: "fac-1", name: "South Gate DC", timezone: "America/Chicago" });
  listFacilityDocks.mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 });
  getAppointmentSlot.mockResolvedValue({
    id: "slot-1",
    start_time: "2026-08-17T15:00:00Z",
    end_time: "2026-08-17T16:00:00Z",
  });
  getDock.mockResolvedValue({ id: "dock-1", name: "Dock A" });
  createConversation.mockResolvedValue({
    thread_id: "thread-1",
    driver_id: "drv-1",
    shipment_id: "shp-1",
    status: "ok",
  });
  getChatThread.mockResolvedValue({ id: "thread-1", shipment_id: "shp-1" });
  listChatMessages.mockResolvedValue({
    items: [
      {
        id: "msg-1",
        direction: "inbound",
        content: "Need a window",
        sent_at: "2026-08-17T10:00:00Z",
        metadata: {},
      },
    ],
    page: 1,
    page_size: 100,
    total: 1,
  });
}

describe("OpsProvider bootstrap reliability", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockHappyPath();
  });

  it("populates shipment binding after a fast API response", async () => {
    renderConsole();
    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("SHP-DEMO-001"));
    expect(screen.getByTestId("shipments")).toHaveTextContent("SHP-DEMO-001");
    expect(screen.getByTestId("driver")).toHaveTextContent("Jane Rivera");
    expect(screen.getByTestId("facility")).toHaveTextContent("South Gate DC");
    expect(screen.getByTestId("appointment")).toHaveTextContent("confirmed");
    expect(screen.getByTestId("connecting")).toHaveTextContent("false");
    expect(screen.getByTestId("connection-error")).toHaveTextContent("false");
    expect(screen.getByTestId("composer-ready")).toHaveTextContent("true");
    await waitFor(() => expect(screen.getByTestId("thread")).toHaveTextContent("thread-1"));
  });

  it("waits for a delayed shipment list instead of treating it as empty", async () => {
    listShipments.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () => resolve({ items: [demoShipment], page: 1, page_size: 100, total: 1 }),
            40,
          );
        }),
    );
    renderConsole();
    expect(screen.getByTestId("connecting")).toHaveTextContent("true");
    expect(screen.getByTestId("shipments")).toHaveTextContent("");
    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("SHP-DEMO-001"));
    expect(screen.getByTestId("connection-error")).toHaveTextContent("false");
  });

  it("retries after a timeout and then binds shipments", async () => {
    getHealth
      .mockRejectedValueOnce(new ApiError(408, "The request timed out.", "timeout"))
      .mockResolvedValue({ status: "ok", service: "setuhaul" });
    renderConsole();
    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("SHP-DEMO-001"));
    expect(getHealth).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("connection-error")).toHaveTextContent("false");
    expect(screen.getByTestId("shipments")).toHaveTextContent("SHP-DEMO-001");
  });

  it("keeps connectionError instead of an empty shipment dataset when the API is down", async () => {
    getHealth.mockRejectedValue(new ApiError(408, "The request timed out.", "timeout"));
    renderConsole();
    await waitFor(() => expect(screen.getByTestId("connection-error")).toHaveTextContent("true"));
    expect(screen.getByTestId("shipments")).toHaveTextContent("");
    expect(screen.getByTestId("connecting")).toHaveTextContent("false");
    expect(listShipments).not.toHaveBeenCalled();
  });

  it("repopulates the dropdown after the API comes back", async () => {
    getHealth.mockRejectedValue(new ApiError(0, "Unable to reach the SetuHaul API.", "network"));
    renderConsole();
    await waitFor(() => expect(screen.getByTestId("connection-error")).toHaveTextContent("true"));
    mockHappyPath();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("SHP-DEMO-001"));
    expect(screen.getByTestId("driver")).toHaveTextContent("Jane Rivera");
    expect(screen.getByTestId("connection-error")).toHaveTextContent("false");
  });

  it("does not let a stale timeout overwrite a successful bootstrap", async () => {
    let rejectFirst: ((error: unknown) => void) | undefined;
    getHealth.mockImplementationOnce(
      () =>
        new Promise((_, reject) => {
          rejectFirst = reject;
        }),
    );
    renderConsole();
    await waitFor(() => expect(getHealth).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("SHP-DEMO-001"));
    rejectFirst?.(new ApiError(408, "The request timed out.", "timeout"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.getByTestId("selected")).toHaveTextContent("SHP-DEMO-001");
    expect(screen.getByTestId("connection-error")).toHaveTextContent("false");
    expect(screen.getByTestId("shipments")).toHaveTextContent("SHP-DEMO-001");
  });
});
