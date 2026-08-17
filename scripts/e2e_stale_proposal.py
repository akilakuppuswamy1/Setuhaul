"""Live API stale-proposal acceptance: winner 200, loser 409."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.e2e_api import require_health, request, resolve_shipment

FIXTURE_HINT = "python scripts/seed_e2e_fixtures.py"


def proposal_for(shipment_number: str) -> dict:
    shipment = resolve_shipment(shipment_number, hint=FIXTURE_HINT)
    code, payload = request("GET", f"/shipments/{shipment['id']}/appointments?page=1&page_size=20")
    if code != 200:
        raise SystemExit(f"appointments failed for {shipment_number}: {code}")
    for row in payload.get("items") or []:
        if row.get("status") == "requested" and "STEP7_PROPOSAL" in (row.get("notes") or ""):
            return row
    raise SystemExit(f"no pending proposal on {shipment_number}")


def main() -> None:
    require_health()
    win = proposal_for("SHP-E2E-STALE-001")
    lose = proposal_for("SHP-E2E-STALE-002")
    win_code, win_body = request("POST", f"/proposals/{win['id']}/accept", {})
    lose_code, lose_body = request("POST", f"/proposals/{lose['id']}/accept", {})
    print("winner", win_code, win_body)
    print("loser", lose_code, lose_body)
    if win_code != 200:
        raise SystemExit(f"winner expected 200, got {win_code}")
    if lose_code != 409:
        raise SystemExit(f"loser expected 409, got {lose_code}")
    slot_id = win.get("appointment_slot_id")
    _, slot = request("GET", f"/appointment-slots/{slot_id}")
    if slot.get("status") != "full":
        raise SystemExit(f"expected slot full, got {slot}")
    print("STALE PROPOSAL PASS")


if __name__ == "__main__":
    main()
