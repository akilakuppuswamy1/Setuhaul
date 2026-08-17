"""Reschedule of an already-confirmed appointment via proposal accept."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
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
from app.schemas.proposal import ProposalCreateRequest, ProposalStatus
from app.services.allocation import AllocationService
from app.services.proposal import PROPOSAL_MARKER, ProposalService


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _build_reschedule_scenario(db_session: Session) -> dict[str, object]:
    now = _utc(2026, 8, 13, 10, 0)
    carrier = Carrier(
        name="Resched Carrier",
        code=f"RC-{uuid.uuid4().hex[:6]}",
        status=EntityStatus.ACTIVE,
    )
    driver = Driver(carrier=carrier, name="Alex Driver", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate=f"RS-{uuid.uuid4().hex[:4]}",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        status=EntityStatus.ACTIVE,
    )
    facility = Facility(
        name="Chicago Cross-Dock",
        code=f"CHI-{uuid.uuid4().hex[:6]}",
        timezone="UTC",
        status=EntityStatus.ACTIVE,
    )
    dock_a = Dock(
        facility=facility,
        name="Dock A",
        dock_type="standard",
        max_weight_kg=Decimal("25000"),
        status=DockStatus.AVAILABLE,
    )
    dock_b = Dock(
        facility=facility,
        name="Dock B",
        dock_type="standard",
        max_weight_kg=Decimal("25000"),
        status=DockStatus.AVAILABLE,
    )
    original_slot = AppointmentSlot(
        facility=facility,
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
        capacity=1,
        status=AppointmentSlotStatus.OPEN,
    )
    new_slot = AppointmentSlot(
        facility=facility,
        start_time=now + timedelta(hours=4),
        end_time=now + timedelta(hours=5),
        capacity=1,
        status=AppointmentSlotStatus.OPEN,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number=f"SHP-RS-{uuid.uuid4().hex[:4]}",
        origin_location="Milwaukee, WI",
        destination_location="Chicago Cross-Dock",
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("9000"),
        pallet_count=14,
    )
    db_session.add_all(
        [carrier, driver, vehicle, facility, dock_a, dock_b, original_slot, new_slot, shipment]
    )
    db_session.flush()
    shipment.destination_facility_id = facility.id
    db_session.add(
        ETAUpdate(
            shipment_id=shipment.id,
            previous_eta=None,
            new_eta=now + timedelta(hours=2, minutes=15),
            update_timestamp=now,
            source=ETASource.DISPATCH,
            reason="Original scheduled arrival",
        )
    )
    db_session.commit()

    original = AllocationService(db_session).allocate(
        shipment.id,
        AllocationRequest(
            appointment_slot_id=original_slot.id,
            dock_id=dock_a.id,
            evaluated_at=now,
        ),
    )
    db_session.add(
        ETAUpdate(
            shipment_id=shipment.id,
            previous_eta=now + timedelta(hours=2, minutes=15),
            new_eta=now + timedelta(hours=4, minutes=15),
            update_timestamp=now + timedelta(minutes=5),
            source=ETASource.DRIVER,
            reason="traffic / driver delay",
        )
    )
    db_session.commit()
    db_session.refresh(original_slot)
    db_session.refresh(new_slot)
    db_session.refresh(dock_a)
    db_session.refresh(dock_b)
    return {
        "now": now,
        "shipment": shipment,
        "original_slot": original_slot,
        "new_slot": new_slot,
        "dock_a": dock_a,
        "dock_b": dock_b,
        "original_appointment_id": original.appointment.id,
        "facility": facility,
    }


def _active_confirmed(db_session: Session, shipment_id: uuid.UUID) -> list[Appointment]:
    return list(
        db_session.scalars(
            select(Appointment)
            .where(Appointment.shipment_id == shipment_id)
            .where(Appointment.status.in_((AppointmentStatus.CONFIRMED, AppointmentStatus.HELD)))
            .order_by(Appointment.created_at.desc(), Appointment.id.desc())
        ).all()
    )


def _count_confirmed(db_session: Session, slot_id: uuid.UUID) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.appointment_slot_id == slot_id)
            .where(Appointment.status == AppointmentStatus.CONFIRMED)
        )
        or 0
    )


class TestConfirmedAppointmentReschedule:
    def test_confirmed_original_reschedule_succeeds(self, db_session: Session) -> None:
        data = _build_reschedule_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["new_slot"].id,
                dock_id=data["dock_b"].id,
            ),
        )
        assert created.status == ProposalStatus.PROPOSED
        assert created.appointment_id is None
        assert _count_confirmed(db_session, data["original_slot"].id) == 1
        assert _count_confirmed(db_session, data["new_slot"].id) == 0

        result = service.accept(created.proposal_id)
        assert result.status == ProposalStatus.CONFIRMED
        assert result.appointment_id is not None
        assert result.appointment_id != data["original_appointment_id"]

        original = db_session.get(Appointment, data["original_appointment_id"])
        booked = db_session.get(Appointment, result.appointment_id)
        assert original is not None
        assert booked is not None
        assert original.status == AppointmentStatus.CANCELLED
        assert original.appointment_slot_id == data["original_slot"].id
        assert f"superseded_by={booked.id}" in (original.notes or "")
        assert booked.status == AppointmentStatus.CONFIRMED
        assert booked.appointment_slot_id == data["new_slot"].id
        assert booked.dock_id == data["dock_b"].id
        assert booked.id != original.id

        active = _active_confirmed(db_session, data["shipment"].id)
        assert len(active) == 1
        assert active[0].id == booked.id

        db_session.refresh(data["original_slot"])
        db_session.refresh(data["new_slot"])
        db_session.refresh(data["dock_a"])
        db_session.refresh(data["dock_b"])
        assert data["original_slot"].status == AppointmentSlotStatus.OPEN
        assert data["new_slot"].status == AppointmentSlotStatus.FULL
        assert data["dock_a"].status == DockStatus.AVAILABLE
        assert data["dock_b"].status == DockStatus.OCCUPIED
        assert _count_confirmed(db_session, data["original_slot"].id) == 0
        assert _count_confirmed(db_session, data["new_slot"].id) == 1

    def test_original_remains_queryable_history(self, db_session: Session) -> None:
        data = _build_reschedule_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["new_slot"].id,
                dock_id=data["dock_b"].id,
            ),
        )
        service.accept(created.proposal_id)
        listed, total = (
            db_session.query(Appointment)
            .filter(Appointment.shipment_id == data["shipment"].id)
            .all(),
            db_session.query(Appointment)
            .filter(Appointment.shipment_id == data["shipment"].id)
            .count(),
        )
        original = db_session.get(Appointment, data["original_appointment_id"])
        assert original in listed
        assert original.status == AppointmentStatus.CANCELLED
        assert total >= 3

    def test_allocation_failure_rolls_back_reschedule(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = _build_reschedule_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["new_slot"].id,
                dock_id=data["dock_b"].id,
            ),
        )
        original_supersede = AllocationService._supersede_active

        def fail_after_supersede(self: AllocationService, existing: Appointment) -> None:
            original_supersede(self, existing)
            raise ConflictError("forced allocation failure after supersede")

        monkeypatch.setattr(AllocationService, "_supersede_active", fail_after_supersede)
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)

        original = db_session.get(Appointment, data["original_appointment_id"])
        assert original is not None
        assert original.status == AppointmentStatus.CONFIRMED
        assert original.appointment_slot_id == data["original_slot"].id
        db_session.refresh(data["original_slot"])
        db_session.refresh(data["new_slot"])
        db_session.refresh(data["dock_a"])
        db_session.refresh(data["dock_b"])
        assert data["original_slot"].status == AppointmentSlotStatus.FULL
        assert data["new_slot"].status == AppointmentSlotStatus.OPEN
        assert data["dock_a"].status == DockStatus.OCCUPIED
        assert data["dock_b"].status == DockStatus.AVAILABLE
        assert _count_confirmed(db_session, data["original_slot"].id) == 1
        assert _count_confirmed(db_session, data["new_slot"].id) == 0
        assert len(_active_confirmed(db_session, data["shipment"].id)) == 1

    def test_sequential_retry_returns_same_confirmed_appointment(self, db_session: Session) -> None:
        data = _build_reschedule_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["new_slot"].id,
                dock_id=data["dock_b"].id,
            ),
        )
        first = service.accept(created.proposal_id)
        second = service.accept(created.proposal_id)
        assert second.status == ProposalStatus.CONFIRMED
        assert second.appointment_id == first.appointment_id
        assert len(_active_confirmed(db_session, data["shipment"].id)) == 1
        assert _count_confirmed(db_session, data["new_slot"].id) == 1

    def test_proposal_create_does_not_duplicate_confirmed(self, db_session: Session) -> None:
        data = _build_reschedule_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["new_slot"].id,
                dock_id=data["dock_b"].id,
            ),
        )
        proposal_row = db_session.get(Appointment, created.proposal_id)
        assert proposal_row is not None
        assert proposal_row.status == AppointmentStatus.REQUESTED
        assert PROPOSAL_MARKER in (proposal_row.notes or "")
        assert _count_confirmed(db_session, data["new_slot"].id) == 0
        assert len(_active_confirmed(db_session, data["shipment"].id)) == 1

        service.accept(created.proposal_id)
        confirmed = _active_confirmed(db_session, data["shipment"].id)
        assert len(confirmed) == 1
        assert confirmed[0].appointment_slot_id == data["new_slot"].id
        assert _count_confirmed(db_session, data["new_slot"].id) == 1

    def test_direct_allocate_still_rejects_active_duplicate(self, db_session: Session) -> None:
        data = _build_reschedule_scenario(db_session)
        with pytest.raises(ConflictError, match="already has an active allocation"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["new_slot"].id,
                    dock_id=data["dock_b"].id,
                    evaluated_at=data["now"],
                ),
            )
        assert _count_confirmed(db_session, data["original_slot"].id) == 1
        assert _count_confirmed(db_session, data["new_slot"].id) == 0
