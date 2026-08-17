"""Structure and invariant checks for the classroom ops seed (SQLite only)."""

from __future__ import annotations

from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentSlot, Driver, Facility, Shipment
from app.models.enums import AppointmentStatus
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.services.feasibility import FeasibilityService
from app.services.proposal import PROPOSAL_MARKER
from scripts.seed_ops_demo import (
    ETA_COMPETE,
    ETA_NOCAP,
    FORBIDDEN_DATABASE_NAMES,
    collect_seed_counts,
    seed_ops_demo,
)

CHI = ZoneInfo("America/Chicago")


def _local(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=CHI)
    return value.astimezone(CHI)


def _chicago(session: Session) -> Facility:
    return session.query(Facility).filter_by(code="CHI-XD").one()


def _shipment(session: Session, number: str) -> Shipment:
    return session.query(Shipment).filter_by(shipment_number=number).one()


def _slot(session: Session, facility: Facility, start_hour: int, start_minute: int, end_hour: int, end_minute: int) -> AppointmentSlot:
    slots = session.query(AppointmentSlot).filter_by(facility_id=facility.id).all()
    for slot in slots:
        start = _local(slot.start_time)
        end = _local(slot.end_time)
        if (
            start.hour == start_hour
            and start.minute == start_minute
            and end.hour == end_hour
            and end.minute == end_minute
        ):
            return slot
    raise AssertionError(f"missing slot {start_hour}:{start_minute}-{end_hour}:{end_minute}")


def test_forbidden_names_include_test_and_system_databases() -> None:
    assert "setuhaul_test" in FORBIDDEN_DATABASE_NAMES
    assert "postgres" in FORBIDDEN_DATABASE_NAMES
    assert "template0" in FORBIDDEN_DATABASE_NAMES
    assert "template1" in FORBIDDEN_DATABASE_NAMES
    assert "setuhaul" not in FORBIDDEN_DATABASE_NAMES


def test_seed_counts_are_classroom_sized(db_session: Session) -> None:
    seed_ops_demo(db_session)
    counts = collect_seed_counts(db_session)
    assert 15 <= counts["drivers"] <= 25
    assert 20 <= counts["shipments"] <= 40
    assert 2 <= counts["facilities"] <= 3
    assert 6 <= counts["docks"] <= 12
    assert 20 <= counts["slots"] <= 40
    assert counts["confirmed"] >= 1
    assert counts["proposals"] >= 1
    assert counts["cancelled"] >= 1
    assert counts["held"] == 0


def test_seed_is_idempotent(db_session: Session) -> None:
    first = seed_ops_demo(db_session)
    counts_one = collect_seed_counts(db_session)
    second = seed_ops_demo(db_session)
    counts_two = collect_seed_counts(db_session)
    assert first["race_proposal_id"] == second["race_proposal_id"]
    assert counts_one == counts_two
    assert db_session.query(Shipment).filter_by(shipment_number="SHP-DEMO-001").count() == 1


