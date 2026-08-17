"""Idempotent E2E fixture reset for live/local acceptance validation.

Ensures deterministic, repeatable scenarios without DROP DATABASE or touching
unrelated production rows. Only updates/creates records tagged for E2E fixtures.

Run after base demo seed:
  python scripts/seed_ops_demo.py
  python scripts/seed_e2e_fixtures.py

Safe to re-run before every E2E / Playwright / hero script execution.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
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
from app.services.proposal import PROPOSAL_MARKER
from scripts.seed_ops_demo import (
    DEMO_DAY,
    ORIGINAL_END,
    ORIGINAL_START,
    SLOT_A_END,
    SLOT_A_START,
    SLOT_B_END,
    SLOT_B_START,
    SPC_SHIPMENT_NUMBER,
    _appointment,
    _driver,
    _ensure_eta,
    _shipment,
    _slot_at,
    _sync_slot_fill,
    _vehicle,
    assert_live_demo_target,
    reset_demo_spc_fixture,
    seed_ops_demo,
)
from scripts.seed_phase4_live_fixtures import (
    BOOK_ETA,
    BOOK_NEW,
    BOOK_ORIGINAL,
    RACE_ETA,
    RACE_NEW,
    RACE_ORIGINAL,
    RESCH_ETA,
    RESCH_NEW,
    RESCH_ORIGINAL,
    seed as seed_phase4,
)

TZ = ZoneInfo("America/Chicago")
_CONSUMING = tuple(AppointmentStatus(s) for s in CAPACITY_CONSUMING_APPOINTMENT_STATUSES)
_E2E_RESET = "E2E:reset-on-reseed"

# Dallas hero (scripts/e2e_hero_flow.py)
HERO_SHIPMENT_NUMBER = "SH-1024"
HERO_DRIVER_EXTERNAL_ID = "demo-driver-rivera"
SPC_DEMO_SHIPMENT = SPC_SHIPMENT_NUMBER

# Phase 4 Playwright fixtures
PHASE4_BOOK = "SHP-PHASE4-BOOK-001"
PHASE4_RACE = "SHP-PHASE4-RACE-001"
PHASE4_RESCHEDULE = "SHP-PHASE4-RESCHEDULE-001"

# Dedicated stale-proposal pair (same capacity-1 slot, two proposals)
STALE_WIN = "SHP-E2E-STALE-001"
STALE_LOSE = "SHP-E2E-STALE-002"
STALE_SLOT_START = DEMO_DAY.replace(hour=6, minute=0)
STALE_SLOT_END = DEMO_DAY.replace(hour=6, minute=30)
STALE_ETA = DEMO_DAY.replace(hour=6, minute=10)


def _shipment_by_number(session: Session, number: str) -> Shipment:
    row = session.query(Shipment).filter_by(shipment_number=number).one_or_none()
    if row is None:
        raise RuntimeError(f"Missing shipment {number!r}. Run scripts/seed_ops_demo.py first.")
    return row


def _cancel_consuming_on_slot(session: Session, slot: AppointmentSlot, *, keep_ids: set | None = None) -> int:
    keep_ids = keep_ids or set()
    count = 0
    for row in session.query(Appointment).filter(
        Appointment.appointment_slot_id == slot.id,
        Appointment.status.in_(_CONSUMING),
    ):
        if row.id in keep_ids:
            continue
        row.status = AppointmentStatus.CANCELLED
        row.notes = (row.notes or "") + f"\n{_E2E_RESET}"
        count += 1
    if count:
        _sync_slot_fill(session, slot)
    return count


def _cancel_shipment_extras(
    session: Session,
    shipment: Shipment,
    *,
    keep_notes_contains: tuple[str, ...] = (),
) -> None:
    for row in session.query(Appointment).filter_by(shipment_id=shipment.id).all():
        if any(tag in (row.notes or "") for tag in keep_notes_contains):
            continue
        if row.status in _CONSUMING or (
            row.status == AppointmentStatus.REQUESTED and PROPOSAL_MARKER in (row.notes or "")
        ):
            row.status = AppointmentStatus.CANCELLED
            row.notes = (row.notes or "") + f"\n{_E2E_RESET}"


def _release_dock(session: Session, dock: Dock | None) -> None:
    if dock is not None and dock.status == DockStatus.OCCUPIED:
        consuming = (
            session.query(Appointment)
            .filter(
                Appointment.dock_id == dock.id,
                Appointment.status.in_(_CONSUMING),
            )
            .count()
        )
        if consuming == 0:
            dock.status = DockStatus.AVAILABLE


def reset_hero_sh1024(session: Session) -> dict[str, Any]:
    """Restore Dallas classroom hero SH-1024 for a fresh booking walkthrough."""
    carrier = session.query(Carrier).filter_by(code="SETU-DEMO").one()
    facility = session.query(Facility).filter_by(code="DAL-DC").one()
    shipment = _shipment_by_number(session, HERO_SHIPMENT_NUMBER)
    driver = _driver(
        session,
        carrier,
        external_id=HERO_DRIVER_EXTERNAL_ID,
        name="Jane Rivera",
        phone="+155501024",
    )
    shipment.driver_id = driver.id
    shipment.status = ShipmentStatus.IN_TRANSIT
    shipment.is_active = True

    original_slot = _slot_at(session, facility.id, ORIGINAL_START, ORIGINAL_END, 1)
    alt_a = _slot_at(session, facility.id, SLOT_A_START, SLOT_A_END, 1)
    alt_b = _slot_at(session, facility.id, SLOT_B_START, SLOT_B_END, 1)
    dock_a = session.query(Dock).filter_by(facility_id=facility.id, name="Dock A").one()
    dock_b = session.query(Dock).filter_by(facility_id=facility.id, name="Dock B").one()

    _cancel_shipment_extras(session, shipment, keep_notes_contains=("Original 6:30 PM appointment",))

    original = (
        session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.notes.contains("Original 6:30 PM appointment"),
        )
        .one_or_none()
    )
    if original is None:
        original = Appointment(
            shipment_id=shipment.id,
            facility_id=facility.id,
            appointment_slot_id=original_slot.id,
            dock_id=dock_a.id,
            status=AppointmentStatus.REQUESTED,
            notes="Original 6:30 PM appointment",
        )
        session.add(original)
    else:
        original.status = AppointmentStatus.REQUESTED
        original.appointment_slot_id = original_slot.id
        original.dock_id = dock_a.id
        original.notes = "Original 6:30 PM appointment"

    for slot in (original_slot, alt_a, alt_b):
        _cancel_consuming_on_slot(session, slot)
        _sync_slot_fill(session, slot)
    for dock in (dock_a, dock_b):
        _release_dock(session, dock)

    session.flush()
    return {
        "shipment_number": HERO_SHIPMENT_NUMBER,
        "driver_external_id": HERO_DRIVER_EXTERNAL_ID,
        "facility_code": facility.code,
        "shipment_id": str(shipment.id),
        "driver_id": str(driver.id),
    }


def _reset_phase4_item(session: Session, key: str, item: dict[str, Any], spec: dict[str, Any]) -> None:
    shipment: Shipment = item["shipment"]
    original_slot: AppointmentSlot = item["original_slot"]
    new_slot: AppointmentSlot = item["new_slot"]
    dock: Dock = item["dock"]
    original_appt: Appointment = item["original_appointment"]

    _cancel_shipment_extras(session, shipment)
    _cancel_consuming_on_slot(session, new_slot)
    _release_dock(session, dock)

    original_appt.status = spec["original_status"]
    original_appt.appointment_slot_id = original_slot.id
    original_appt.notes = spec["original_notes"]
    if spec["original_status"] == AppointmentStatus.CONFIRMED:
        original_appt.dock_id = dock.id
        original_slot.status = AppointmentSlotStatus.FULL
        dock.status = DockStatus.OCCUPIED
    else:
        original_appt.dock_id = None

    new_slot.capacity = 1
    new_slot.status = AppointmentSlotStatus.OPEN
    _sync_slot_fill(session, new_slot)

    eta = item["eta"]
    eta.new_eta = spec["eta"]
    eta.previous_eta = spec["original"][0]
    eta.update_timestamp = datetime.now(tz=timezone.utc)
    eta.reason = spec["eta_reason"]


def reset_phase4_fixtures(session: Session) -> dict[str, Any]:
    """Re-create or reset Phase 4 browser/API fixtures to pre-consumption state."""
    seeded = seed_phase4(session)
    specs = {
        "book": {
            "original": BOOK_ORIGINAL,
            "eta": BOOK_ETA,
            "original_status": AppointmentStatus.REQUESTED,
            "original_notes": "PHASE4-BOOK original 12:00 PM appointment",
            "eta_reason": "PHASE4-BOOK dispatch ETA 1:15 PM",
        },
        "race": {
            "original": RACE_ORIGINAL,
            "eta": RACE_ETA,
            "original_status": AppointmentStatus.REQUESTED,
            "original_notes": "PHASE4-RACE original 7:00 AM appointment",
            "eta_reason": "PHASE4-RACE dispatch ETA 8:15 AM",
        },
        "reschedule": {
            "original": RESCH_ORIGINAL,
            "eta": RESCH_ETA,
            "original_status": AppointmentStatus.CONFIRMED,
            "original_notes": "PHASE4-RESCHEDULE original 9:00 AM confirmed appointment",
            "eta_reason": "PHASE4-RESCHEDULE driver ETA 1:00 PM; original 9:00 AM cannot be made",
        },
    }
    for key, spec in specs.items():
        _reset_phase4_item(session, key, seeded["items"][key], spec)

    return {
        "book": PHASE4_BOOK,
        "race": PHASE4_RACE,
        "reschedule": PHASE4_RESCHEDULE,
    }


def _proposal_notes(tag: str) -> str:
    return f"{PROPOSAL_MARKER}\n{tag}"


def ensure_stale_proposal_pair(session: Session) -> dict[str, Any]:
    """Two requested proposals on one capacity-1 slot; neither confirmed initially."""
    carrier = session.query(Carrier).filter_by(code="SETU-DEMO").one()
    chicago = session.query(Facility).filter_by(code="CHI-XD").one()
    stale_slot = _slot_at(session, chicago.id, STALE_SLOT_START, STALE_SLOT_END, 1)
    _cancel_consuming_on_slot(session, stale_slot)
    stale_slot.status = AppointmentSlotStatus.OPEN
    stale_slot.capacity = 1

    dock = (
        session.query(Dock)
        .filter_by(facility_id=chicago.id, name="Dock 0-P4-STALE")
        .one_or_none()
    )
    if dock is None:
        dock = Dock(
            facility_id=chicago.id,
            name="Dock 0-P4-STALE",
            dock_type="standard",
            max_weight_kg=Decimal("25000"),
            temperature_controlled=False,
            status=DockStatus.AVAILABLE,
        )
        session.add(dock)
        session.flush()
    else:
        dock.status = DockStatus.AVAILABLE

    specs = [
        (STALE_WIN, "e2e-stale-win-driver", "E2E Stale Winner", "E2E-STALE-WIN-VAN", "E2E:STALE winner proposal"),
        (STALE_LOSE, "e2e-stale-lose-driver", "E2E Stale Loser", "E2E-STALE-LOSE-VAN", "E2E:STALE loser proposal"),
    ]
    proposals: list[Appointment] = []
    shipments: list[Shipment] = []
    now = datetime.now(tz=timezone.utc)
    for number, ext, name, plate, tag in specs:
        driver = _driver(session, carrier, external_id=ext, name=name, phone="+1555405010")
        vehicle = _vehicle(session, carrier, license_plate=plate)
        shipment = _shipment(
            session,
            carrier,
            shipment_number=number,
            driver=driver,
            vehicle=vehicle,
            origin="Aurora, IL",
            destination="Chicago Cross-Dock",
            facility=chicago,
            status=ShipmentStatus.IN_TRANSIT,
            weight_kg="8500",
            pallet_count=10,
        )
        for row in session.query(Appointment).filter_by(shipment_id=shipment.id).all():
            row.status = AppointmentStatus.CANCELLED
            row.notes = (row.notes or "") + f"\n{_E2E_RESET}"
        _ensure_eta(
            session,
            shipment,
            new_eta=STALE_ETA,
            timestamp=DEMO_DAY.replace(hour=4, minute=30),
            source=ETASource.DISPATCH,
            reason=f"{tag} dispatch ETA",
        )
        proposal = Appointment(
            shipment_id=shipment.id,
            facility_id=chicago.id,
            appointment_slot_id=stale_slot.id,
            dock_id=dock.id,
            status=AppointmentStatus.REQUESTED,
            notes=_proposal_notes(tag),
            created_at=now,
            updated_at=now,
        )
        session.add(proposal)
        session.flush()
        proposals.append(proposal)
        shipments.append(shipment)
        proposals.append(proposal)
        shipments.append(shipment)

    _sync_slot_fill(session, stale_slot)
    session.flush()
    return {
        "slot_id": str(stale_slot.id),
        "winner_shipment": STALE_WIN,
        "loser_shipment": STALE_LOSE,
        "winner_proposal_id": str(proposals[0].id),
        "loser_proposal_id": str(proposals[1].id),
    }


def reset_demo_race_shipment(session: Session) -> dict[str, Any]:
    """Reset SHP-DEMO-RACE from seed_ops_demo for API concurrency script."""
    from scripts.seed_ops_demo import DEMO_RACE_NOTES

    shipment = _shipment_by_number(session, "SHP-DEMO-RACE")
    chicago = session.query(Facility).filter_by(code="CHI-XD").one()
    slot_2000 = None
    for existing in session.query(AppointmentSlot).filter_by(facility_id=chicago.id).all():
        start = existing.start_time.astimezone(TZ) if existing.start_time.tzinfo else existing.start_time.replace(tzinfo=TZ)
        end = existing.end_time.astimezone(TZ) if existing.end_time.tzinfo else existing.end_time.replace(tzinfo=TZ)
        if start.hour == 20 and start.minute == 0 and end.hour == 20 and end.minute == 30:
            slot_2000 = existing
            break
    if slot_2000 is None:
        raise RuntimeError("Chicago 20:00 slot missing from demo seed")

    dock_b = session.query(Dock).filter_by(facility_id=chicago.id, name="Dock B").one()
    _cancel_shipment_extras(session, shipment)
    _cancel_consuming_on_slot(session, slot_2000)

    for extra in (
        session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status.in_(_CONSUMING),
        )
        .all()
    ):
        extra.status = AppointmentStatus.CANCELLED
        extra.notes = (extra.notes or "") + f"\n{_E2E_RESET}"

    race_proposal = (
        session.query(Appointment)
        .filter(Appointment.shipment_id == shipment.id, Appointment.notes.contains("DEMO:RACE"))
        .one_or_none()
    )
    if race_proposal is None:
        race_proposal = Appointment(
            shipment_id=shipment.id,
            facility_id=chicago.id,
            appointment_slot_id=slot_2000.id,
            dock_id=dock_b.id,
            status=AppointmentStatus.REQUESTED,
            notes=DEMO_RACE_NOTES,
        )
        session.add(race_proposal)
    else:
        race_proposal.status = AppointmentStatus.REQUESTED
        race_proposal.appointment_slot_id = slot_2000.id
        race_proposal.dock_id = dock_b.id
        race_proposal.notes = DEMO_RACE_NOTES
    race_proposal.created_at = datetime.now(tz=timezone.utc)
    _sync_slot_fill(session, slot_2000)
    _release_dock(session, dock_b)
    session.flush()
    return {
        "shipment_number": "SHP-DEMO-RACE",
        "proposal_id": str(race_proposal.id),
        "slot_id": str(slot_2000.id),
    }


def seed_e2e_fixtures(session: Session) -> dict[str, Any]:
    seed_ops_demo(session)
    session.flush()
    result = {
        "hero": reset_hero_sh1024(session),
        "spc": reset_demo_spc_fixture(session),
        "phase4": reset_phase4_fixtures(session),
        "stale": ensure_stale_proposal_pair(session),
        "demo_race": reset_demo_race_shipment(session),
    }
    session.commit()
    return result


def print_report(result: dict[str, Any]) -> None:
    print()
    print("=" * 50)
    print("SETUHAUL E2E FIXTURES READY")
    print("=" * 50)
    hero = result["hero"]
    print(f"HERO  {hero['shipment_number']}  driver={hero['driver_external_id']}  facility={hero['facility_code']}")
    spc = result["spc"]
    print(
        f"SPC   {spc['shipment_number']}  driver={spc['driver_external_id']}  "
        f"facility={spc['facility_code']}"
    )
    phase4 = result["phase4"]
    print(f"PHASE4  book={phase4['book']}  race={phase4['race']}  reschedule={phase4['reschedule']}")
    stale = result["stale"]
    print(
        f"STALE  winner={stale['winner_shipment']}  loser={stale['loser_shipment']}  "
        f"slot={stale['slot_id']}"
    )
    race = result["demo_race"]
    print(f"DEMO RACE  {race['shipment_number']}  proposal={race['proposal_id']}")
    print()
    print("Re-run safe. No DROP DATABASE. Only E2E-tagged rows and the dedicated SPC demo fixture reset.")
    print("Unrelated operational history is preserved.")
    print("=" * 50)


def main() -> None:
    assert_live_demo_target()
    session = SessionLocal()
    try:
        result = seed_e2e_fixtures(session)
        print_report(result)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
