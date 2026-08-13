"""Tests for Step 2 SQLAlchemy domain models."""

from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401
from app.core.database import Base
from app.models import (
    Appointment,
    AppointmentSlot,
    Carrier,
    ChatMessage,
    ChatThread,
    Dock,
    Driver,
    DriverException,
    ETAUpdate,
    Facility,
    Shipment,
    Vehicle,
)
from app.models.enums import (
    AppointmentStatus,
    ETASource,
    ExceptionType,
    MessageDirection,
    SenderType,
    ShipmentStatus,
)
from scripts.seed_data import seed_demo_data

EXPECTED_TABLES = {
    "carriers",
    "drivers",
    "vehicles",
    "shipments",
    "eta_updates",
    "driver_exceptions",
    "facility_checkins",
    "facilities",
    "docks",
    "facility_rules",
    "appointment_slots",
    "appointments",
    "chat_threads",
    "chat_messages",
    "contacts",
    "operational_messages",
}


def test_models_import_correctly() -> None:
    assert Carrier.__tablename__ == "carriers"
    assert Shipment.__tablename__ == "shipments"
    assert Appointment.__tablename__ == "appointments"


def test_metadata_contains_all_intended_tables() -> None:
    table_names = set(Base.metadata.tables.keys())
    assert EXPECTED_TABLES.issubset(table_names)
    assert "alembic_version" not in table_names


def test_no_unexpected_domain_tables() -> None:
    table_names = set(Base.metadata.tables.keys())
    assert table_names == EXPECTED_TABLES


def test_driver_can_have_multiple_shipments(db_session) -> None:
    carrier = Carrier(name="Test Carrier", code="TST")
    driver = Driver(carrier=carrier, name="Multi Shipment Driver")
    db_session.add_all([carrier, driver])
    db_session.flush()

    shipments = [
        Shipment(
            carrier=carrier,
            driver=driver,
            shipment_number=f"MS-{index}",
            origin_location="Origin A",
            destination_location="Dest A",
            status=ShipmentStatus.ASSIGNED,
        )
        for index in range(2)
    ]
    db_session.add_all(shipments)
    db_session.commit()

    db_session.refresh(driver)
    assert len(driver.shipments) == 2
    assert {shipment.shipment_number for shipment in driver.shipments} == {"MS-0", "MS-1"}


def test_shipment_can_have_multiple_eta_updates(db_session) -> None:
    carrier = Carrier(name="ETA Carrier", code="ETA")
    shipment = Shipment(
        carrier=carrier,
        shipment_number="ETA-1",
        origin_location="A",
        destination_location="B",
    )
    db_session.add_all([carrier, shipment])
    db_session.flush()

    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    updates = [
        ETAUpdate(
            shipment=shipment,
            previous_eta=None,
            new_eta=now,
            update_timestamp=now - timedelta(hours=2),
            source=ETASource.SYSTEM,
        ),
        ETAUpdate(
            shipment=shipment,
            previous_eta=now,
            new_eta=now + timedelta(hours=1),
            update_timestamp=now - timedelta(hours=1),
            source=ETASource.DRIVER,
        ),
    ]
    db_session.add_all(updates)
    db_session.commit()

    db_session.refresh(shipment)
    assert len(shipment.eta_updates) == 2
    latest = shipment.eta_updates[-1]
    assert latest.source == ETASource.DRIVER
    assert latest.new_eta.replace(tzinfo=timezone.utc) == now + timedelta(hours=1)


def test_shipment_can_have_multiple_exceptions(db_session) -> None:
    carrier = Carrier(name="Exception Carrier", code="EXC")
    shipment = Shipment(
        carrier=carrier,
        shipment_number="EXC-1",
        origin_location="A",
        destination_location="B",
    )
    db_session.add_all([carrier, shipment])
    db_session.flush()

    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    exceptions = [
        DriverException(
            shipment=shipment,
            exception_type=ExceptionType.TRAFFIC,
            occurred_at=now,
        ),
        DriverException(
            shipment=shipment,
            exception_type=ExceptionType.DELAY,
            occurred_at=now + timedelta(minutes=30),
        ),
    ]
    db_session.add_all(exceptions)
    db_session.commit()

    db_session.refresh(shipment)
    assert len(shipment.exceptions) == 2


