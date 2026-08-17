"""Deterministic tests for first-successful-confirm (FCFS-style) allocation.

These cases document current policy. They do not add priority scoring,
carrier ranking, perishable rules, or commercial penalties.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.models import Appointment, AppointmentSlot, Carrier, Dock, Driver, ETAUpdate, Facility, Shipment, Vehicle
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    DockStatus,
    EntityStatus,
    ETASource,
    ShipmentStatus,
)
from app.schemas.allocation import AllocationRequest
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.schemas.proposal import ProposalCreateRequest, ProposalStatus
from app.services.allocation import AllocationService
from app.services.feasibility import FeasibilityService
from app.services.proposal import ProposalService


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _world(session: Session) -> dict:
    now = _utc(2026, 8, 13, 10, 0)
    carrier = Carrier(name="FCFS Carrier", code=f"FCFS-{uuid4().hex[:6]}", status=EntityStatus.ACTIVE)
    facility = Facility(
        name="FCFS Facility",
        code=f"FCFS-F-{uuid4().hex[:6]}",
        timezone="UTC",
        status=EntityStatus.ACTIVE,
    )
    dock = Dock(
        facility=facility,
        name="Dock A",
        dock_type="standard",
        max_weight_kg=Decimal("25000"),
        status=DockStatus.AVAILABLE,
    )
    slot = AppointmentSlot(
        facility=facility,
        start_time=now + timedelta(hours=3),
        end_time=now + timedelta(hours=4),
        capacity=1,
        status=AppointmentSlotStatus.OPEN,
    )
    session.add_all([carrier, facility, dock, slot])
    session.flush()
    return {"now": now, "carrier": carrier, "facility": facility, "dock": dock, "slot": slot}


def _shipment(session: Session, world: dict, label: str) -> Shipment:
    driver = Driver(
        carrier=world["carrier"],
        name=f"Driver {label}",
        status=EntityStatus.ACTIVE,
    )
    vehicle = Vehicle(
        carrier=world["carrier"],
        license_plate=f"FCFS-{label}-{uuid4().hex[:4]}",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        status=EntityStatus.ACTIVE,
    )
    shipment = Shipment(
        carrier=world["carrier"],
        driver=driver,
        vehicle=vehicle,
        shipment_number=f"FCFS-{label}-{uuid4().hex[:4]}",
        origin_location="Origin",
        destination_location="Facility",
        destination_facility_id=world["facility"].id,
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("8000"),
        pallet_count=10,
    )
    eta = ETAUpdate(
        shipment=shipment,
        previous_eta=None,
        new_eta=world["slot"].start_time + timedelta(minutes=10),
        update_timestamp=world["now"],
        source=ETASource.DISPATCH,
        reason=f"FCFS {label}",
    )
    session.add_all([driver, vehicle, shipment, eta])
    session.flush()
    return shipment


def test_show_does_not_reserve_slot_then_confirm_loses_after_capacity_drop(db_session: Session) -> None:
    """Facility capacity drops after SHOW: first successful confirm still wins."""
    world = _world(db_session)
    first = _shipment(db_session, world, "A")
    rival = _shipment(db_session, world, "B")
    feasibility = FeasibilityService(db_session)
    shown = feasibility.evaluate(
        first.id,
        FeasibilityEvaluateRequest(appointment_slot_id=world["slot"].id, evaluated_at=world["now"]),
    )
    assert shown.feasible is True
    consuming = (
        db_session.query(Appointment)
        .filter(
            Appointment.appointment_slot_id == world["slot"].id,
            Appointment.status.in_([AppointmentStatus.CONFIRMED, AppointmentStatus.HELD]),
        )
        .count()
    )
    assert consuming == 0

    created = ProposalService(db_session).create(
        first.id,
        ProposalCreateRequest(appointment_slot_id=world["slot"].id),
    )
    AllocationService(db_session).allocate(
        rival.id,
        AllocationRequest(appointment_slot_id=world["slot"].id, evaluated_at=world["now"]),
    )
    try:
        ProposalService(db_session).accept(created.proposal_id)
        raise AssertionError("stale confirm must not succeed after SHOW-time capacity was taken")
    except ConflictError:
        fetched = ProposalService(db_session).get(created.proposal_id)
        assert fetched.status == ProposalStatus.STALE


def test_later_shipment_does_not_outrank_first_successful_confirm(db_session: Session) -> None:
    """No priority field: a later shipment that confirms first wins the slot."""
    world = _world(db_session)
    early = _shipment(db_session, world, "EARLY")
    later = _shipment(db_session, world, "LATER")
    early_proposal = ProposalService(db_session).create(
        early.id,
        ProposalCreateRequest(appointment_slot_id=world["slot"].id),
    )
    later_proposal = ProposalService(db_session).create(
        later.id,
        ProposalCreateRequest(appointment_slot_id=world["slot"].id),
    )
    accepted = ProposalService(db_session).accept(later_proposal.proposal_id)
    assert accepted.status == ProposalStatus.CONFIRMED
    try:
        ProposalService(db_session).accept(early_proposal.proposal_id)
        raise AssertionError("earlier proposal must not preempt first successful confirm")
    except ConflictError:
        stale = ProposalService(db_session).get(early_proposal.proposal_id)
        assert stale.status == ProposalStatus.STALE
    confirmed = (
        db_session.query(Appointment)
        .filter(
            Appointment.appointment_slot_id == world["slot"].id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .all()
    )
    assert len(confirmed) == 1
    assert confirmed[0].shipment_id == later.id
