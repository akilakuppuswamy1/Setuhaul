"""Live API walkthrough against a running SetuHaul process. No mocked outcomes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.e2e_api import BASE, require_health, request, resolve_shipment

HERO_SHIPMENT_NUMBER = "SH-1024"
HERO_DRIVER_EXTERNAL_ID = "demo-driver-rivera"
FIXTURE_HINT = "python scripts/seed_e2e_fixtures.py"


def send(thread_id: str, message: str) -> dict[str, Any]:
    status, payload = request("POST", f"/conversations/{thread_id}/messages", {"message": message})
    print(f"\n=== {message!r} -> HTTP {status}")
    if status >= 400:
        print(json.dumps(payload, indent=2)[:2000])
        raise SystemExit(f"message failed: {status}")
    tools = [(item.get("name"), item.get("success"), item.get("error")) for item in payload.get("tool_calls") or []]
    print(
        "intent={intent} status={status} tools={tools} proposal={proposal} human={human}".format(
            intent=payload.get("intent"),
            status=payload.get("status"),
            tools=tools,
            proposal=payload.get("proposal_id"),
            human=payload.get("requires_human"),
        )
    )
    print((payload.get("response") or "")[:500])
    return payload


def resolve_hero_context() -> tuple[str, str]:
    shipment = resolve_shipment(HERO_SHIPMENT_NUMBER, hint=FIXTURE_HINT)
    driver_id = shipment.get("driver_id")
    if not driver_id:
        raise SystemExit(
            f"Shipment {HERO_SHIPMENT_NUMBER!r} has no driver_id. "
            f"Re-seed with {FIXTURE_HINT}."
        )
    code, detail = request("GET", f"/shipments/{shipment['id']}")
    if code != 200:
        raise SystemExit(f"Could not load shipment {HERO_SHIPMENT_NUMBER!r}: HTTP {code} {detail}")
    appt_code, appt_payload = request("GET", f"/shipments/{shipment['id']}/appointments?page=1&page_size=50")
    if appt_code != 200:
        raise SystemExit(f"Could not list appointments for {HERO_SHIPMENT_NUMBER!r}: HTTP {appt_code}")
    appointments = appt_payload.get("items") or []
    consuming = [
        row
        for row in appointments
        if row.get("status") in {"confirmed", "held"}
        and "STEP7_PROPOSAL" not in (row.get("notes") or "")
        and "Original 6:30 PM appointment" not in (row.get("notes") or "")
    ]
    if consuming:
        raise SystemExit(
            f"Hero fixture {HERO_SHIPMENT_NUMBER!r} already has a confirmed alternate appointment. "
            f"Run {FIXTURE_HINT} to reset Dallas hero state before replaying the flow."
        )
    return str(driver_id), str(shipment["id"])


def main() -> None:
    health = require_health()
    print("health", health, "api", BASE)

    driver_id, shipment_id = resolve_hero_context()
    print(f"hero shipment={HERO_SHIPMENT_NUMBER} driver_external_id={HERO_DRIVER_EXTERNAL_ID}")
    print(f"resolved driver_id={driver_id} shipment_id={shipment_id}")

    code, created = request(
        "POST",
        "/conversations",
        {"driver_id": driver_id, "shipment_id": shipment_id, "subject": "E2E hero"},
    )
    if code not in {200, 201}:
        raise SystemExit(f"create conversation failed: {code} {created}")
    thread_id = created["thread_id"]
    print("thread", thread_id)

    t1 = send(
        thread_id,
        "I'll be two hours late. I was supposed to reach by 6:30 PM, but I'll reach around 8:30 PM.",
    )
    names = [item["name"] for item in t1.get("tool_calls") or []]
    assert t1["intent"] in {"UPDATE_ETA", "REPORT_DELAY"}, t1["intent"]
    assert "record_eta_update" in names, names
    assert "accept_proposal" not in names
    assert "allocate" not in str(names)

    t2 = send(thread_id, "I also have an emergency and need to leave by 9:30 PM.")
    names = [item["name"] for item in t2.get("tool_calls") or []]
    assert "accept_proposal" not in names
    assert t2.get("proposal_id") in {None, t1.get("proposal_id")}

    t3 = send(thread_id, "My ETA is 8:30 PM. What options do I have?")
    names = [item["name"] for item in t3.get("tool_calls") or []]
    assert t3["intent"] == "ASK_OPTIONS", t3["intent"]
    assert "get_available_options" in names, names
    assert "create_proposal" not in names
    assert "accept_proposal" not in names
    options = (t3.get("metadata") or {}).get("presented_options") or []
    print("options", len(options))
    if len(options) < 1:
        raise SystemExit(
            f"expected at least one feasible option for {HERO_SHIPMENT_NUMBER!r}. "
            f"Run {FIXTURE_HINT} if slots were consumed."
        )

    selection = "The first one works." if len(options) == 1 else "The second one works."
    t4 = send(thread_id, selection)
    names = [item["name"] for item in t4.get("tool_calls") or []]
    assert t4["intent"] == "PROPOSE_CHANGE", t4["intent"]
    assert "create_proposal" in names, names
    assert "accept_proposal" not in names
    assert t4.get("proposal_id"), t4
    proposal_id = t4["proposal_id"]
    code, proposal = request("GET", f"/proposals/{proposal_id}")
    print("proposal after select", code, proposal.get("status"), proposal.get("message"))
    assert proposal.get("status") == "proposed", proposal

    t5 = send(thread_id, "Has it been confirmed?")
    names = [item["name"] for item in t5.get("tool_calls") or []]
    assert t5["intent"] == "ASK_STATUS", t5["intent"]
    assert names == ["get_proposal"], names
    assert "accept_proposal" not in names

    t6 = send(thread_id, "Confirm it.")
    names = [item["name"] for item in t6.get("tool_calls") or []]
    assert t6["intent"] == "ACCEPT_PROPOSAL", t6["intent"]
    assert "accept_proposal" in names, names
    code, proposal = request("GET", f"/proposals/{proposal_id}")
    print("proposal after confirm", code, proposal.get("status"), proposal.get("appointment_id"))
    if proposal.get("status") != "confirmed":
        raise SystemExit(f"expected confirmed, got {proposal}")

    print("\nHERO FLOW PASS")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print("ASSERTION FAILED", exc, file=sys.stderr)
        raise
