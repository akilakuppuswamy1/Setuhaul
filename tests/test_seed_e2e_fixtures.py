"""Structure checks for idempotent E2E fixture reset (SQLite only)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Appointment, Shipment
from app.models.enums import AppointmentStatus
from app.services.proposal import PROPOSAL_MARKER
from scripts.seed_e2e_fixtures import (
    HERO_SHIPMENT_NUMBER,
    PHASE4_RACE,
    STALE_LOSE,
    STALE_WIN,
    seed_e2e_fixtures,
)
from scripts.seed_ops_demo import seed_ops_demo


def test_e2e_reset_restores_hero_shipment(db_session: Session) -> None:
    seed_ops_demo(db_session)
    seed_e2e_fixtures(db_session)
    shipment = db_session.query(Shipment).filter_by(shipment_number=HERO_SHIPMENT_NUMBER).one()
    rows = db_session.query(Appointment).filter_by(shipment_id=shipment.id).all()
    originals = [row for row in rows if "Original 6:30 PM appointment" in (row.notes or "")]
    assert len(originals) == 1
    assert originals[0].status == AppointmentStatus.REQUESTED
    extras = [
        row
        for row in rows
        if row.status in {AppointmentStatus.CONFIRMED, AppointmentStatus.HELD}
        and "Original 6:30 PM appointment" not in (row.notes or "")
    ]
    assert not extras


def test_e2e_reset_phase4_race_is_unconsumed(db_session: Session) -> None:
    seed_ops_demo(db_session)
    result = seed_e2e_fixtures(db_session)
    shipment = db_session.query(Shipment).filter_by(shipment_number=PHASE4_RACE).one()
    confirmed = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .all()
    )
    assert not any("STEP7_PROPOSAL" not in (row.notes or "") for row in confirmed)
    proposals = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.REQUESTED,
            Appointment.notes.contains(PROPOSAL_MARKER),
        )
        .all()
    )
    assert len(proposals) == 0
    assert result["phase4"]["race"] == PHASE4_RACE


def test_e2e_stale_pair_has_two_proposals_one_slot(db_session: Session) -> None:
    seed_ops_demo(db_session)
    seed_e2e_fixtures(db_session)
    win = db_session.query(Shipment).filter_by(shipment_number=STALE_WIN).one()
    lose = db_session.query(Shipment).filter_by(shipment_number=STALE_LOSE).one()
    win_prop = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == win.id,
            Appointment.status == AppointmentStatus.REQUESTED,
            Appointment.notes.contains(PROPOSAL_MARKER),
        )
        .one()
    )
    lose_prop = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == lose.id,
            Appointment.status == AppointmentStatus.REQUESTED,
            Appointment.notes.contains(PROPOSAL_MARKER),
        )
        .one()
    )
    assert win_prop.appointment_slot_id == lose_prop.appointment_slot_id
    confirmed = (
        db_session.query(Appointment)
        .filter(
            Appointment.appointment_slot_id == win_prop.appointment_slot_id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .count()
    )
    assert confirmed == 0


def test_e2e_reset_is_idempotent(db_session: Session) -> None:
    seed_ops_demo(db_session)
    first = seed_e2e_fixtures(db_session)
    second = seed_e2e_fixtures(db_session)
    assert first["hero"]["shipment_id"] == second["hero"]["shipment_id"]
    assert first["stale"]["slot_id"] == second["stale"]["slot_id"]
