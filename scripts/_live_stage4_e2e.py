"""Non-destructive live Stage 4 API checks. Does not DROP SCHEMA or reset the demo DB."""

from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

BASE = os.environ.get("SETUHAUL_API_URL", "http://127.0.0.1:8010").rstrip("/")


def request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            payload = json.loads(response.read().decode()) if response.length != 0 else None
            return response.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def must(code: int, payload: Any, expected: set[int], label: str) -> Any:
    if code not in expected:
        raise SystemExit(f"{label} failed HTTP {code}: {payload}")
    return payload


def shipments_by_number() -> dict[str, dict[str, Any]]:
    code, payload = request("GET", "/shipments?page=1&page_size=100")
    must(code, payload, {200}, "list shipments")
    return {item["shipment_number"]: item for item in payload.get("items") or []}


def open_thread(driver_id: str, shipment_id: str, subject: str) -> str:
    code, created = request(
        "POST",
        "/conversations",
        {"driver_id": driver_id, "shipment_id": shipment_id, "subject": subject},
    )
    must(code, created, {200, 201}, "create conversation")
    return created["thread_id"]


def send(thread_id: str, message: str) -> dict[str, Any]:
    code, payload = request("POST", f"/conversations/{thread_id}/messages", {"message": message})
    must(code, payload, {200}, f"message {message!r}")
    return payload


def names(turn: dict[str, Any]) -> list[str]:
    return [item.get("name") for item in turn.get("tool_calls") or []]


def appointment_states(shipment_id: str) -> list[dict[str, Any]]:
    code, payload = request("GET", f"/shipments/{shipment_id}/appointments?page=1&page_size=50")
    must(code, payload, {200}, "list shipment appointments")
    return payload.get("items") or []


def pick_hero(by_number: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for number in ("SHP-DEMO-004", "SHP-DEMO-005", "SHP-DEMO-002", "SHP-DEMO-001"):
        item = by_number.get(number)
        if not item:
            continue
        confirmed = [
            row
            for row in appointment_states(item["id"])
            if row.get("status") == "confirmed" and "STEP7_PROPOSAL" not in (row.get("notes") or "")
        ]
        if not confirmed:
            return item
    raise SystemExit("No unused hero demo shipment remains (001/002/004/005 already confirmed).")


def flow_hero(item: dict[str, Any]) -> None:
    thread = open_thread(item["driver_id"], item["id"], "stage4-hero")
    eta = send(thread, "I'll reach around 8:30 PM because of traffic.")
    assert eta["intent"] == "UPDATE_ETA", eta["intent"]
    assert "record_eta_update" in names(eta)
    assert "8:30 PM" in (eta.get("response") or "")
    assert "00:30 UTC" not in (eta.get("response") or "")
    combo = send(thread, "I can't make it, give me options.")
    assert "get_available_options" in names(combo)
    assert "request_human_escalation" not in names(combo)
    assert combo.get("requires_human") is False
    selected = send(thread, "The first one works.")
    assert "create_proposal" in names(selected)
    assert "accept_proposal" not in names(selected)
    status = send(thread, "Has it been confirmed?")
    assert status["intent"] == "ASK_STATUS"
    assert "accept_proposal" not in names(status)
    hold = send(thread, "Don't confirm it yet.")
    assert hold["response"] == "The appointment has not been confirmed."
    assert "accept_proposal" not in names(hold)
    confirmed = send(thread, "Confirm it.")
    assert "accept_proposal" in names(confirmed)
    assert any(item.get("name") == "accept_proposal" and item.get("success") for item in confirmed.get("tool_calls") or [])
    rows = appointment_states(item["id"])
    current = [row for row in rows if row.get("status") == "confirmed" and "STEP7_PROPOSAL" not in (row.get("notes") or "")]
    assert len(current) == 1, rows
    print("A hero PASS", item["shipment_number"])


def flow_reschedule(item: dict[str, Any]) -> None:
    rows = appointment_states(item["id"])
    cancelled = [row for row in rows if row.get("status") == "cancelled" and "superseded_by=" in (row.get("notes") or "")]
    current = [row for row in rows if row.get("status") == "confirmed" and "STEP7_PROPOSAL" not in (row.get("notes") or "")]
    if cancelled and len(current) == 1:
        print("B reschedule already complete; skipping mutation")
        return
    thread = open_thread(item["driver_id"], item["id"], "stage4-reschedule")
    options = send(thread, "I can't make the 6:30 PM appointment.")
    assert "get_available_options" in names(options)
    assert "request_human_escalation" not in names(options)
    assert "8:30 PM" in (options.get("response") or "")
    selected = send(thread, "The first one works.")
    assert "create_proposal" in names(selected)
    confirmed = send(thread, "Confirm it.")
    assert any(item.get("name") == "accept_proposal" and item.get("success") for item in confirmed.get("tool_calls") or [])
    rows = appointment_states(item["id"])
    cancelled = [row for row in rows if row.get("status") == "cancelled" and "superseded_by=" in (row.get("notes") or "")]
    current = [row for row in rows if row.get("status") == "confirmed" and "STEP7_PROPOSAL" not in (row.get("notes") or "")]
    assert cancelled, rows
    assert len(current) == 1, rows
    print("B reschedule PASS", item["shipment_number"])


def flow_nocap(item: dict[str, Any]) -> None:
    before = appointment_states(item["id"])
    thread = open_thread(item["driver_id"], item["id"], "stage4-nocap")
    turn = send(thread, "What options do I have?")
    assert "get_available_options" in names(turn)
    assert turn.get("requires_human") is True
    after = appointment_states(item["id"])
    assert len(after) == len(before)
    print("C nocap PASS")


def flow_race(item: dict[str, Any]) -> None:
    thread = open_thread(item["driver_id"], item["id"], "stage4-race")
    send(thread, "What options do I have?")
    proposed = send(thread, "The first one works.")
    proposal_id = proposed.get("proposal_id")
    if not proposal_id:
        raise SystemExit(f"race proposal missing: {proposed}")
    before = [
        row
        for row in appointment_states(item["id"])
        if row.get("status") == "confirmed" and "STEP7_PROPOSAL" not in (row.get("notes") or "")
    ]

    def accept() -> int:
        code, _payload = request("POST", f"/proposals/{proposal_id}/accept", {})
        return code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: accept(), range(2)))
    assert sorted(codes) == [200, 409], codes
    after = [
        row
        for row in appointment_states(item["id"])
        if row.get("status") == "confirmed" and "STEP7_PROPOSAL" not in (row.get("notes") or "")
    ]
    assert len(after) == len(before) + 1
    loser = send(open_thread(item["driver_id"], item["id"], "stage4-race-loser"), "Confirm it.")
    assert "Appointment confirmed" not in (loser.get("response") or "")
    stale = (loser.get("status") in {"stale", "conflict", "error"}) or any(
        (item.get("name") == "accept_proposal" and not item.get("success"))
        or item.get("error")
        for item in loser.get("tool_calls") or []
    )
    # Already confirmed is also a safe 409/conflict, not a second booking.
    assert stale or "already" in (loser.get("response") or "").lower() or loser.get("status") != "ok" or "no longer available" in (loser.get("response") or "").lower()
    print("D race PASS", codes)


