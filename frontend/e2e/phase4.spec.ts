import { expect, test, type Page } from "@playwright/test";

const API = process.env.SETUHAUL_API_URL ?? "http://127.0.0.1:8010";
const RACE = "SHP-PHASE4-RACE-001";
const RESCHEDULE = "SHP-PHASE4-RESCHEDULE-001";
const NOCAP = "SHP-DEMO-NOCAP";
const VIEWPORTS = [
  { name: "1366x768", width: 1366, height: 768 },
  { name: "1440x900", width: 1440, height: 900 },
  { name: "768x1024", width: 768, height: 1024 },
  { name: "390x844", width: 390, height: 844 },
] as const;

async function api(path: string, init?: RequestInit) {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  return { status: response.status, payload };
}

async function shipmentByNumber(number: string) {
  const { payload } = await api("/shipments?page=1&page_size=100");
  const item = payload.items.find((row: { shipment_number: string }) => row.shipment_number === number);
  expect(item, `missing ${number}`).toBeTruthy();
  return item as { id: string; shipment_number: string; driver_id: string; destination_facility_id: string };
}

async function bindShipment(page: Page, shipmentNumber: string) {
  await page.goto("/");
  await expect(page.getByLabel("Bound shipment")).toBeVisible({ timeout: 30_000 });
  const select = page.getByLabel("Bound shipment");
  const value = await select.evaluate((el, number) => {
    const node = el as HTMLSelectElement;
    const option = [...node.options].find((item) => item.textContent?.trim() === number);
    return option?.value ?? "";
  }, shipmentNumber);
  expect(value, `missing shipment ${shipmentNumber}`).not.toBe("");
  await select.selectOption(value);
  await expect(page.getByLabel("Bound shipment")).toHaveValue(value);
  await expect(page.locator(".shipment-bind")).toContainText(shipmentNumber);
  await expect(page.locator("#driver-message")).toBeEnabled({ timeout: 45_000 });
}

async function sendDriver(page: Page, message: string) {
  const box = page.locator("#driver-message");
  await expect(box).toBeEnabled({ timeout: 30_000 });
  await box.fill(message);
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(message).first()).toBeVisible();
  await expect(page.locator(".bubble.assistant").last()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Working|Recording|Checking|Revalidating|Understanding|Creating/)).toHaveCount(0, {
    timeout: 60_000,
  });
}

async function noHorizontalOverflow(page: Page) {
  const metrics = await page.evaluate(() => {
    const root = document.documentElement;
    return { scrollWidth: root.scrollWidth, clientWidth: root.clientWidth };
  });
  expect(metrics.scrollWidth, JSON.stringify(metrics)).toBeLessThanOrEqual(metrics.clientWidth + 2);
}

async function pendingProposalId(shipmentId: string): Promise<string> {
  const { payload } = await api(`/shipments/${shipmentId}/appointments?page=1&page_size=50`);
  const pending = [...payload.items]
    .filter((row: { status: string; notes?: string | null }) => row.status === "requested" && (row.notes ?? "").includes("STEP7_PROPOSAL"))
    .sort((a: { created_at: string }, b: { created_at: string }) => b.created_at.localeCompare(a.created_at))[0];
  expect(pending, "pending proposal appointment").toBeTruthy();
  return pending.id as string;
}

test.describe.configure({ mode: "serial" });

test("health is live before browser flows", async () => {
  const { status, payload } = await api("/health");
  expect(status).toBe(200);
  expect(payload).toMatchObject({ status: "ok", service: "setuhaul" });
});

for (const viewport of VIEWPORTS) {
  test(`viewport ${viewport.name} has no overflow and keeps composer reachable`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/");
    await expect(page.getByLabel("Bound shipment")).toBeVisible({ timeout: 30_000 });
    if (viewport.width <= 760) {
      await page.getByRole("button", { name: "Open menu" }).click();
      await expect(page.getByRole("link", { name: "Appointments" })).toBeVisible();
      await page.getByRole("link", { name: "Driver Console" }).click();
    }
    await noHorizontalOverflow(page);
    await expect(page.locator("#driver-message")).toBeVisible();
    const composerBox = await page.locator(".composer").boundingBox();
    const logBox = await page.getByRole("log").boundingBox();
    expect(composerBox).toBeTruthy();
    expect(logBox).toBeTruthy();
    expect(composerBox!.y).toBeGreaterThanOrEqual(logBox!.y);
  });
}

