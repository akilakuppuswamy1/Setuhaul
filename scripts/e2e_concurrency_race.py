"""Live API concurrency acceptance: one HTTP 200, one HTTP 409, exactly one confirmed."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.e2e_api import require_health, request, resolve_shipment

FIXTURE_HINT = "python scripts/seed_e2e_fixtures.py"
RACE_SHIPMENT = "SHP-PHASE4-RACE-001"


def pending_proposal_id(shipment_id: str) -> str:
    code, payload = request("GET", f"/shipments/{shipment_id}/appointments?page=1&page_size=50")
    if code != 200:
        raise SystemExit(f"list appointments failed: {code} {payload}")
    pending = [
        row
        for row in payload.get("items") or []
        if row.get("status") == "requested" and "STEP7_PROPOSAL" in (row.get("notes") or "")
    ]
    if not pending:
        raise SystemExit(
            f"No pending proposal on {RACE_SHIPMENT!r}. Create one via conversation or run {FIXTURE_HINT}."
        )
    pending.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return str(pending[0]["id"])


def create_race_proposal(shipment: dict[str, Any]) -> str:
    code, created = request(
        "POST",
        "/conversations",
        {
            "driver_id": shipment["driver_id"],
            "shipment_id": shipment["id"],
            "subject": "e2e-concurrency-setup",
        },
    )
    if code not in {200, 201}:
        raise SystemExit(f"create conversation failed: {code} {created}")
    thread_id = created["thread_id"]
    turn: dict[str, Any] = {}
    for message in (
        "I'm delayed in traffic. I'll arrive around 8:15 AM.",
        "What options do I have?",
        "The first one works.",
    ):
        code, turn = request("POST", f"/conversations/{thread_id}/messages", {"message": message})
        if code != 200:
            raise SystemExit(f"setup message failed: {code} {turn}")
    proposal_id = turn.get("proposal_id")
    if not proposal_id:
        proposal_id = pending_proposal_id(shipment["id"])
    code, proposal = request("GET", f"/proposals/{proposal_id}")
    if code != 200 or proposal.get("status") != "proposed":
        raise SystemExit(f"proposal not proposed: {code} {proposal}")
    return str(proposal_id)


def main() -> None:
    require_health()
    shipment = resolve_shipment(RACE_SHIPMENT, hint=FIXTURE_HINT)

    _, listed = request("GET", f"/shipments/{shipment['id']}/appointments?page=1&page_size=50")
    consuming = [
        row
        for row in listed.get("items") or []
        if row.get("status") in {"confirmed", "held"}
        and "STEP7_PROPOSAL" not in (row.get("notes") or "")
    ]
    if consuming:
        raise SystemExit(
            f"{RACE_SHIPMENT!r} already has a confirmed appointment. Run {FIXTURE_HINT} before the race test."
        )

    proposal_id = create_race_proposal(shipment)
    code, proposal = request("GET", f"/proposals/{proposal_id}")
    if code != 200:
        raise SystemExit(f"proposal lookup failed: {code} {proposal}")
    slot_id = proposal.get("slot_id")

    def accept_once() -> int:
        status, _payload = request("POST", f"/proposals/{proposal_id}/accept", {})
        return status

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: accept_once(), range(2)))

    print("concurrent accept codes", codes)
    if sorted(codes) != [200, 409]:
        raise SystemExit(f"expected [200, 409], got {codes}")

    _, after = request("GET", f"/shipments/{shipment['id']}/appointments?page=1&page_size=50")
    confirmed = [
        row
        for row in after.get("items") or []
        if row.get("status") == "confirmed" and "STEP7_PROPOSAL" not in (row.get("notes") or "")
    ]
    if len(confirmed) != 1:
        raise SystemExit(f"expected exactly one confirmed appointment, got {len(confirmed)}")
    if slot_id:
        _, slot = request("GET", f"/appointment-slots/{slot_id}")
        if slot.get("status") != "full":
            raise SystemExit(f"expected slot full, got {slot}")
    print("CONCURRENCY RACE PASS")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        raise
