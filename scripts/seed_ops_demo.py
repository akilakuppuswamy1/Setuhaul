"""Seed a presentation-ready Dallas DC operations snapshot.

Creates (or reuses) the driver conversation demo:
original 6:30 PM appointment, later open slots, no open exceptions.
Does not change schema. Safe to re-run: unique codes skip insert.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import (
    Appointment,
    AppointmentSlot,
    Carrier,
    Dock,
    Driver,
    ETAUpdate,
    Facility,
    FacilityRule,
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
ORIGINAL_START = DEMO_DAY.replace(hour=18, minute=30)  # 6:30 PM
ORIGINAL_END = DEMO_DAY.replace(hour=19, minute=0)
SLOT_A_START = DEMO_DAY.replace(hour=20, minute=30)  # 8:30 PM
SLOT_A_END = DEMO_DAY.replace(hour=21, minute=0)
# Second option must still contain the 8:30 PM ETA (Step 5 ETA-001) and end by 9:30 PM.
SLOT_B_START = DEMO_DAY.replace(hour=20, minute=30)
SLOT_B_END = DEMO_DAY.replace(hour=21, minute=30)


def seed_ops_demo(session: Session) -> dict[str, object]:
    carrier = session.query(Carrier).filter_by(code="SETU-DEMO").one_or_none()
    if carrier is None:
        carrier = Carrier(name="SetuHaul Demo Carrier", code="SETU-DEMO", status=EntityStatus.ACTIVE)
        session.add(carrier)
        session.flush()

    driver = session.query(Driver).filter_by(external_id="demo-driver-rivera").one_or_none()
    if driver is None:
        driver = Driver(
            carrier_id=carrier.id,
            name="Jane Rivera",
            phone="+155501024",
            external_id="demo-driver-rivera",
            status=EntityStatus.ACTIVE,
        )
        session.add(driver)
        session.flush()

    vehicle = session.query(Vehicle).filter_by(license_plate="SH-1024-VAN").one_or_none()
    if vehicle is None:
        vehicle = Vehicle(
            carrier_id=carrier.id,
            license_plate="SH-1024-VAN",
            vehicle_type="53ft_dry_van",
            max_weight_kg=Decimal("20000"),
            max_volume_cbm=Decimal("90"),
            status=EntityStatus.ACTIVE,
        )
        session.add(vehicle)
        session.flush()

    facility = session.query(Facility).filter_by(code="DAL-DC").one_or_none()
    if facility is None:
        facility = Facility(
            name="Dallas Distribution Center",
            code="DAL-DC",
            address="2400 Logistics Way, Dallas, TX",
            timezone="America/Chicago",
            status=EntityStatus.ACTIVE,
        )
        session.add(facility)
        session.flush()

    dock_a = session.query(Dock).filter_by(facility_id=facility.id, name="Dock A").one_or_none()
    if dock_a is None:
        dock_a = Dock(
            facility_id=facility.id,
            name="Dock A",
            dock_type="standard",
            max_weight_kg=Decimal("25000"),
            status=DockStatus.AVAILABLE,
        )
        session.add(dock_a)
        session.flush()

    dock_b = session.query(Dock).filter_by(facility_id=facility.id, name="Dock B").one_or_none()
    if dock_b is None:
        dock_b = Dock(
            facility_id=facility.id,
            name="Dock B",
            dock_type="standard",
            max_weight_kg=Decimal("25000"),
            status=DockStatus.AVAILABLE,
        )
        session.add(dock_b)
        session.flush()

    if session.query(FacilityRule).filter_by(facility_id=facility.id, rule_type="max_daily_appointments").one_or_none() is None:
        session.add(
            FacilityRule(
                facility_id=facility.id,
                rule_type="max_daily_appointments",
                rule_value={"limit": 80},
                effective_start=ORIGINAL_START - timedelta(days=30),
                is_active=True,
            )
        )

    def _slot(start: datetime, end: datetime, capacity: int) -> AppointmentSlot:
        existing = (
            session.query(AppointmentSlot)
            .filter_by(facility_id=facility.id, start_time=start, end_time=end)
            .one_or_none()
        )
        if existing is not None:
            return existing
        slot = AppointmentSlot(
            facility_id=facility.id,
            start_time=start,
            end_time=end,
            capacity=capacity,
            status=AppointmentSlotStatus.OPEN,
        )
        session.add(slot)
        session.flush()
        return slot

    original_slot = _slot(ORIGINAL_START, ORIGINAL_END, 1)
    alt_a = _slot(SLOT_A_START, SLOT_A_END, 1)
    # Heal the previous 9:00–9:30 window so ETA 8:30 PM remains inside the slot.
    previous_b = (
        session.query(AppointmentSlot)
        .filter_by(
            facility_id=facility.id,
            start_time=DEMO_DAY.replace(hour=21, minute=0),
            end_time=SLOT_B_END,
        )
        .one_or_none()
    )
    if previous_b is not None:
        previous_b.start_time = SLOT_B_START
        alt_b = previous_b
        session.flush()
    else:
        alt_b = _slot(SLOT_B_START, SLOT_B_END, 1)

    shipment = session.query(Shipment).filter_by(shipment_number="SH-1024").one_or_none()
    if shipment is None:
        shipment = Shipment(
            carrier_id=carrier.id,
            driver_id=driver.id,
            vehicle_id=vehicle.id,
            shipment_number="SH-1024",
            origin_location="Fort Worth, TX",
            destination_location="Dallas Distribution Center",
            destination_facility_id=facility.id,
            status=ShipmentStatus.IN_TRANSIT,
            is_active=True,
            weight_kg=Decimal("11000"),
            pallet_count=16,
        )
        session.add(shipment)
        session.flush()

    original_eta_ts = DEMO_DAY.replace(hour=8, minute=0)
    existing_etas = session.query(ETAUpdate).filter_by(shipment_id=shipment.id).all()
    if not existing_etas:
        session.add(
            ETAUpdate(
                shipment_id=shipment.id,
                previous_eta=None,
                new_eta=ORIGINAL_START,
                update_timestamp=original_eta_ts,
                source=ETASource.DISPATCH,
                reason="Original scheduled arrival",
            )
        )
    else:
        for item in existing_etas:
            if item.source == ETASource.DISPATCH and (item.reason or "").startswith("Original scheduled"):
                item.update_timestamp = original_eta_ts

    existing_appt = (
        session.query(Appointment)
        .filter_by(shipment_id=shipment.id, appointment_slot_id=original_slot.id)
        .one_or_none()
    )
    if existing_appt is None:
        session.add(
            Appointment(
                shipment_id=shipment.id,
                facility_id=facility.id,
                appointment_slot_id=original_slot.id,
                dock_id=dock_a.id,
                status=AppointmentStatus.REQUESTED,
                notes="Original 6:30 PM appointment",
            )
        )
    elif existing_appt.status == AppointmentStatus.CONFIRMED:
        # A confirmed original blocks Step 6 from allocating a rescheduled slot.
        existing_appt.status = AppointmentStatus.REQUESTED
        existing_appt.notes = existing_appt.notes or "Original 6:30 PM appointment"

    extra = session.query(Shipment).filter_by(shipment_number="SH-1025").one_or_none()
    if extra is None:
        extra = Shipment(
            carrier_id=carrier.id,
            driver_id=driver.id,
            vehicle_id=vehicle.id,
            shipment_number="SH-1025",
            origin_location="Waco, TX",
            destination_location="Dallas Distribution Center",
            destination_facility_id=facility.id,
            status=ShipmentStatus.ASSIGNED,
            is_active=True,
            weight_kg=Decimal("7000"),
            pallet_count=10,
        )
        session.add(extra)
        session.flush()
        session.add(
            ETAUpdate(
                shipment_id=extra.id,
                previous_eta=None,
                new_eta=SLOT_A_START,
                update_timestamp=ORIGINAL_START - timedelta(hours=4),
                source=ETASource.DISPATCH,
                reason="Scheduled inbound",
            )
        )

    session.commit()
    return {
        "carrier_id": str(carrier.id),
        "driver_id": str(driver.id),
        "facility_id": str(facility.id),
        "shipment_id": str(shipment.id),
        "shipment_number": shipment.shipment_number,
        "original_slot_id": str(original_slot.id),
        "option_slot_ids": [str(alt_a.id), str(alt_b.id)],
        "dock_a_id": str(dock_a.id),
        "dock_b_id": str(dock_b.id),
    }


def main() -> None:
    session = SessionLocal()
    try:
        result = seed_ops_demo(session)
        print("Seeded operations demo:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
