"""Step 6 allocation service and API tests."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError
from app.engines.feasibility.models import FeasibilityOutcome
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
from app.repositories.appointment import AppointmentRepository
from app.schemas.allocation import AllocationRequest
from app.services.allocation import AllocationService
from app.services.feasibility import FeasibilityService


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _build_allocation_scenario(
    db_session: Session,
    *,
    slot_capacity: int = 5,
    shipment_number: str = "ALLOC-SHP-1",
    include_eta: bool = True,
    dock_status: DockStatus = DockStatus.AVAILABLE,
    slot_status: AppointmentSlotStatus = AppointmentSlotStatus.OPEN,
) -> dict[str, object]:
    """Build a shipment ready for allocation without an existing active appointment."""
    now = _utc(2026, 8, 13, 10, 0)
    carrier = Carrier(name="Alloc Carrier", code=f"AC-{uuid.uuid4().hex[:6]}", status=EntityStatus.ACTIVE)
    driver = Driver(carrier=carrier, name="Alloc Driver", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate=f"AL-{uuid.uuid4().hex[:4]}",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        max_volume_cbm=Decimal("90"),
        status=EntityStatus.ACTIVE,
    )
    facility = Facility(
        name="Alloc Facility",
        code=f"AF-{uuid.uuid4().hex[:6]}",
        timezone="UTC",
        status=EntityStatus.ACTIVE,
    )
    dock = Dock(
        facility=facility,
        name="Dock A",
        dock_type="standard",
        max_weight_kg=Decimal("25000"),
        status=dock_status,
    )
    slot = AppointmentSlot(
        facility=facility,
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
        capacity=slot_capacity,
        status=slot_status,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number=shipment_number,
        origin_location="Origin",
        destination_location="Alloc Facility",
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("8000"),
        volume_cbm=Decimal("30"),
        pallet_count=12,
    )
    db_session.add_all([carrier, driver, vehicle, facility, dock, slot, shipment])
    db_session.flush()
    shipment.destination_facility_id = facility.id

    if include_eta:
        db_session.add(
            ETAUpdate(
                shipment_id=shipment.id,
                previous_eta=None,
                new_eta=now + timedelta(hours=2, minutes=15),
                update_timestamp=now,
                source=ETASource.DISPATCH,
            )
        )

    db_session.commit()
    return {
        "shipment": shipment,
        "slot": slot,
        "dock": dock,
        "facility": facility,
        "carrier": carrier,
        "now": now,
    }


def _add_shipment_to_facility(
    db_session: Session,
    facility: Facility,
    *,
    shipment_number: str,
    now: datetime | None = None,
) -> Shipment:
    """Add another feasible shipment at the same facility."""
    now = now or _utc(2026, 8, 13, 10, 0)
    carrier = db_session.get(Carrier, facility.id)  # type: ignore[arg-type]
    # Reuse carrier from an existing shipment at this facility
    existing = db_session.scalar(
        select(Shipment).where(Shipment.destination_facility_id == facility.id).limit(1)
    )
    assert existing is not None
    carrier = existing.carrier
    driver = Driver(carrier=carrier, name=f"Driver {shipment_number}", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate=f"V-{shipment_number}",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        status=EntityStatus.ACTIVE,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number=shipment_number,
        origin_location="Origin",
        destination_location=facility.name,
        destination_facility_id=facility.id,
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("5000"),
        pallet_count=10,
    )
    db_session.add_all([driver, vehicle, shipment])
    db_session.flush()
    db_session.add(
        ETAUpdate(
            shipment_id=shipment.id,
            previous_eta=None,
            new_eta=now + timedelta(hours=2, minutes=15),
            update_timestamp=now,
            source=ETASource.DISPATCH,
        )
    )
    db_session.commit()
    return shipment


def _count_appointments(db_session: Session, slot_id: uuid.UUID) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.appointment_slot_id == slot_id)
            .where(
                Appointment.status.in_(
                    [AppointmentStatus.CONFIRMED, AppointmentStatus.HELD]
                )
            )
        )
        or 0
    )


class TestAllocationService:
    def test_successful_allocation(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        result = AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
                evaluated_at=data["now"],
            ),
        )
        assert result.success is True
        assert result.appointment is not None
        assert result.appointment.status == AppointmentStatus.CONFIRMED
        assert result.appointment_slot is not None
        assert result.dock is not None
        assert result.feasibility is not None
        assert result.feasibility.feasible is True
        assert _count_appointments(db_session, data["slot"].id) == 1

    def test_deterministic_slot_selection(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        now = data["now"]
        facility = data["facility"]
        db_session.delete(data["slot"])
        db_session.flush()
        earlier = AppointmentSlot(
            facility_id=facility.id,
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=3),
            capacity=3,
            status=AppointmentSlotStatus.OPEN,
        )
        later = AppointmentSlot(
            facility_id=facility.id,
            start_time=now + timedelta(hours=4),
            end_time=now + timedelta(hours=5),
            capacity=3,
            status=AppointmentSlotStatus.OPEN,
        )
        db_session.add_all([earlier, later])
        db_session.commit()

        result = AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(evaluated_at=now),
        )
        assert result.success is True
        assert result.appointment_slot is not None
        assert result.appointment_slot.id == earlier.id

    def test_infeasible_shipment_rejected(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, include_eta=False)
        with pytest.raises(SetuHaulError, match="not evaluable|not feasible"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )
        assert _count_appointments(db_session, data["slot"].id) == 0

    def test_missing_shipment(self, db_session: Session) -> None:
        with pytest.raises(NotFoundError):
            AllocationService(db_session).allocate(uuid.uuid4())

    def test_missing_slot(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        with pytest.raises(NotFoundError, match="slot"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(appointment_slot_id=uuid.uuid4()),
            )

    def test_missing_dock(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        with pytest.raises(NotFoundError, match="Dock"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    dock_id=uuid.uuid4(),
                ),
            )

    def test_unavailable_slot_closed(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, slot_status=AppointmentSlotStatus.CLOSED)
        with pytest.raises(ConflictError, match="not available"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(appointment_slot_id=data["slot"].id),
            )

    def test_unavailable_dock(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, dock_status=DockStatus.OCCUPIED)
        with pytest.raises(ConflictError, match="not available"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    dock_id=data["dock"].id,
                ),
            )

    def test_at_capacity_rejected(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, slot_capacity=1)
        other = _add_shipment_to_facility(
            db_session, data["facility"], shipment_number="ALLOC-SHP-2", now=data["now"]
        )
        AllocationService(db_session).allocate(
            other.id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        with pytest.raises(ConflictError, match="capacity exhausted|not available"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )

    def test_duplicate_shipment_allocation_rejected(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        service = AllocationService(db_session)
        service.allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        with pytest.raises(ConflictError, match="already has an active allocation"):
            service.allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )

    def test_slot_marked_full_at_capacity(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, slot_capacity=1)
        AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        db_session.refresh(data["slot"])
        assert data["slot"].status == AppointmentSlotStatus.FULL

    def test_dock_marked_occupied(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
                evaluated_at=data["now"],
            ),
        )
        db_session.refresh(data["dock"])
        assert data["dock"].status == DockStatus.OCCUPIED

    def test_failed_allocation_leaves_no_partial_state(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, include_eta=False)
        before_appts = db_session.scalar(select(func.count()).select_from(Appointment))
        with pytest.raises(SetuHaulError):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(appointment_slot_id=data["slot"].id),
            )
        after_appts = db_session.scalar(select(func.count()).select_from(Appointment))
        assert before_appts == after_appts

    def test_session_usable_after_failed_allocation(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, include_eta=False)
        with pytest.raises(SetuHaulError):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(appointment_slot_id=data["slot"].id),
            )
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        assert result.outcome in (
            FeasibilityOutcome.NOT_EVALUABLE,
            FeasibilityOutcome.NOT_FEASIBLE,
        )

    def test_eta_history_untouched(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        before = db_session.scalar(select(func.count()).select_from(ETAUpdate))
        AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        after = db_session.scalar(select(func.count()).select_from(ETAUpdate))
        assert before == after


class TestAllocationAPI:
    def test_allocate_endpoint_success(self, db_session: Session, client: TestClient) -> None:
        data = _build_allocation_scenario(db_session)
        response = client.post(
            f"/shipments/{data['shipment'].id}/allocate",
            json={
                "appointment_slot_id": str(data["slot"].id),
                "dock_id": str(data["dock"].id),
                "evaluated_at": data["now"].isoformat(),
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["appointment"]["status"] == "confirmed"
        assert "traceback" not in response.text.lower()

    def test_allocate_not_found(self, client: TestClient) -> None:
        response = client.post(
            f"/shipments/{uuid.uuid4()}/allocate",
            json={},
        )
        assert response.status_code == 404

    def test_allocate_conflict_returns_409(self, db_session: Session, client: TestClient) -> None:
        data = _build_allocation_scenario(db_session, slot_capacity=1)
        other = _add_shipment_to_facility(
            db_session, data["facility"], shipment_number="ALLOC-SHP-API-2", now=data["now"]
        )
        client.post(
            f"/shipments/{other.id}/allocate",
            json={
                "appointment_slot_id": str(data["slot"].id),
                "evaluated_at": data["now"].isoformat(),
            },
        )
        response = client.post(
            f"/shipments/{data['shipment'].id}/allocate",
            json={
                "appointment_slot_id": str(data["slot"].id),
                "evaluated_at": data["now"].isoformat(),
            },
        )
        assert response.status_code == 409

    def test_allocate_infeasible_returns_400(self, db_session: Session, client: TestClient) -> None:
        data = _build_allocation_scenario(db_session, include_eta=False)
        response = client.post(
            f"/shipments/{data['shipment'].id}/allocate",
            json={"appointment_slot_id": str(data["slot"].id)},
        )
        assert response.status_code == 400


class TestAllocationDeterminism:
    def test_repeated_allocation_same_inputs_same_slot(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        results = []
        for i in range(2):
            shipment = _add_shipment_to_facility(
                db_session,
                data["facility"],
                shipment_number=f"DET-SHP-{i}",
                now=data["now"],
            )
            result = AllocationService(db_session).allocate(
                shipment.id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )
            results.append(result.appointment_slot.id)
        assert results[0] == results[1]

    def test_stable_conflict_on_full_slot(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, slot_capacity=1)
        filler = _add_shipment_to_facility(
            db_session, data["facility"], shipment_number="FILL-SHP", now=data["now"]
        )
        AllocationService(db_session).allocate(
            filler.id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        conflicts = []
        for i in range(2):
            reject = _add_shipment_to_facility(
                db_session,
                data["facility"],
                shipment_number=f"REJ-SHP-{i}",
                now=data["now"],
            )
            try:
                AllocationService(db_session).allocate(
                    reject.id,
                    AllocationRequest(
                        appointment_slot_id=data["slot"].id,
                        evaluated_at=data["now"],
                    ),
                )
            except ConflictError as exc:
                conflicts.append(str(exc))
        assert len(conflicts) == 2
        assert conflicts[0] == conflicts[1]


class TestAllocationInvariants:
    def test_allocation_references_valid_entities(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        result = AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
                evaluated_at=data["now"],
            ),
        )
        appt = db_session.get(Appointment, result.appointment.id)
        assert appt is not None
        assert appt.shipment_id == data["shipment"].id
        assert appt.appointment_slot_id == data["slot"].id
        assert appt.dock_id == data["dock"].id
        assert appt.facility_id == data["facility"].id

    def test_capacity_not_exceeded(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, slot_capacity=2)
        for i in range(2):
            shipment = _add_shipment_to_facility(
                db_session,
                data["facility"],
                shipment_number=f"CAP-SHP-{i}",
                now=data["now"],
            )
            AllocationService(db_session).allocate(
                shipment.id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )
        assert _count_appointments(db_session, data["slot"].id) == 2
        db_session.refresh(data["slot"])
        assert data["slot"].status == AppointmentSlotStatus.FULL