def flow_readonly(item: dict[str, Any]) -> None:
    before = appointment_states(item["id"])
    thread = open_thread(item["driver_id"], item["id"], "stage4-readonly")
    for message in (
        "When is my appointment?",
        "What is my appointment time?",
        "Has it been confirmed?",
        "Don't confirm it yet.",
    ):
        turn = send(thread, message)
        assert "accept_proposal" not in names(turn), message
        assert "create_proposal" not in names(turn), message
    after = appointment_states(item["id"])
    assert after == before
    print("E readonly PASS")


def flow_nl(item: dict[str, Any]) -> None:
    thread = open_thread(item["driver_id"], item["id"], "stage4-nl")
    eta = send(thread, "I'll reach around 8:30 PM because of traffic.")
    assert eta["intent"] == "UPDATE_ETA"
    options = send(thread, "I can't make it, give me options.")
    assert "get_available_options" in names(options)
    print("F natural language PASS")


def main() -> None:
    code, health = request("GET", "/health")
    must(code, health, {200}, "health")
    by_number = shipments_by_number()
    required = {
        "SHP-DEMO-001",
        "SHP-DEMO-RESCHEDULE",
        "SHP-DEMO-NOCAP",
        "SHP-DEMO-RACE",
    }
    missing = [name for name in required if name not in by_number]
    if missing:
        raise SystemExit(f"missing demo shipments: {missing}")
    results: dict[str, str] = {}
    try:
        flow_hero(pick_hero(by_number))
        results["A"] = "PASS"
    except Exception as exc:
        results["A"] = f"FAIL {exc}"
        print("A FAIL", exc)
        traceback.print_exc()
    try:
        flow_reschedule(by_number["SHP-DEMO-RESCHEDULE"])
        results["B"] = "PASS"
    except Exception as exc:
        results["B"] = f"FAIL {exc}"
        print("B FAIL", exc)
    try:
        flow_nocap(by_number["SHP-DEMO-NOCAP"])
        results["C"] = "PASS"
    except Exception as exc:
        results["C"] = f"FAIL {exc}"
        print("C FAIL", exc)
    try:
        flow_race(by_number["SHP-DEMO-RACE"])
        results["D"] = "PASS"
    except Exception as exc:
        results["D"] = f"FAIL {exc}"
        print("D FAIL", exc)
        traceback.print_exc()
    try:
        flow_readonly(by_number["SHP-DEMO-001"])
        results["E"] = "PASS"
    except Exception as exc:
        results["E"] = f"FAIL {exc}"
        print("E FAIL", exc)
    try:
        flow_nl(by_number.get("SHP-DEMO-003") or by_number["SHP-DEMO-001"])
        results["F"] = "PASS"
    except Exception as exc:
        results["F"] = f"FAIL {exc}"
        print("F FAIL", exc)
    print("LIVE_API_RESULTS", json.dumps(results, indent=2))
    if any(value != "PASS" for value in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
