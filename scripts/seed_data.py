"""Deterministic seed dataset for validating Step 2 domain models."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Appointment,
    AppointmentSlot,
    Carrier,
    ChatMessage,
    ChatThread,
    Contact,
    Dock,
    Driver,
    DriverException,
    ETAUpdate,
    Facility,
    FacilityCheckin,
    FacilityRule,
    OperationalMessage,
    Shipment,
    Vehicle,
)
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    CheckinType,
    ChatThreadStatus,
    ContactType,
    DockStatus,
    EntityStatus,
    ETASource,
    ExceptionStatus,
    ExceptionType,
    MessageChannel,
    MessageDirection,
    OperationalMessageStatus,
    SenderType,
    ShipmentStatus,
)


def seed_demo_data(session: Session) -> dict[str, object]:
    """Insert a small deterministic dataset and return key entity references."""
    now = datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)

    carrier = Carrier(name="Acme Logistics", code="ACME", status=EntityStatus.ACTIVE)
    session.add(carrier)
    session.flush()

    drivers = [
        Driver(carrier_id=carrier.id, name="Jane Rivera", phone="+15550001"),
        Driver(carrier_id=carrier.id, name="Sam Patel", phone="+15550002"),
    ]
    vehicles = [
        Vehicle(
            carrier_id=carrier.id,
            license_plate="TRK-101",
            vehicle_type="53ft_dry_van",
            max_weight_kg=Decimal("20000"),
            max_volume_cbm=Decimal("90"),
        ),
        Vehicle(
            carrier_id=carrier.id,
            license_plate="TRK-202",
            vehicle_type="48ft_reefer",
            max_weight_kg=Decimal("18000"),
        ),
    ]
    session.add_all(drivers + vehicles)
    session.flush()

    facility = Facility(
        name="Central Receiving DC",
        code="CRDC-01",
        address="100 Warehouse Blvd",
        timezone="America/Chicago",
        status=EntityStatus.ACTIVE,
    )
    session.add(facility)
    session.flush()

    docks = [
        Dock(
            facility_id=facility.id,
            name="Dock A",
            dock_type="standard",
            max_weight_kg=Decimal("25000"),
            status=DockStatus.AVAILABLE,
        ),
        Dock(
            facility_id=facility.id,
            name="Dock B",
            dock_type="reefer",
            temperature_controlled=True,
            status=DockStatus.AVAILABLE,
        ),
    ]
    session.add_all(docks)
    session.flush()

    rule = FacilityRule(
        facility_id=facility.id,
        rule_type="max_daily_appointments",
        rule_value={"limit": 50},
        effective_start=now - timedelta(days=30),
        is_active=True,
    )
    session.add(rule)

    slots = [
        AppointmentSlot(
            facility_id=facility.id,
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=3),
            capacity=3,
            status=AppointmentSlotStatus.OPEN,
        ),
        AppointmentSlot(
            facility_id=facility.id,
            start_time=now + timedelta(hours=4),
            end_time=now + timedelta(hours=5),
            capacity=2,
            status=AppointmentSlotStatus.OPEN,
        ),
    ]
    session.add_all(slots)
    session.flush()

    shipments = [
        Shipment(
            carrier_id=carrier.id,
            driver_id=drivers[0].id,
            vehicle_id=vehicles[0].id,
            shipment_number="SHP-1001",
            origin_location="Dallas, TX",
            destination_location="Central Receiving DC",
            destination_facility_id=facility.id,
            status=ShipmentStatus.IN_TRANSIT,
            is_active=True,
            weight_kg=Decimal("12000"),
            pallet_count=18,
        ),
        Shipment(
            carrier_id=carrier.id,
            driver_id=drivers[0].id,
            vehicle_id=vehicles[1].id,
            shipment_number="SHP-1002",
            origin_location="Houston, TX",
            destination_location="Central Receiving DC",
            destination_facility_id=facility.id,
            status=ShipmentStatus.ASSIGNED,
            is_active=True,
            weight_kg=Decimal("8000"),
            pallet_count=12,
        ),
        Shipment(
            carrier_id=carrier.id,
            driver_id=drivers[1].id,
            vehicle_id=vehicles[1].id,
            shipment_number="SHP-1003",
            origin_location="Austin, TX",
            destination_location="Central Receiving DC",
            destination_facility_id=facility.id,
            status=ShipmentStatus.PENDING,
            is_active=False,
            weight_kg=Decimal("5000"),
            pallet_count=8,
        ),
    ]
    session.add_all(shipments)
    session.flush()

    eta_updates = [
        ETAUpdate(
            shipment_id=shipments[0].id,
            previous_eta=None,
            new_eta=now + timedelta(hours=1),
            update_timestamp=now - timedelta(hours=2),
            source=ETASource.DISPATCH,
        ),
        ETAUpdate(
            shipment_id=shipments[0].id,
            previous_eta=now + timedelta(hours=1),
            new_eta=now + timedelta(hours=2, minutes=30),
            update_timestamp=now - timedelta(minutes=30),
            source=ETASource.DRIVER,
            reason="Traffic on I-35",
        ),
    ]
    session.add_all(eta_updates)

    exception = DriverException(
        shipment_id=shipments[0].id,
        driver_id=drivers[0].id,
        exception_type=ExceptionType.TRAFFIC,
        description="Heavy congestion near facility",
        status=ExceptionStatus.OPEN,
        occurred_at=now - timedelta(minutes=45),
    )
    session.add(exception)
    session.flush()

    appointments = [
        Appointment(
            shipment_id=shipments[0].id,
            facility_id=facility.id,
            appointment_slot_id=slots[0].id,
            dock_id=docks[0].id,
            status=AppointmentStatus.CONFIRMED,
        ),
        Appointment(
            shipment_id=shipments[0].id,
            facility_id=facility.id,
            appointment_slot_id=slots[1].id,
            status=AppointmentStatus.CANCELLED,
            notes="Superseded by rescheduled slot",
        ),
    ]
    session.add_all(appointments)

    checkin = FacilityCheckin(
        shipment_id=shipments[0].id,
        facility_id=facility.id,
        dock_id=docks[0].id,
        checkin_type=CheckinType.GATE_IN,
        occurred_at=now - timedelta(minutes=10),
    )
    session.add(checkin)

    thread = ChatThread(
        shipment_id=shipments[0].id,
        driver_id=drivers[0].id,
        driver_exception_id=exception.id,
        subject="Delay notification",
        status=ChatThreadStatus.OPEN,
    )
    session.add(thread)
    session.flush()

    messages = [
        ChatMessage(
            chat_thread_id=thread.id,
            sender_type=SenderType.DRIVER,
            content="Running about 90 minutes late.",
            sent_at=now - timedelta(minutes=40),
            direction=MessageDirection.INBOUND,
            metadata_={"channel": "mobile_app"},
        ),
        ChatMessage(
            chat_thread_id=thread.id,
            sender_type=SenderType.DISPATCHER,
            content="Copy that. Updating ETA.",
            sent_at=now - timedelta(minutes=35),
            direction=MessageDirection.OUTBOUND,
        ),
    ]
    session.add_all(messages)

    contact = Contact(
        name="Receiving Desk",
        email="receiving@crdc.example",
        phone="+15559999",
        contact_type=ContactType.FACILITY,
        facility_id=facility.id,
        status=EntityStatus.ACTIVE,
    )
    session.add(contact)
    session.flush()

    op_message = OperationalMessage(
        contact_id=contact.id,
        shipment_id=shipments[0].id,
        channel=MessageChannel.EMAIL,
        subject="Appointment confirmed",
        body="Shipment SHP-1001 appointment confirmed.",
        status=OperationalMessageStatus.SENT,
        sent_at=now - timedelta(hours=1),
    )
    session.add(op_message)

    session.commit()

    return {
        "carrier": carrier,
        "drivers": drivers,
        "vehicles": vehicles,
        "facility": facility,
        "docks": docks,
        "slots": slots,
        "shipments": shipments,
        "appointments": appointments,
        "exception": exception,
        "thread": thread,
    }
