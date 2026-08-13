"""Step 2 hardening tests for schema integrity and imperfect operational data."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    Appointment,
    AppointmentSlot,
    Carrier,
    DriverException,
    ETAUpdate,
    Facility,
    FacilityRule,
    Shipment,
)
from app.models.enums import (
    AppointmentStatus,
    EntityStatus,
    ETASource,
    ExceptionStatus,
    ExceptionType,
)


def test_cancelled_appointment_remains_in_history(db_session) -> None:
    carrier = Carrier(name="Hist Carrier", code="HIST")
    facility = Facility(name="Hist Facility", code="HF-01")
    slot = AppointmentSlot(
        facility=facility,
        start_time=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc),
        capacity=1,
    )
    shipment = Shipment(
        carrier=carrier,
        shipment_number="HIST-1",
        origin_location="A",
        destination_location="B",
        destination_facility=facility,
    )
    cancelled = Appointment(
        shipment=shipment,
        facility=facility,
        appointment_slot=slot,
        status=AppointmentStatus.CANCELLED,
        notes="Cancelled due to delay",
    )
    db_session.add_all([carrier, facility, slot, shipment, cancelled])
    db_session.commit()

    cancelled_id = cancelled.id
    db_session.expire_all()

    persisted = db_session.get(Appointment, cancelled_id)
    assert persisted is not None
    assert persisted.status == AppointmentStatus.CANCELLED
    assert persisted.notes == "Cancelled due to delay"


def test_missing_optional_operational_fields_accepted(db_session) -> None:
    carrier = Carrier(name="Sparse Carrier", code="SPARSE")
    facility = Facility(name="Sparse Facility", code="SF-02")
    shipment = Shipment(
        carrier=carrier,
        shipment_number="SPARSE-1",
        origin_location="Unknown origin",
        destination_location="Unknown destination",
        driver_id=None,
        vehicle_id=None,
        weight_kg=None,
        volume_cbm=None,
        pallet_count=None,
        equipment_required=None,
        scheduled_pickup_at=None,
        scheduled_delivery_at=None,
    )
    appointment = Appointment(
        shipment=shipment,
        facility=facility,
        appointment_slot_id=None,
        dock_id=None,
        status=AppointmentStatus.REQUESTED,
    )
    db_session.add_all([carrier, facility, shipment, appointment])
    db_session.commit()

    db_session.refresh(shipment)
    db_session.refresh(appointment)
    assert shipment.driver_id is None
    assert shipment.vehicle_id is None
    assert appointment.dock_id is None
    assert appointment.appointment_slot_id is None


def test_shipment_without_eta_updates_represents_missing_eta(db_session) -> None:
    carrier = Carrier(name="No ETA Carrier", code="NOETA")
    shipment = Shipment(
        carrier=carrier,
        shipment_number="NOETA-1",
        origin_location="A",
        destination_location="B",
    )
    db_session.add_all([carrier, shipment])
    db_session.commit()

    db_session.refresh(shipment)
    assert shipment.eta_updates == []


def test_exception_without_delay_duration_accepted(db_session) -> None:
    carrier = Carrier(name="Exc Carrier", code="EXC2")
    shipment = Shipment(
        carrier=carrier,
        shipment_number="EXC2-1",
        origin_location="A",
        destination_location="B",
    )
    exception = DriverException(
        shipment=shipment,
        driver_id=None,
        exception_type=ExceptionType.DELAY,
        description=None,
        occurred_at=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
        resolved_at=None,
    )
    db_session.add_all([carrier, shipment, exception])
    db_session.commit()

    db_session.refresh(exception)
    assert exception.description is None
    assert exception.driver_id is None
    assert exception.resolved_at is None


def test_resolved_exception_remains_in_history(db_session) -> None:
    carrier = Carrier(name="Resolved Carrier", code="RES")
    shipment = Shipment(
        carrier=carrier,
        shipment_number="RES-1",
        origin_location="A",
        destination_location="B",
    )
    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    exception = DriverException(
        shipment=shipment,
        exception_type=ExceptionType.TRAFFIC,
        status=ExceptionStatus.RESOLVED,
        occurred_at=now,
        resolved_at=now + timedelta(hours=1),
    )
    db_session.add_all([carrier, shipment, exception])
    db_session.commit()

    exception_id = exception.id
    db_session.expire_all()
    persisted = db_session.get(DriverException, exception_id)
    assert persisted is not None
    assert persisted.status == ExceptionStatus.RESOLVED


def test_appointment_slot_end_must_be_after_start(db_session) -> None:
    facility = Facility(name="Slot Constraint Facility", code="SCF-01")
    invalid_slot = AppointmentSlot(
        facility=facility,
        start_time=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 13, 11, 0, tzinfo=timezone.utc),
        capacity=1,
    )
    db_session.add_all([facility, invalid_slot])
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_appointment_slot_capacity_must_be_non_negative(db_session) -> None:
    facility = Facility(name="Capacity Facility", code="CAP-01")
    invalid_slot = AppointmentSlot(
        facility=facility,
        start_time=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 13, 13, 0, tzinfo=timezone.utc),
        capacity=-1,
    )
    db_session.add_all([facility, invalid_slot])
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_facility_rule_effective_end_must_be_after_start(db_session) -> None:
    facility = Facility(name="Rule Facility", code="RULE-01")
    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    invalid_rule = FacilityRule(
        facility=facility,
        rule_type="operating_hours",
        rule_value={"open": "08:00", "close": "17:00"},
        effective_start=now,
        effective_end=now - timedelta(hours=1),
        is_active=True,
    )
    db_session.add_all([facility, invalid_rule])
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_facility_rule_json_round_trip(db_session) -> None:
    facility = Facility(name="JSON Facility", code="JSON-01")
    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    rule = FacilityRule(
        facility=facility,
        rule_type="dock_compatibility",
        rule_value={
            "allowed_vehicle_types": ["53ft_dry_van", "48ft_reefer"],
            "max_pallets": 24,
            "nested": {"enabled": True},
        },
        effective_start=now,
        is_active=True,
    )
    db_session.add_all([facility, rule])
    db_session.commit()

    db_session.refresh(rule)
    assert rule.rule_value["allowed_vehicle_types"] == ["53ft_dry_van", "48ft_reefer"]
    assert rule.rule_value["nested"]["enabled"] is True


def test_uuid_primary_keys_and_foreign_keys(db_session) -> None:
    carrier = Carrier(name="UUID Carrier", code="UUID")
    shipment = Shipment(
        carrier=carrier,
        shipment_number="UUID-1",
        origin_location="A",
        destination_location="B",
    )
    db_session.add_all([carrier, shipment])
    db_session.commit()

    assert isinstance(carrier.id, uuid.UUID)
    assert isinstance(shipment.id, uuid.UUID)
    assert isinstance(shipment.carrier_id, uuid.UUID)
    assert shipment.carrier_id == carrier.id


def test_enum_persistence_round_trip(db_session) -> None:
    carrier = Carrier(name="Enum Carrier", code="ENUM")
    db_session.add(carrier)
    db_session.commit()

    db_session.refresh(carrier)
    assert carrier.status == EntityStatus.ACTIVE
    assert carrier.status.value == "active"

    carrier.status = EntityStatus.INACTIVE
    db_session.commit()
    db_session.refresh(carrier)
    assert carrier.status == EntityStatus.INACTIVE


def test_conflicting_eta_corrections_preserved(db_session) -> None:
    carrier = Carrier(name="ETA Conflict Carrier", code="ETAC")
    shipment = Shipment(
        carrier=carrier,
        shipment_number="ETAC-1",
        origin_location="A",
        destination_location="B",
    )
    db_session.add_all([carrier, shipment])
    db_session.flush()

    base = datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)
    updates = [
        ETAUpdate(
            shipment=shipment,
            previous_eta=None,
            new_eta=base,
            update_timestamp=base - timedelta(hours=3),
            source=ETASource.DRIVER,
            reason="Driver estimate",
        ),
        ETAUpdate(
            shipment=shipment,
            previous_eta=base,
            new_eta=base + timedelta(hours=2),
            update_timestamp=base - timedelta(hours=2),
            source=ETASource.DISPATCH,
            reason="Dispatch correction",
        ),
        ETAUpdate(
            shipment=shipment,
            previous_eta=base + timedelta(hours=2),
            new_eta=base + timedelta(minutes=30),
            update_timestamp=base - timedelta(hours=1),
            source=ETASource.CARRIER,
            reason="Carrier correction",
        ),
    ]
    db_session.add_all(updates)
    db_session.commit()

    db_session.refresh(shipment)
    assert len(shipment.eta_updates) == 3
    sources = {update.source for update in shipment.eta_updates}
    assert sources == {ETASource.DRIVER, ETASource.DISPATCH, ETASource.CARRIER}
