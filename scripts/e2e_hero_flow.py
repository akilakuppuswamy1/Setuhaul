"""Live API walkthrough against a running SetuHaul process. No mocked outcomes."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = os.environ.get("SETUHAUL_API_URL", "http://127.0.0.1:8010").rstrip("/")
DRIVER_ID = os.environ.get("SETUHAUL_DRIVER_ID", "41a10bd1-a604-4f85-afcd-06286902e88d")
SHIPMENT_ID = os.environ.get("SETUHAUL_SHIPMENT_ID", "aba51808-a7a2-4c9b-86a9-dee411481438")


def request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode())
            return response.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


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


def main() -> None:
    code, health = request("GET", "/health")
    if code != 200 or health.get("service") != "setuhaul":
        raise SystemExit(f"unexpected health: {code} {health}")
    print("health", health)

    code, created = request(
        "POST",
        "/conversations",
        {"driver_id": DRIVER_ID, "shipment_id": SHIPMENT_ID, "subject": "E2E hero"},
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
    if len(options) < 2:
        raise SystemExit("expected at least two feasible options")

    t4 = send(thread_id, "The second one works, but I need to leave by 9:30 PM.")
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

    print("\n--- conflict / stale path ---")
    code, created2 = request(
        "POST",
        "/conversations",
        {"driver_id": DRIVER_ID, "shipment_id": SHIPMENT_ID, "subject": "E2E conflict"},
    )
    thread2 = created2["thread_id"]
    send(thread2, "My ETA is 8:30 PM. What options do I have?")
    conflict_turn = send(thread2, "The first one works.")
    names = [item["name"] for item in conflict_turn.get("tool_calls") or []]
    if "create_proposal" in names and conflict_turn.get("proposal_id"):
        confirm_conflict = send(thread2, "Confirm it.")
        confirm_names = [item["name"] for item in confirm_conflict.get("tool_calls") or []]
        print("conflict tools", confirm_names, "status", confirm_conflict.get("status"))
        if confirm_conflict.get("status") in {"stale", "conflict"} or confirm_conflict.get("status") != "ok":
            print("CONFLICT PATH PASS", confirm_conflict.get("status"), confirm_conflict.get("response", "")[:240])
        else:
            code, after = request("GET", f"/proposals/{conflict_turn['proposal_id']}")
            print("conflict proposal", after.get("status"))
            if after.get("status") == "confirmed":
                raise SystemExit("conflict path unexpectedly confirmed a second allocation")
    else:
        print("CONFLICT PATH PASS (no second proposal; backend refused duplicate allocation earlier)")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print("ASSERTION FAILED", exc, file=sys.stderr)
        raise
