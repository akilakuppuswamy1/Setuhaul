"""INSERT-only Phase 4 live E2E fixtures.

Does not reset the demo database, drop schema, or update existing demo rows.
Targets DATABASE_URL / setuhaul only. Never selects setuhaul_test.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.engines.feasibility.rules import CAPACITY_CONSUMING_APPOINTMENT_STATUSES
from app.models import (
    Appointment,
    AppointmentSlot,
    Carrier,
    Dock,
    Driver,
    ETAUpdate,
    Facility,
    Shipment,
    Vehicle,
)
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    DockStatus,
    EntityStatus,
    ETASource,
    ShipmentStatus,
)

TZ = ZoneInfo("America/Chicago")
DEMO_DAY = datetime(2026, 8, 13, tzinfo=TZ)
API = "http://127.0.0.1:8010"
FORBIDDEN = frozenset({"postgres", "template0", "template1", "setuhaul_test"})
_CONSUMING = tuple(AppointmentStatus(status) for status in CAPACITY_CONSUMING_APPOINTMENT_STATUSES)

BOOK_ORIGINAL = (DEMO_DAY.replace(hour=12, minute=0), DEMO_DAY.replace(hour=12, minute=30))
BOOK_NEW = (DEMO_DAY.replace(hour=13, minute=0), DEMO_DAY.replace(hour=14, minute=0))
BOOK_ETA = DEMO_DAY.replace(hour=13, minute=15)

RACE_ORIGINAL = (DEMO_DAY.replace(hour=7, minute=0), DEMO_DAY.replace(hour=7, minute=30))
RACE_NEW = (DEMO_DAY.replace(hour=8, minute=0), DEMO_DAY.replace(hour=9, minute=0))
RACE_ETA = DEMO_DAY.replace(hour=8, minute=15)

RESCH_ORIGINAL = (DEMO_DAY.replace(hour=9, minute=0), DEMO_DAY.replace(hour=9, minute=30))
RESCH_NEW = (DEMO_DAY.replace(hour=12, minute=45), DEMO_DAY.replace(hour=13, minute=45))
RESCH_ETA = DEMO_DAY.replace(hour=13, minute=0)


def _utc(value: datetime) -> datetime:
    return value.astimezone(TZ).astimezone(ZoneInfo("UTC"))


def assert_live_demo() -> str:
    parsed = make_url(settings.database_url)
    name = parsed.database or ""
    print("=" * 50)
    print("DATABASE =", name)
    print("=" * 50)
    if name in FORBIDDEN or name != "setuhaul":
        raise SystemExit(f"Refusing to write fixtures to database {name!r}")
    with engine.connect() as connection:
        current = connection.exec_driver_sql("SELECT current_database()").scalar()
    print("current_database() =", current)
    if current != "setuhaul":
        raise SystemExit(f"Refusing connected database {current!r}")
    print("INSERT-only Phase 4 fixture seed. Existing demo rows will not be updated.")
    return str(current)


def _get_or_insert(session: Session, model, match: dict[str, Any], values: dict[str, Any]):
    existing = session.query(model).filter_by(**match).one_or_none()
    if existing is not None:
        return existing, False
    row = model(**values)
    session.add(row)
    session.flush()
    return row, True


def _slot(session: Session, facility: Facility, start: datetime, end: datetime, capacity: int) -> tuple[AppointmentSlot, bool]:
    start_utc = _utc(start)
    end_utc = _utc(end)
    for existing in session.query(AppointmentSlot).filter_by(facility_id=facility.id).all():
        existing_start = existing.start_time.astimezone(ZoneInfo("UTC")) if existing.start_time.tzinfo else existing.start_time.replace(tzinfo=ZoneInfo("UTC"))
        existing_end = existing.end_time.astimezone(ZoneInfo("UTC")) if existing.end_time.tzinfo else existing.end_time.replace(tzinfo=ZoneInfo("UTC"))
        if existing_start == start_utc and existing_end == end_utc:
            return existing, False
    slot = AppointmentSlot(
        facility_id=facility.id,
        start_time=start_utc,
        end_time=end_utc,
        capacity=capacity,
        status=AppointmentSlotStatus.OPEN,
    )
    session.add(slot)
    session.flush()
    return slot, True


def seed(session: Session) -> dict[str, Any]:
    created: list[str] = []
    chicago = session.query(Facility).filter_by(code="CHI-XD").one()
    carrier = session.query(Carrier).filter_by(code="SETU-DEMO").one()

    specs = [
        {
            "key": "book",
            "shipment_number": "SHP-PHASE4-BOOK-001",
            "driver_ext": "phase4-book-driver",
            "driver_name": "Phase4 Book Driver",
            "phone": "+1555404001",
            "plate": "P4-BOOK-VAN",
            "dock_name": "Dock 0-P4-BOOK",
            "original": BOOK_ORIGINAL,
            "new": BOOK_NEW,
            "eta": BOOK_ETA,
            "original_status": AppointmentStatus.REQUESTED,
            "original_notes": "PHASE4-BOOK original 12:00 PM appointment",
            "eta_reason": "PHASE4-BOOK dispatch ETA 1:15 PM",
        },
        {
            "key": "race",
            "shipment_number": "SHP-PHASE4-RACE-001",
            "driver_ext": "phase4-race-driver",
            "driver_name": "Phase4 Race Driver",
            "phone": "+1555404002",
            "plate": "P4-RACE-VAN",
            "dock_name": "Dock 0-P4-RACE",
            "original": RACE_ORIGINAL,
            "new": RACE_NEW,
            "eta": RACE_ETA,
            "original_status": AppointmentStatus.REQUESTED,
            "original_notes": "PHASE4-RACE original 7:00 AM appointment",
            "eta_reason": "PHASE4-RACE dispatch ETA 8:15 AM",
        },
        {
            "key": "reschedule",
            "shipment_number": "SHP-PHASE4-RESCHEDULE-001",
            "driver_ext": "phase4-reschedule-driver",
            "driver_name": "Phase4 Reschedule Driver",
            "phone": "+1555404003",
            "plate": "P4-RESCH-VAN",
            "dock_name": "Dock 0-P4-RESCH",
            "original": RESCH_ORIGINAL,
            "new": RESCH_NEW,
            "eta": RESCH_ETA,
            "original_status": AppointmentStatus.CONFIRMED,
            "original_notes": "PHASE4-RESCHEDULE original 9:00 AM confirmed appointment",
            "eta_reason": "PHASE4-RESCHEDULE driver ETA 1:00 PM; original 9:00 AM cannot be made",
        },
    ]

    out: dict[str, Any] = {"facility": chicago, "created": created, "items": {}}
    now = datetime.now(tz=TZ)

    for spec in specs:
        driver, inserted = _get_or_insert(
            session,
            Driver,
            {"external_id": spec["driver_ext"]},
            {
                "carrier_id": carrier.id,
                "name": spec["driver_name"],
                "phone": spec["phone"],
                "external_id": spec["driver_ext"],
                "status": EntityStatus.ACTIVE,
            },
        )
        if inserted:
            created.append(f"driver:{spec['driver_ext']}")

        vehicle, inserted = _get_or_insert(
            session,
            Vehicle,
            {"license_plate": spec["plate"]},
            {
                "carrier_id": carrier.id,
                "license_plate": spec["plate"],
                "vehicle_type": "53ft_dry_van",
                "max_weight_kg": Decimal("20000"),
                "max_volume_cbm": Decimal("90"),
                "status": EntityStatus.ACTIVE,
            },
        )
        if inserted:
            created.append(f"vehicle:{spec['plate']}")

        dock, inserted = _get_or_insert(
            session,
            Dock,
            {"facility_id": chicago.id, "name": spec["dock_name"]},
            {
                "facility_id": chicago.id,
                "name": spec["dock_name"],
                "dock_type": "standard",
                "max_weight_kg": Decimal("25000"),
                "temperature_controlled": False,
                "status": DockStatus.AVAILABLE,
            },
        )
        if inserted:
            created.append(f"dock:{spec['dock_name']}")

        original_slot, inserted = _slot(session, chicago, spec["original"][0], spec["original"][1], 1)
        if inserted:
            created.append(f"slot:{spec['original'][0].isoformat()}")
        new_slot, inserted = _slot(session, chicago, spec["new"][0], spec["new"][1], 1)
        if inserted:
            created.append(f"slot:{spec['new'][0].isoformat()}")

        shipment, inserted = _get_or_insert(
            session,
            Shipment,
            {"shipment_number": spec["shipment_number"]},
            {
                "carrier_id": carrier.id,
                "driver_id": driver.id,
                "vehicle_id": vehicle.id,
                "shipment_number": spec["shipment_number"],
                "origin_location": "Rockford, IL",
                "destination_location": "Chicago Cross-Dock",
                "destination_facility_id": chicago.id,
                "status": ShipmentStatus.IN_TRANSIT,
                "is_active": True,
                "weight_kg": Decimal("8000"),
                "pallet_count": 10,
            },
        )
        if inserted:
            created.append(f"shipment:{spec['shipment_number']}")

        eta, inserted = _get_or_insert(
            session,
            ETAUpdate,
            {"shipment_id": shipment.id, "reason": spec["eta_reason"]},
            {
                "shipment_id": shipment.id,
                "previous_eta": _utc(spec["original"][0]),
                "new_eta": _utc(spec["eta"]),
                "update_timestamp": now,
                "source": ETASource.DISPATCH,
                "reason": spec["eta_reason"],
            },
        )
        if inserted:
            created.append(f"eta:{spec['shipment_number']}")

        appt, inserted = _get_or_insert(
            session,
            Appointment,
            {"shipment_id": shipment.id, "notes": spec["original_notes"]},
            {
                "shipment_id": shipment.id,
                "facility_id": chicago.id,
                "appointment_slot_id": original_slot.id,
                "dock_id": dock.id if spec["original_status"] == AppointmentStatus.CONFIRMED else None,
                "status": spec["original_status"],
                "notes": spec["original_notes"],
            },
        )
        if inserted:
            created.append(f"appointment:{spec['shipment_number']}:original")
            if spec["original_status"] == AppointmentStatus.CONFIRMED:
                original_slot.status = AppointmentSlotStatus.FULL
                dock.status = DockStatus.OCCUPIED

        out["items"][spec["key"]] = {
            "shipment": shipment,
            "driver": driver,
            "dock": dock,
            "original_slot": original_slot,
            "new_slot": new_slot,
            "eta": eta,
            "original_appointment": appt,
        }
    return out


def _counts(session: Session, slot_id, dock_id) -> dict[str, int]:
    confirmed = session.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.appointment_slot_id == slot_id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
    )
    held = session.scalar(
        select(func.count()).select_from(Appointment).where(
            Appointment.appointment_slot_id == slot_id,
            Appointment.status == AppointmentStatus.HELD,
        )
    )
    dock_appts = session.query(Appointment).filter(
        Appointment.dock_id == dock_id,
        Appointment.status.in_(_CONSUMING),
    ).all()
    return {"confirmed": int(confirmed or 0), "held": int(held or 0), "dock_consuming": len(dock_appts)}


def print_precheck(session: Session, item: dict[str, Any]) -> None:
    shipment = item["shipment"]
    slot = item["new_slot"]
    dock = item["dock"]
    facility = session.get(Facility, shipment.destination_facility_id)
    counts = _counts(session, slot.id, dock.id)
    available = (
        session.query(Dock)
        .filter_by(facility_id=facility.id, status=DockStatus.AVAILABLE)
        .order_by(Dock.name.asc())
        .all()
    )
    print("\n--- PRECHECK SHP-PHASE4-BOOK-001 ---")
    print("facility:", facility.name, facility.code, facility.status.value, facility.timezone)
    print("slot:", slot.id, slot.start_time.isoformat(), slot.end_time.isoformat())
    print("slot status:", slot.status.value)
    print("slot capacity:", slot.capacity)
    print("confirmed:", counts["confirmed"])
    print("held:", counts["held"])
    print("compatible docks:")
    for candidate in available:
        print(
            f"  {candidate.name} type={candidate.dock_type} status={candidate.status.value} "
            f"reefer={candidate.temperature_controlled} max_kg={candidate.max_weight_kg}"
        )
    print("book dock:", dock.name, dock.status.value, dock.dock_type)
    print("existing consuming appointments on book dock:", counts["dock_consuming"])
    print("shipment compatibility: dry van 8000kg / 10 pallets / active in_transit")
    print("proposal state: none (not created yet)")
    if slot.status != AppointmentSlotStatus.OPEN or slot.capacity != 1:
        raise SystemExit("Fixture slot is not OPEN capacity 1")
    if counts["confirmed"] or counts["held"]:
        raise SystemExit("Fixture slot already has consuming appointments")
    if dock.status != DockStatus.AVAILABLE or dock.dock_type != "standard":
        raise SystemExit("Fixture dock is not a compatible AVAILABLE standard dock")
    print("PRECHECK PASS: slot OPEN capacity 1 confirmed 0 held 0 compatible dock AVAILABLE")


def request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def chicago_label(iso_value: str) -> str:
    dt = datetime.fromisoformat(iso_value.replace("Z", "+00:00")).astimezone(TZ)
    return dt.strftime("%I:%M %p").lstrip("0") + " CDT"


def verify_flow(session: Session, item: dict[str, Any]) -> dict[str, Any]:
    shipment = item["shipment"]
    slot = item["new_slot"]
    driver = item["driver"]
    result: dict[str, Any] = {}

    print("\n--- SHOW get_available_options ---")
    code, created = request(
        "POST",
        "/conversations",
        {
            "driver_id": str(driver.id),
            "shipment_id": str(shipment.id),
            "subject": "phase4-book-clean-fixture",
        },
    )
    if code not in {200, 201}:
        raise SystemExit(f"create conversation failed {code} {created}")
    thread = created["thread_id"]
    code, turn = request("POST", f"/conversations/{thread}/messages", {"message": "What options do I have?"})
    if code != 200:
        raise SystemExit(f"options message failed {code} {turn}")
    options = (turn.get("metadata") or {}).get("presented_options") or []
    slot_ids = [str(item.get("slot_id")) for item in options]
    print("intent:", turn.get("intent"), "requires_human:", turn.get("requires_human"))
    print("option count:", len(options))
    print("new slot returned:", str(slot.id) in slot_ids)
    for option in options:
        start = option.get("start_time")
        end = option.get("end_time")
        local = f"{chicago_label(start)} – {chicago_label(end)}" if start and end else ""
        print("  option", option.get("index"), local, option.get("slot_id"))
        if str(option.get("slot_id")) == str(slot.id) and "1:00 PM" not in local:
            raise SystemExit(f"Chicago local time mismatch for new slot: {local}")
    session.expire_all()
    slot = session.get(AppointmentSlot, slot.id)
    confirmed_before = _counts(session, slot.id, item["dock"].id)
    print("after SHOW slot", slot.status.value, "confirmed", confirmed_before["confirmed"], "held", confirmed_before["held"])
    if str(slot.id) not in slot_ids:
        raise SystemExit("New fixture slot was not returned by get_available_options")
    if confirmed_before["confirmed"] or confirmed_before["held"] or slot.status != AppointmentSlotStatus.OPEN:
        raise SystemExit("SHOW mutated capacity")
    result["show"] = "PASS"

    print("\n--- PROPOSE ---")
    code, proposal = request(
        "POST",
        f"/shipments/{shipment.id}/proposals",
        {"appointment_slot_id": str(slot.id), "notes": "PHASE4-BOOK live e2e proposal"},
    )
    print("HTTP", code, json.dumps(proposal, default=str)[:500])
    if code not in {200, 201}:
        raise SystemExit(f"proposal create failed {code}")
    session.expire_all()
    slot = session.get(AppointmentSlot, slot.id)
    dock = session.get(Dock, item["dock"].id)
    counts = _counts(session, slot.id, dock.id)
    print("proposal status:", proposal.get("status"), "dock_id:", proposal.get("dock_id"))
    print("slot", slot.status.value, "dock", dock.status.value, "confirmed", counts["confirmed"])
    if proposal.get("status") != "proposed":
        raise SystemExit("proposal is not proposed")
    if slot.status != AppointmentSlotStatus.OPEN or counts["confirmed"] or dock.status != DockStatus.AVAILABLE:
        raise SystemExit("PROPOSE consumed capacity")
    result["propose"] = proposal
    result["proposal_id"] = proposal["proposal_id"]

    print("\n--- CONFIRM ---")
    code, accepted = request("POST", f"/proposals/{proposal['proposal_id']}/accept", {})
    print("HTTP", code, json.dumps(accepted, default=str)[:800])
    result["confirm_http"] = code
    result["confirm"] = accepted
    if code != 200:
        print("CONFIRM FAILED. Collecting allocation context.")
        return result

    session.expire_all()
    slot = session.get(AppointmentSlot, slot.id)
    dock = session.get(Dock, item["dock"].id)
    counts = _counts(session, slot.id, dock.id)
    current = [
        row
        for row in session.query(Appointment).filter_by(shipment_id=shipment.id).all()
        if row.status == AppointmentStatus.CONFIRMED and "STEP7_PROPOSAL" not in (row.notes or "")
    ]
    print("confirmed on slot:", counts["confirmed"])
    print("slot status:", slot.status.value)
    print("dock status:", dock.status.value)
    print("proposal status:", accepted.get("status"))
    print("appointment_id:", accepted.get("appointment_id"))
    print("current confirmed for shipment:", len(current), [str(row.id) for row in current])
    if counts["confirmed"] != 1 or slot.status != AppointmentSlotStatus.FULL:
        raise SystemExit("confirm did not consume slot capacity exactly once")
    if dock.status != DockStatus.OCCUPIED:
        raise SystemExit("confirm did not occupy the dedicated dock")
    if len(current) != 1:
        raise SystemExit("shipment does not have exactly one current confirmed appointment")
    result["appointment_id"] = accepted.get("appointment_id")
    result["final_slot_status"] = slot.status.value
    result["final_dock_status"] = dock.status.value
    result["final_confirmed"] = counts["confirmed"]
    return result


def main() -> None:
    assert_live_demo()
    session = SessionLocal()
    try:
        seeded = seed(session)
        session.commit()
        print("Inserted new rows:", seeded["created"] or "(already present; no updates)")
        book = seeded["items"]["book"]
        print_precheck(session, book)
        outcome = verify_flow(session, book)
        print("\n=== PHASE 4 CLEAN FIXTURE RESULT ===")
        print("BOOK shipment", book["shipment"].id, book["shipment"].shipment_number)
        print("RACE shipment", seeded["items"]["race"]["shipment"].shipment_number)
        print("RESCHEDULE shipment", seeded["items"]["reschedule"]["shipment"].shipment_number)
        print("confirm HTTP", outcome.get("confirm_http"))
        if outcome.get("confirm_http") != 200:
            sys.exit(2)
        print("CLEAN FIXTURE CONFIRM PASS")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