test("shipment switching does not keep the previous conversation", async ({ page }) => {
  await bindShipment(page, RACE);
  await expect(page.getByText("Phase4 Race Driver").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Chicago Cross-Dock").first()).toBeVisible();
  await sendDriver(page, "Just checking in for the race shipment.");
  await expect(page.getByText("Just checking in for the race shipment.")).toBeVisible();

  await bindShipment(page, RESCHEDULE);
  await expect(page.getByText("Phase4 Reschedule Driver").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Just checking in for the race shipment.")).toHaveCount(0);
  await expect(page.getByText("Phase4 Race Driver")).toHaveCount(0);
});

test("no-capacity shipment escalates without a proposal card", async ({ page }) => {
  await bindShipment(page, NOCAP);
  await sendDriver(page, "What options do I have?");
  await expect(page.getByTestId("human-escalation")).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText(/Proposed appointment/i)).toHaveCount(0);
  await expect(page.getByTestId("confirmation-summary")).toHaveCount(0);
  const reason = page.getByTestId("human-escalation").locator(".wrap-text").first();
  await expect(reason).toBeVisible();
  const styles = await reason.evaluate((node) => getComputedStyle(node).position);
  expect(styles).not.toBe("absolute");
  expect(styles).not.toBe("fixed");
  await page.setViewportSize({ width: 390, height: 844 });
  await noHorizontalOverflow(page);
  await expect(page.locator(".composer")).toBeVisible();
});

test("reschedule journey on SHP-PHASE4-RESCHEDULE-001", async ({ page }) => {
  const shipment = await shipmentByNumber(RESCHEDULE);
  const before = await api(`/shipments/${shipment.id}/appointments?page=1&page_size=50`);
  const originalId = "75c4488c-f959-429c-8512-ad85aa8f029a";
  const alreadyRescheduled = before.payload.items.some((row: { id: string; notes?: string | null; status: string }) => {
    return row.id === originalId && (row.status === "cancelled" || (row.notes ?? "").includes("superseded_by="));
  });

  await bindShipment(page, RESCHEDULE);
  await expect(page.getByText("Phase4 Reschedule Driver").first()).toBeVisible();
  await expect(page.getByText(/Confirmed/i).first()).toBeVisible();

  if (!alreadyRescheduled) {
    const existingProposal = page.getByText(/Proposed appointment/i);
    if (!(await existingProposal.isVisible().catch(() => false))) {
      await sendDriver(page, "I cannot make the original 9 AM appointment. I'll arrive around 1 PM.");
      await sendDriver(page, "What options do I have?");
      await expect(page.getByRole("button", { name: /Select option/i }).first()).toBeVisible({ timeout: 60_000 });
      await expect(page.getByText(/00:30 UTC/)).toHaveCount(0);
      const later = page.locator(".option-card", { hasText: /12:45\sPM/i });
      if (await later.count()) {
        await later.getByRole("button", { name: /Select option/i }).click();
      } else {
        await page.getByRole("button", { name: /Select option/i }).last().click();
      }
    }
    await expect(page.getByText(/Proposed appointment/i)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(/Awaiting confirmation/i).first()).toBeVisible();
    await page.getByRole("button", { name: "Confirm proposed appointment" }).click();
  }

  await expect(page.getByTestId("confirmation-summary")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Cancelled \/ Superseded/i).first()).toBeVisible();
  await expect(page.getByText("Original remains visible as history")).toBeVisible();
  await expect(page.getByText("Original superseded")).toBeVisible();
  await expect(page.locator(".timeline-step.done", { hasText: "New appointment confirmed" })).toBeVisible();

  await page.reload();
  await bindShipment(page, RESCHEDULE);
  await expect(page.getByTestId("confirmation-summary")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/Cancelled \/ Superseded/i).first()).toBeVisible();

  await page.goto("/appointments");
  await expect(page.locator("table.data").getByText(RESCHEDULE).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("table.data").getByText("Cancelled / Superseded").first()).toBeVisible();
  await expect(page.locator("table.data").getByText("Confirmed").first()).toBeVisible();

  const after = await api(`/shipments/${shipment.id}/appointments?page=1&page_size=50`);
  const current = after.payload.items.filter((row: { status: string; notes?: string | null }) => {
    return row.status === "confirmed" && !(row.notes ?? "").includes("STEP7_PROPOSAL");
  });
  const originalStillPresent = after.payload.items.some((row: { id: string }) => row.id === originalId);
  expect(current.length).toBe(1);
  expect(originalStillPresent).toBe(true);
});