def test_shipment_can_have_appointment_history(db_session) -> None:
    carrier = Carrier(name="Appt Carrier", code="APT")
    facility = Facility(name="Test Facility", code="TF-01")
    slot = AppointmentSlot(
        facility=facility,
        start_time=datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc),
        capacity=1,
    )
    shipment = Shipment(
        carrier=carrier,
        shipment_number="APT-1",
        origin_location="A",
        destination_location="B",
        destination_facility=facility,
    )
    db_session.add_all([carrier, facility, slot, shipment])
    db_session.flush()

    appointments = [
        Appointment(
            shipment=shipment,
            facility=facility,
            appointment_slot=slot,
            status=AppointmentStatus.CANCELLED,
        ),
        Appointment(
            shipment=shipment,
            facility=facility,
            appointment_slot=slot,
            status=AppointmentStatus.CONFIRMED,
        ),
    ]
    db_session.add_all(appointments)
    db_session.commit()

    db_session.refresh(shipment)
    assert len(shipment.appointments) == 2
    statuses = {appointment.status for appointment in shipment.appointments}
    assert statuses == {AppointmentStatus.CANCELLED, AppointmentStatus.CONFIRMED}


def test_facility_can_have_multiple_docks(db_session) -> None:
    facility = Facility(name="Dock Facility", code="DF-01")
    docks = [
        Dock(facility=facility, name="D1", dock_type="standard"),
        Dock(facility=facility, name="D2", dock_type="reefer"),
    ]
    db_session.add_all([facility, *docks])
    db_session.commit()

    db_session.refresh(facility)
    assert len(facility.docks) == 2


def test_facility_can_have_multiple_appointment_slots(db_session) -> None:
    facility = Facility(name="Slot Facility", code="SF-01")
    slots = [
        AppointmentSlot(
            facility=facility,
            start_time=datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc),
            capacity=2,
        ),
        AppointmentSlot(
            facility=facility,
            start_time=datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 13, 11, 0, tzinfo=timezone.utc),
            capacity=2,
        ),
    ]
    db_session.add_all([facility, *slots])
    db_session.commit()

    db_session.refresh(facility)
    assert len(facility.appointment_slots) == 2


def test_chat_thread_can_contain_multiple_messages(db_session) -> None:
    carrier = Carrier(name="Chat Carrier", code="CHT")
    shipment = Shipment(
        carrier=carrier,
        shipment_number="CHT-1",
        origin_location="A",
        destination_location="B",
    )
    thread = ChatThread(shipment=shipment, subject="Ops chat")
    db_session.add_all([carrier, shipment, thread])
    db_session.flush()

    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    messages = [
        ChatMessage(
            thread=thread,
            sender_type=SenderType.DRIVER,
            content="First message",
            sent_at=now,
            direction=MessageDirection.INBOUND,
        ),
        ChatMessage(
            thread=thread,
            sender_type=SenderType.DISPATCHER,
            content="Second message",
            sent_at=now + timedelta(minutes=5),
            direction=MessageDirection.OUTBOUND,
        ),
    ]
    db_session.add_all(messages)
    db_session.commit()

    db_session.refresh(thread)
    assert len(thread.messages) == 2


def test_seed_data_represents_core_scenarios(db_session) -> None:
    data = seed_demo_data(db_session)

    assert len(data["drivers"]) == 2
    assert len(data["shipments"]) == 3
    assert len(data["docks"]) == 2
    assert len(data["slots"]) == 2
    assert len(data["appointments"]) == 2

    primary_shipment = data["shipments"][0]
    db_session.refresh(primary_shipment)
    assert len(primary_shipment.eta_updates) == 2
    assert len(primary_shipment.exceptions) == 1
    assert len(primary_shipment.appointments) == 2

    db_session.refresh(data["thread"])
    assert len(data["thread"].messages) == 2


def test_carrier_driver_vehicle_relationships(db_session) -> None:
    carrier = Carrier(name="Rel Carrier", code="REL")
    driver = Driver(carrier=carrier, name="Driver One")
    vehicle = Vehicle(carrier=carrier, license_plate="ABC123", vehicle_type="van")
    db_session.add_all([carrier, driver, vehicle])
    db_session.commit()

    db_session.refresh(carrier)
    assert carrier.drivers[0].name == "Driver One"
    assert carrier.vehicles[0].license_plate == "ABC123"
    assert driver.carrier.code == "REL"
