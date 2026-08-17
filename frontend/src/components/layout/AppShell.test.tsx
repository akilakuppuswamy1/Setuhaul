import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

const retryBootstrap = vi.fn();
const ops = {
  healthOk: null as boolean | null,
  healthError: null as string | null,
  facility: null as { name: string } | null,
  driver: null as { name: string } | null,
  shipment: null as { id: string; shipment_number: string } | null,
  shipments: [] as Array<{ id: string; shipment_number: string }>,
  selectShipment: vi.fn(),
  connecting: true,
  connectionError: false,
  retryBootstrap,
};

vi.mock("@/state/OpsProvider", () => ({
  useOps: () => ops,
}));

describe("AppShell bootstrap status", () => {
  beforeEach(() => {
    ops.healthOk = null;
    ops.healthError = null;
    ops.facility = null;
    ops.driver = null;
    ops.shipment = null;
    ops.shipments = [];
    ops.connecting = true;
    ops.connectionError = false;
  });  it("shows a connecting state instead of an empty shipment dropdown", () => {
    render(
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("api-connection-status")).toHaveTextContent("Connecting to SetuHaul API...");
    expect(screen.queryByLabelText("Select shipment")).not.toBeInTheDocument();
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
  });

  it("shows retry when the API is temporarily unavailable and keeps prior shipments", () => {
    ops.connecting = false;
    ops.connectionError = true;
    ops.healthOk = true;
    ops.shipments = [{ id: "shp-1", shipment_number: "SHP-DEMO-001" }];
    ops.shipment = { id: "shp-1", shipment_number: "SHP-DEMO-001" };
    render(
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("api-connection-status")).toHaveTextContent(
      "SetuHaul API temporarily unavailable",
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByLabelText("Select shipment")).toHaveValue("shp-1");
  });
});