test("normal booking then real concurrent confirmation on SHP-PHASE4-RACE-001", async ({ page, browser }) => {
  const shipment = await shipmentByNumber(RACE);
  const before = await api(`/shipments/${shipment.id}/appointments?page=1&page_size=50`);
  const consumingBefore = before.payload.items.filter((row: { status: string; notes?: string | null }) => {
    return (row.status === "confirmed" || row.status === "held") && !(row.notes ?? "").includes("STEP7_PROPOSAL");
  });
  let winnerPage = page;
  let slotId: string | null = consumingBefore[0]?.appointment_slot_id ?? null;

  if (consumingBefore.length === 0) {
    await bindShipment(page, RACE);
    await expect(page.getByText("Phase4 Race Driver").first()).toBeVisible();
    await expect(page.getByText("Chicago Cross-Dock").first()).toBeVisible();
    await sendDriver(page, "I'm delayed in traffic. I'll arrive around 8:15 AM.");
    await expect(page.getByText(/8:15\sAM/i).first()).toBeVisible();
    await expect(page.getByTestId("confirmation-summary")).toHaveCount(0);
    await sendDriver(page, "What options do I have?");
    await expect(page.getByRole("button", { name: /Select option/i }).first()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(/8:00\sAM/i).first()).toBeVisible();
    await expect(page.getByText(/00:30 UTC/)).toHaveCount(0);
    const morning = page.locator(".option-card", { hasText: /8:00\sAM/i });
    if (await morning.count()) {
      await morning.getByRole("button", { name: /Select option/i }).click();
    } else {
      await page.getByRole("button", { name: /Select option/i }).first().click();
    }
    await expect(page.getByText(/Proposed appointment/i)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("confirmation-summary")).toHaveCount(0);
    await sendDriver(page, "Has it been confirmed?");
    await expect(page.getByText(/read-only/i).first()).toBeVisible();
    await expect(page.getByTestId("confirmation-summary")).toHaveCount(0);

    const proposalId = await pendingProposalId(shipment.id);
    const proposal = await api(`/proposals/${proposalId}`);
    expect(proposal.payload.status).toBe("proposed");
    slotId = proposal.payload.slot_id;
    const slotBefore = await api(`/appointment-slots/${slotId}`);
    expect(slotBefore.payload.status).toBe("open");

    const loserPage = await browser.newPage();
    await bindShipment(loserPage, RACE);
    await expect(loserPage.getByText(/Proposed appointment/i)).toBeVisible({ timeout: 30_000 });

    const waitAccept = (target: Page) =>
      target.waitForResponse(
        (response) =>
          response.url().includes(`/proposals/${proposalId}/accept`) && response.request().method() === "POST",
        { timeout: 30_000 },
      );
    const [first, second] = await Promise.all([
      waitAccept(page),
      waitAccept(loserPage),
      page.getByRole("button", { name: "Confirm proposed appointment" }).click(),
      loserPage.getByRole("button", { name: "Confirm proposed appointment" }).click(),
    ]);
    const statuses = [first.status(), second.status()].sort();
    expect(statuses).toEqual([200, 409]);
    const winnerHttp = first.status() === 200 ? first : second;
    const loserHttp = first.status() === 409 ? first : second;
    const winnerBody = await winnerHttp.json();
    const loserBody = await loserHttp.json().catch(() => ({}));
    expect(winnerBody.appointment_id).toBeTruthy();
    expect(loserBody?.appointment_id ?? loserBody?.appointmentId ?? null).toBeFalsy();

    winnerPage = first.status() === 200 ? page : loserPage;
    const conflictPage = first.status() === 409 ? page : loserPage;

    await expect(conflictPage.getByTestId("stale-conflict")).toBeVisible({ timeout: 20_000 });
    await expect(conflictPage.getByTestId("confirmation-summary")).toHaveCount(0);
    await expect(conflictPage.getByText(/Your appointment is confirmed/i)).toHaveCount(0);
    await expect(conflictPage.getByRole("button", { name: /select option/i })).toHaveCount(0);
    await expect(winnerPage.getByTestId("confirmation-summary")).toBeVisible({ timeout: 20_000 });
    await loserPage.close();
  }

  await winnerPage.reload();
  await bindShipment(winnerPage, RACE);
  await expect(winnerPage.getByTestId("confirmation-summary")).toBeVisible({ timeout: 20_000 });
  await expect(winnerPage.getByText(/Your appointment is confirmed/i)).toBeVisible();
  await expect(winnerPage.getByTestId("confirmation-summary")).toContainText(/8:00\sAM/);
  await expect(winnerPage.getByTestId("stale-conflict")).toHaveCount(0);
  const summaryBox = await winnerPage.getByTestId("confirmation-summary").boundingBox();
  const logBox = await winnerPage.getByRole("log").boundingBox();
  expect(summaryBox!.y).toBeLessThan(logBox!.y);
  await expect(winnerPage.locator(".messages")).not.toContainText("Your appointment is confirmed.");
  await winnerPage.getByRole("button", { name: /show details/i }).click();
  await expect(winnerPage.getByTestId("confirmation-details")).toBeVisible();
  await expect(winnerPage.getByTestId("confirmation-details")).not.toContainText(/feasibility engine/i);
  await expect(winnerPage.locator(".timeline-step.done", { hasText: "Appointment confirmed" })).toBeVisible();

  await winnerPage.goto("/appointments");
  await expect(winnerPage.locator("table.data").getByText(RACE).first()).toBeVisible({ timeout: 30_000 });
  await expect(winnerPage.locator("table.data").getByText("Phase4 Race Driver").first()).toBeVisible();
  await expect(winnerPage.locator("table.data").getByText("Chicago Cross-Dock").first()).toBeVisible();
  await expect(winnerPage.locator("table.data").getByText("Confirmed").first()).toBeVisible();

  const after = await api(`/shipments/${shipment.id}/appointments?page=1&page_size=50`);
  const confirmed = after.payload.items.filter((row: { status: string; notes?: string | null }) => {
    return row.status === "confirmed" && !(row.notes ?? "").includes("STEP7_PROPOSAL");
  });
  expect(confirmed.length).toBe(1);
  const resolvedSlotId = slotId ?? confirmed[0].appointment_slot_id;
  const slot = await api(`/appointment-slots/${resolvedSlotId}`);
  expect(slot.payload.status).toBe("full");
});