def test_hero_scarce_evening_capacity(db_session: Session) -> None:
    seed_ops_demo(db_session)
    chicago = _chicago(db_session)
    slot_1930 = _slot(db_session, chicago, 19, 30, 20, 30)
    slot_2000 = _slot(db_session, chicago, 20, 0, 20, 30)
    slot_wide = _slot(db_session, chicago, 20, 0, 21, 0)
    competing = ["SHP-DEMO-001", "SHP-DEMO-002", "SHP-DEMO-003", "SHP-DEMO-004", "SHP-DEMO-005"]
    assert all(db_session.query(Shipment).filter_by(shipment_number=number).count() == 1 for number in competing)
    remaining = 0
    service = FeasibilityService(db_session)
    alex = _shipment(db_session, "SHP-DEMO-001")
    for slot in (slot_1930, slot_2000, slot_wide):
        booked = (
            db_session.query(Appointment)
            .filter(
                Appointment.appointment_slot_id == slot.id,
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
            .count()
        )
        assert slot.capacity == 1
        remaining += max(slot.capacity - booked, 0)
        result = service.evaluate(alex.id, FeasibilityEvaluateRequest(appointment_slot_id=slot.id))
        assert result.feasible is True, result.blocking_reasons
    assert remaining == 3
    names = {row.name for row in db_session.query(Driver).all()}
    assert {"Alex Driver", "Priya Driver", "Ravi Driver", "Maya Driver", "Daniel Driver"} <= names


def test_proposals_do_not_consume_race_capacity(db_session: Session) -> None:
    seed_ops_demo(db_session)
    chicago = _chicago(db_session)
    slot = _slot(db_session, chicago, 20, 0, 20, 30)
    requested = (
        db_session.query(Appointment)
        .filter(
            Appointment.appointment_slot_id == slot.id,
            Appointment.status == AppointmentStatus.REQUESTED,
            Appointment.notes.contains(PROPOSAL_MARKER),
        )
        .count()
    )
    confirmed = (
        db_session.query(Appointment)
        .filter(
            Appointment.appointment_slot_id == slot.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .count()
    )
    assert requested >= 1
    assert confirmed == 0
    assert slot.capacity == 1


def test_reschedule_fixture_keeps_original_confirmed_only(db_session: Session) -> None:
    seed_ops_demo(db_session)
    shipment = _shipment(db_session, "SHP-DEMO-RESCHEDULE")
    confirmed = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .all()
    )
    assert len(confirmed) == 1
    slot = confirmed[0].appointment_slot
    assert slot is not None
    assert _local(slot.start_time).hour == 18
    assert _local(slot.start_time).minute == 30
    later = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.id != confirmed[0].id,
        )
        .count()
    )
    assert later == 0
    service = FeasibilityService(db_session)
    chicago = _chicago(db_session)
    target = _slot(db_session, chicago, 20, 30, 21, 0)
    result = service.evaluate(shipment.id, FeasibilityEvaluateRequest(appointment_slot_id=target.id))
    assert result.feasible is True, result.blocking_reasons


def test_nocap_has_no_feasible_open_slot(db_session: Session) -> None:
    seed_ops_demo(db_session)
    shipment = _shipment(db_session, "SHP-DEMO-NOCAP")
    latest = max(shipment.eta_updates, key=lambda item: item.update_timestamp)
    assert _local(latest.new_eta).hour == ETA_NOCAP.hour
    assert _local(latest.new_eta).minute == ETA_NOCAP.minute
    chicago = _chicago(db_session)
    service = FeasibilityService(db_session)
    feasible = 0
    for slot in db_session.query(AppointmentSlot).filter_by(facility_id=chicago.id).all():
        result = service.evaluate(shipment.id, FeasibilityEvaluateRequest(appointment_slot_id=slot.id))
        if result.feasible:
            feasible += 1
    assert feasible == 0


def test_concurrency_fixture_is_proposed_not_confirmed(db_session: Session) -> None:
    result = seed_ops_demo(db_session)
    shipment = _shipment(db_session, "SHP-DEMO-RACE")
    proposal = db_session.query(Appointment).filter_by(id=UUID(str(result["race_proposal_id"]))).one()
    assert proposal.status == AppointmentStatus.REQUESTED
    assert proposal.notes is not None and PROPOSAL_MARKER in proposal.notes
    assert "DEMO:RACE" in proposal.notes
    confirmed = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .count()
    )
    assert confirmed == 0
    slot = proposal.appointment_slot
    assert slot is not None
    assert slot.capacity == 1
    assert "stale" not in (proposal.notes or "").lower()
    assert "winner" not in (proposal.notes or "").lower()
    assert "loser" not in (proposal.notes or "").lower()


def test_dallas_hero_shipment_is_preserved(db_session: Session) -> None:
    seed_ops_demo(db_session)
    shipment = _shipment(db_session, "SH-1024")
    assert shipment.driver is not None
    assert shipment.driver.name == "Jane Rivera"
    requested = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.REQUESTED,
        )
        .count()
    )
    assert requested >= 1


def test_hero_eta_is_eight_pm(db_session: Session) -> None:
    seed_ops_demo(db_session)
    shipment = _shipment(db_session, "SHP-DEMO-001")
    latest = max(shipment.eta_updates, key=lambda item: item.update_timestamp)
    assert _local(latest.new_eta).hour == ETA_COMPETE.hour
    assert _local(latest.new_eta).minute == ETA_COMPETE.minute
