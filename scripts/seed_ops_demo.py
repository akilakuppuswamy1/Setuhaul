"""Seed the classroom operations snapshot (Dallas hero + scarce Chicago capacity).

Creates (or reuses) deterministic demo records. Does not change schema.
Safe to re-run: unique codes / shipment numbers skip insert.

Targets DATABASE_URL only. Never selects setuhaul_test.
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

from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.engines.feasibility.rules import CAPACITY_CONSUMING_APPOINTMENT_STATUSES
from app.models import (
    Appointment,
    AppointmentSlot,
    Carrier,
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
    ContactType,
    DockStatus,
    EntityStatus,
    ETASource,
    ExceptionStatus,
    ExceptionType,
    MessageChannel,
    OperationalMessageStatus,
    ShipmentStatus,
)
from app.services.proposal import PROPOSAL_MARKER

TZ = ZoneInfo("America/Chicago")
DEMO_DAY = datetime(2026, 8, 13, tzinfo=TZ)
ORIGINAL_START = DEMO_DAY.replace(hour=18, minute=30)  # 6:30 PM
ORIGINAL_END = DEMO_DAY.replace(hour=19, minute=0)
SLOT_A_START = DEMO_DAY.replace(hour=20, minute=30)  # 8:30 PM
SLOT_A_END = DEMO_DAY.replace(hour=21, minute=0)
# Second option must still contain the 8:30 PM ETA (Step 5 ETA-001) and end by 9:30 PM.
SLOT_B_START = DEMO_DAY.replace(hour=20, minute=30)
SLOT_B_END = DEMO_DAY.replace(hour=21, minute=30)

# Hero evening windows at Chicago. Disjoint 30-minute clocks cannot all contain one
# ETA (ETA-001). These overlapping windows all contain 8:00 PM except the 9:00 slot.
CHI_1930_START = DEMO_DAY.replace(hour=19, minute=30)
CHI_1930_END = DEMO_DAY.replace(hour=20, minute=30)
CHI_2000_START = DEMO_DAY.replace(hour=20, minute=0)
CHI_2000_END = DEMO_DAY.replace(hour=20, minute=30)
CHI_2000_WIDE_END = DEMO_DAY.replace(hour=21, minute=0)
CHI_2100_START = DEMO_DAY.replace(hour=21, minute=0)
CHI_2100_END = DEMO_DAY.replace(hour=21, minute=30)

ETA_COMPETE = DEMO_DAY.replace(hour=20, minute=0)
ETA_RESCHEDULE = DEMO_DAY.replace(hour=20, minute=30)
ETA_NOCAP = DEMO_DAY.replace(hour=21, minute=15)
ETA_ARRIVED = DEMO_DAY.replace(hour=16, minute=0)


def as_chicago(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)

FORBIDDEN_DATABASE_NAMES = frozenset({"postgres", "template0", "template1", "setuhaul_test"})
_CAPACITY_STATUSES = tuple(
    AppointmentStatus(status) for status in CAPACITY_CONSUMING_APPOINTMENT_STATUSES
)

DEMO_RACE_NOTES = f"{PROPOSAL_MARKER}\nDEMO:RACE capacity-1 concurrent confirm fixture"
DEMO_PROPOSAL_NOTES = f"{PROPOSAL_MARKER}\nDEMO:HERO-PROPOSAL proposed evening slot (does not consume capacity)"
DEMO_RESCHEDULE_NOTES = "DEMO:RESCHEDULE original 6:30 PM confirmed appointment"
DEMO_OCCUPIER_2100 = "DEMO:OCC-2100 confirmed; consumes the 9:00 PM slot"
DEMO_OCCUPIER_1400 = "DEMO:OCC-1400 confirmed; consumes the 2:00 PM slot"
DEMO_OCCUPIER_1000 = "DEMO:OCC-1000 confirmed; consumes one 10:00 AM unit"
DEMO_HISTORY_NOTES = "DEMO:HISTORY superseded / cancelled appointment"
DEMO_ARRIVED_NOTES = "DEMO:ARRIVED waiting at facility"
DEMO_PAD_CONFIRMED = "DEMO:PAD-CONFIRMED classroom volume"
DEMO_PAD_REQUESTED = "DEMO:PAD-REQUESTED classroom volume"


def assert_live_demo_target() -> dict[str, str]:
    """Print the connection target and abort if it is not the live demo database."""
    parsed = make_url(settings.database_url)
    name = parsed.database or ""
    host = parsed.host or ""
    port = str(parsed.port or "")
    profile = settings.app_env
    print("=" * 50)
    print("SETUHAUL DEMO SEED - DATABASE TARGET")
    print("=" * 50)
    print(f"DATABASE NAME: {name}")
    print(f"HOST: {host}")
    print(f"PORT: {port}")
    print(f"environment/profile: {profile}")
    print(f"url_driver: {parsed.drivername}")
    if name in FORBIDDEN_DATABASE_NAMES:
        raise RuntimeError(
            f"Aborting seed: database {name!r} is forbidden. "
            "This script targets the live demo database (setuhaul) only."
        )
    with engine.connect() as connection:
        current = connection.exec_driver_sql("SELECT current_database()").scalar()
    print(f"current_database(): {current}")
    if current in FORBIDDEN_DATABASE_NAMES:
        raise RuntimeError(
            f"Aborting seed: connected database {current!r} is forbidden."
        )
    if current != name:
        raise RuntimeError(
            f"Aborting seed: URL database {name!r} does not match current_database() {current!r}."
        )
    print("Target accepted. Writing demo seed data.")
    print("=" * 50)
    return {
        "database": str(current),
        "host": host,
        "port": port,
        "profile": profile,
    }


def _carrier(session: Session) -> Carrier:
    carrier = session.query(Carrier).filter_by(code="SETU-DEMO").one_or_none()
    if carrier is None:
        carrier = Carrier(name="SetuHaul Demo Carrier", code="SETU-DEMO", status=EntityStatus.ACTIVE)
        session.add(carrier)
        session.flush()
    return carrier


def _driver(
    session: Session,
    carrier: Carrier,
    *,
    external_id: str,
    name: str,
    phone: str,
) -> Driver:
    driver = session.query(Driver).filter_by(external_id=external_id).one_or_none()
    if driver is None:
        driver = Driver(
            carrier_id=carrier.id,
            name=name,
            phone=phone,
            external_id=external_id,
            status=EntityStatus.ACTIVE,
        )
        session.add(driver)
        session.flush()
    else:
        driver.name = name
        driver.phone = phone
        driver.status = EntityStatus.ACTIVE
    return driver


def _vehicle(
    session: Session,
    carrier: Carrier,
    *,
    license_plate: str,
    vehicle_type: str = "53ft_dry_van",
    max_weight_kg: str = "20000",
    max_volume_cbm: str = "90",
) -> Vehicle:
    vehicle = session.query(Vehicle).filter_by(license_plate=license_plate).one_or_none()
    if vehicle is None:
        vehicle = Vehicle(
            carrier_id=carrier.id,
            license_plate=license_plate,
            vehicle_type=vehicle_type,
            max_weight_kg=Decimal(max_weight_kg),
            max_volume_cbm=Decimal(max_volume_cbm),
            status=EntityStatus.ACTIVE,
        )
        session.add(vehicle)
        session.flush()
    else:
        vehicle.vehicle_type = vehicle_type
        vehicle.status = EntityStatus.ACTIVE
    return vehicle


def _facility(
    session: Session,
    *,
    code: str,
    name: str,
    address: str,
    timezone_name: str = "America/Chicago",
) -> Facility:
    facility = session.query(Facility).filter_by(code=code).one_or_none()
    if facility is None:
        facility = Facility(
            name=name,
            code=code,
            address=address,
            timezone=timezone_name,
            status=EntityStatus.ACTIVE,
        )
        session.add(facility)
        session.flush()
    else:
        facility.name = name
        facility.address = address
        facility.status = EntityStatus.ACTIVE
    return facility


def _dock(
    session: Session,
    facility: Facility,
    *,
    name: str,
    dock_type: str = "standard",
    max_weight_kg: str = "25000",
    temperature_controlled: bool = False,
    status: DockStatus = DockStatus.AVAILABLE,
) -> Dock:
    dock = session.query(Dock).filter_by(facility_id=facility.id, name=name).one_or_none()
    if dock is None:
        dock = Dock(
            facility_id=facility.id,
            name=name,
            dock_type=dock_type,
            max_weight_kg=Decimal(max_weight_kg),
            temperature_controlled=temperature_controlled,
            status=status,
        )
        session.add(dock)
        session.flush()
    else:
        dock.dock_type = dock_type
        dock.temperature_controlled = temperature_controlled
        dock.status = status
        dock.max_weight_kg = Decimal(max_weight_kg)
    return dock


def _rule(
    session: Session,
    facility: Facility,
    *,
    rule_type: str,
    rule_value: dict[str, Any],
    effective_start: datetime,
) -> FacilityRule:
    existing = (
        session.query(FacilityRule)
        .filter_by(facility_id=facility.id, rule_type=rule_type)
        .one_or_none()
    )
    if existing is None:
        existing = FacilityRule(
            facility_id=facility.id,
            rule_type=rule_type,
            rule_value=rule_value,
            effective_start=effective_start,
            is_active=True,
        )
        session.add(existing)
        session.flush()
    else:
        existing.rule_value = rule_value
        existing.is_active = True
    return existing


def _slot_at(
    session: Session,
    facility_id,
    start: datetime,
    end: datetime,
    capacity: int,
) -> AppointmentSlot:
    start_local = as_chicago(start)
    end_local = as_chicago(end)
    for existing in session.query(AppointmentSlot).filter_by(facility_id=facility_id).all():
        if as_chicago(existing.start_time) == start_local and as_chicago(existing.end_time) == end_local:
            existing.capacity = capacity
            if existing.status == AppointmentSlotStatus.CLOSED:
                existing.status = AppointmentSlotStatus.OPEN
            return existing
    slot = AppointmentSlot(
        facility_id=facility_id,
        start_time=start,
        end_time=end,
        capacity=capacity,
        status=AppointmentSlotStatus.OPEN,
    )
    session.add(slot)
    session.flush()
    return slot


def _shipment(
    session: Session,
    carrier: Carrier,
    *,
    shipment_number: str,
    driver: Driver,
    vehicle: Vehicle,
    origin: str,
    destination: str,
    facility: Facility,
    status: ShipmentStatus,
    weight_kg: str,
    pallet_count: int,
    is_active: bool = True,
) -> Shipment:
    shipment = session.query(Shipment).filter_by(shipment_number=shipment_number).one_or_none()
    if shipment is None:
        shipment = Shipment(
            carrier_id=carrier.id,
            driver_id=driver.id,
            vehicle_id=vehicle.id,
            shipment_number=shipment_number,
            origin_location=origin,
            destination_location=destination,
            destination_facility_id=facility.id,
            status=status,
            is_active=is_active,
            weight_kg=Decimal(weight_kg),
            pallet_count=pallet_count,
        )
        session.add(shipment)
        session.flush()
    else:
        shipment.driver_id = driver.id
        shipment.vehicle_id = vehicle.id
        shipment.destination_facility_id = facility.id
        shipment.status = status
        shipment.is_active = is_active
        shipment.weight_kg = Decimal(weight_kg)
        shipment.pallet_count = pallet_count
    return shipment


def _ensure_eta(
    session: Session,
    shipment: Shipment,
    *,
    new_eta: datetime,
    timestamp: datetime,
    source: ETASource,
    reason: str,
    previous_eta: datetime | None = None,
) -> ETAUpdate:
    existing = (
        session.query(ETAUpdate)
        .filter_by(shipment_id=shipment.id, reason=reason)
        .one_or_none()
    )
    if existing is None:
        existing = ETAUpdate(
            shipment_id=shipment.id,
            previous_eta=previous_eta,
            new_eta=new_eta,
            update_timestamp=timestamp,
            source=source,
            reason=reason,
        )
        session.add(existing)
        session.flush()
    else:
        existing.previous_eta = previous_eta
        existing.new_eta = new_eta
        existing.update_timestamp = timestamp
        existing.source = source
    return existing


def _appointment(
    session: Session,
    *,
    shipment: Shipment,
    facility: Facility,
    slot: AppointmentSlot,
    dock: Dock | None,
    status: AppointmentStatus,
    notes: str,
    tag: str,
) -> Appointment:
    existing = (
        session.query(Appointment)
        .filter(Appointment.shipment_id == shipment.id, Appointment.notes.contains(tag))
        .one_or_none()
    )
    if existing is None:
        existing = Appointment(
            shipment_id=shipment.id,
            facility_id=facility.id,
            appointment_slot_id=slot.id,
            dock_id=dock.id if dock is not None else None,
            status=status,
            notes=notes,
        )
        session.add(existing)
        session.flush()
    else:
        existing.appointment_slot_id = slot.id
        existing.dock_id = dock.id if dock is not None else None
        existing.status = status
        existing.notes = notes
        existing.facility_id = facility.id
    return existing


def _exception(
    session: Session,
    *,
    shipment: Shipment,
    driver: Driver,
    exception_type: ExceptionType,
    description: str,
    status: ExceptionStatus,
    occurred_at: datetime,
    resolved_at: datetime | None = None,
) -> DriverException:
    existing = (
        session.query(DriverException)
        .filter_by(shipment_id=shipment.id, description=description)
        .one_or_none()
    )
    if existing is None:
        existing = DriverException(
            shipment_id=shipment.id,
            driver_id=driver.id,
            exception_type=exception_type,
            description=description,
            status=status,
            occurred_at=occurred_at,
            resolved_at=resolved_at,
        )
        session.add(existing)
        session.flush()
    else:
        existing.status = status
        existing.resolved_at = resolved_at
        existing.exception_type = exception_type
    return existing


def _checkin(
    session: Session,
    *,
    shipment: Shipment,
    facility: Facility,
    dock: Dock | None,
    checkin_type: CheckinType,
    occurred_at: datetime,
    notes: str,
) -> FacilityCheckin:
    existing = (
        session.query(FacilityCheckin)
        .filter_by(shipment_id=shipment.id, notes=notes)
        .one_or_none()
    )
    if existing is None:
        existing = FacilityCheckin(
            shipment_id=shipment.id,
            facility_id=facility.id,
            dock_id=dock.id if dock is not None else None,
            checkin_type=checkin_type,
            occurred_at=occurred_at,
            notes=notes,
        )
        session.add(existing)
        session.flush()
    return existing


def _sync_slot_fill(session: Session, slot: AppointmentSlot) -> None:
    booked = (
        session.query(Appointment)
        .filter(
            Appointment.appointment_slot_id == slot.id,
            Appointment.status.in_(_CAPACITY_STATUSES),
        )
        .count()
    )
    if booked >= slot.capacity:
        slot.status = AppointmentSlotStatus.FULL
    elif slot.status == AppointmentSlotStatus.FULL:
        slot.status = AppointmentSlotStatus.OPEN


def _seed_dallas_hero(
    session: Session,
    carrier: Carrier,
) -> dict[str, Any]:
    driver = _driver(
        session,
        carrier,
        external_id="demo-driver-rivera",
        name="Jane Rivera",
        phone="+155501024",
    )
    vehicle = _vehicle(session, carrier, license_plate="SH-1024-VAN")
    facility = _facility(
        session,
        code="DAL-DC",
        name="Dallas Distribution Center",
        address="2400 Logistics Way, Dallas, TX",
    )
    dock_a = _dock(session, facility, name="Dock A")
    dock_b = _dock(session, facility, name="Dock B")
    _rule(
        session,
        facility,
        rule_type="max_daily_appointments",
        rule_value={"limit": 80},
        effective_start=ORIGINAL_START - timedelta(days=30),
    )

    original_slot = _slot_at(session, facility.id, ORIGINAL_START, ORIGINAL_END, 1)
    alt_a = _slot_at(session, facility.id, SLOT_A_START, SLOT_A_END, 1)
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
        alt_b = _slot_at(session, facility.id, SLOT_B_START, SLOT_B_END, 1)

    shipment = _shipment(
        session,
        carrier,
        shipment_number="SH-1024",
        driver=driver,
        vehicle=vehicle,
        origin="Fort Worth, TX",
        destination="Dallas Distribution Center",
        facility=facility,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg="11000",
        pallet_count=16,
    )
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

    return {
        "driver": driver,
        "facility": facility,
        "shipment": shipment,
        "original_slot": original_slot,
        "alt_a": alt_a,
        "alt_b": alt_b,
        "dock_a": dock_a,
        "dock_b": dock_b,
        "original_eta_ts": original_eta_ts,
    }


def _seed_chicago_base(
    session: Session,
    carrier: Carrier,
    original_eta_ts: datetime,
) -> dict[str, Any]:
    chicago = _facility(
        session,
        code="CHI-XD",
        name="Chicago Cross-Dock",
        address="5400 Corwith Ave, Chicago, IL",
    )
    alex = _driver(
        session,
        carrier,
        external_id="demo-driver-alex",
        name="Alex Driver",
        phone="+155554375",
    )
    chicago_van = _vehicle(session, carrier, license_plate="CHI-5437-VAN")
    chicago_dock = _dock(session, chicago, name="Dock A")
    chicago_original = _slot_at(session, chicago.id, ORIGINAL_START, ORIGINAL_END, 1)
    chicago_alt_a = _slot_at(session, chicago.id, SLOT_A_START, SLOT_A_END, 1)
    chicago_alt_b = _slot_at(session, chicago.id, SLOT_B_START, SLOT_B_END, 1)

    chicago_shipment = _shipment(
        session,
        carrier,
        shipment_number="SHP-CHI-5437",
        driver=alex,
        vehicle=chicago_van,
        origin="Milwaukee, WI",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg="9000",
        pallet_count=14,
    )
    chicago_etas = session.query(ETAUpdate).filter_by(shipment_id=chicago_shipment.id).all()
    if not chicago_etas:
        session.add(
            ETAUpdate(
                shipment_id=chicago_shipment.id,
                previous_eta=None,
                new_eta=ORIGINAL_START,
                update_timestamp=original_eta_ts,
                source=ETASource.DISPATCH,
                reason="Original scheduled arrival",
            )
        )

    chicago_appt = (
        session.query(Appointment)
        .filter_by(shipment_id=chicago_shipment.id, appointment_slot_id=chicago_original.id)
        .one_or_none()
    )
    if chicago_appt is None:
        session.add(
            Appointment(
                shipment_id=chicago_shipment.id,
                facility_id=chicago.id,
                appointment_slot_id=chicago_original.id,
                dock_id=chicago_dock.id,
                status=AppointmentStatus.REQUESTED,
                notes="Original appointment",
            )
        )
    elif chicago_appt.status == AppointmentStatus.CONFIRMED:
        chicago_appt.status = AppointmentStatus.REQUESTED
        chicago_appt.notes = chicago_appt.notes or "Original appointment"

    return {
        "facility": chicago,
        "alex": alex,
        "dock_a": chicago_dock,
        "original_slot": chicago_original,
        "alt_a": chicago_alt_a,
        "alt_b": chicago_alt_b,
        "shipment": chicago_shipment,
    }


def _seed_scarce_chicago(
    session: Session,
    carrier: Carrier,
    chicago: Facility,
    alex: Driver,
    dock_a: Dock,
    original_slot: AppointmentSlot,
    alt_a: AppointmentSlot,
    alt_b: AppointmentSlot,
) -> dict[str, Any]:
    dock_b = _dock(session, chicago, name="Dock B")
    dock_c = _dock(
        session,
        chicago,
        name="Dock C",
        dock_type="reefer",
        temperature_controlled=True,
    )
    dock_d = _dock(
        session,
        chicago,
        name="Dock D",
        dock_type="standard",
        status=DockStatus.MAINTENANCE,
    )
    _rule(
        session,
        chicago,
        rule_type="max_daily_appointments",
        rule_value={"limit": 40},
        effective_start=ORIGINAL_START - timedelta(days=30),
    )
    _rule(
        session,
        chicago,
        rule_type="operating_hours",
        rule_value={"open": "06:00", "close": "22:00"},
        effective_start=ORIGINAL_START - timedelta(days=30),
    )

    morning_a = _slot_at(
        session,
        chicago.id,
        DEMO_DAY.replace(hour=10, minute=0),
        DEMO_DAY.replace(hour=10, minute=30),
        2,
    )
    morning_b = _slot_at(
        session,
        chicago.id,
        DEMO_DAY.replace(hour=11, minute=0),
        DEMO_DAY.replace(hour=11, minute=30),
        2,
    )
    afternoon = _slot_at(
        session,
        chicago.id,
        DEMO_DAY.replace(hour=14, minute=0),
        DEMO_DAY.replace(hour=14, minute=30),
        1,
    )
    waiting_slot = _slot_at(
        session,
        chicago.id,
        DEMO_DAY.replace(hour=16, minute=0),
        DEMO_DAY.replace(hour=16, minute=30),
        1,
    )
    slot_1930 = _slot_at(session, chicago.id, CHI_1930_START, CHI_1930_END, 1)
    slot_2000 = _slot_at(session, chicago.id, CHI_2000_START, CHI_2000_END, 1)
    slot_2000_wide = _slot_at(session, chicago.id, CHI_2000_START, CHI_2000_WIDE_END, 1)
    slot_2100 = _slot_at(session, chicago.id, CHI_2100_START, CHI_2100_END, 1)

    priya = _driver(session, carrier, external_id="demo-driver-priya", name="Priya Driver", phone="+155510002")
    ravi = _driver(session, carrier, external_id="demo-driver-ravi", name="Ravi Driver", phone="+155510003")
    maya = _driver(session, carrier, external_id="demo-driver-maya", name="Maya Driver", phone="+155510004")
    daniel = _driver(session, carrier, external_id="demo-driver-daniel", name="Daniel Driver", phone="+155510005")
    sarah = _driver(session, carrier, external_id="demo-driver-sarah", name="Sarah Driver", phone="+155510006")
    kumar = _driver(session, carrier, external_id="demo-driver-kumar", name="Kumar Driver", phone="+155510007")
    ananya = _driver(session, carrier, external_id="demo-driver-ananya", name="Ananya Driver", phone="+155510008")
    chen = _driver(session, carrier, external_id="demo-driver-chen", name="Chen Occupier", phone="+155510009")
    lopez = _driver(session, carrier, external_id="demo-driver-lopez", name="Lopez Occupier", phone="+155510010")
    singh = _driver(session, carrier, external_id="demo-driver-singh", name="Singh Occupier", phone="+155510011")
    walsh = _driver(session, carrier, external_id="demo-driver-walsh", name="Walsh Occupier", phone="+155510012")

    vans = {
        "priya": _vehicle(session, carrier, license_plate="CHI-PRIYA-VAN"),
        "ravi": _vehicle(session, carrier, license_plate="CHI-RAVI-VAN"),
        "maya": _vehicle(session, carrier, license_plate="CHI-MAYA-VAN"),
        "daniel": _vehicle(session, carrier, license_plate="CHI-DANIEL-VAN"),
        "sarah": _vehicle(
            session,
            carrier,
            license_plate="CHI-SARAH-REF",
            vehicle_type="48ft_reefer",
            max_weight_kg="18000",
        ),
        "kumar": _vehicle(session, carrier, license_plate="CHI-KUMAR-VAN"),
        "ananya": _vehicle(session, carrier, license_plate="CHI-ANANYA-VAN"),
        "chen": _vehicle(session, carrier, license_plate="CHI-CHEN-VAN"),
        "lopez": _vehicle(session, carrier, license_plate="CHI-LOPEZ-VAN"),
        "singh": _vehicle(session, carrier, license_plate="CHI-SINGH-VAN"),
        "walsh": _vehicle(session, carrier, license_plate="CHI-WALSH-VAN"),
        "alex_demo": _vehicle(session, carrier, license_plate="CHI-ALEX-DEMO"),
        "race": _vehicle(session, carrier, license_plate="CHI-RACE-VAN"),
        "nocap": _vehicle(session, carrier, license_plate="CHI-NOCAP-VAN"),
    }

    origins = {
        "001": "Gary, IN",
        "002": "Joliet, IL",
        "003": "Rockford, IL",
        "004": "Madison, WI",
        "005": "South Bend, IN",
    }
    hero_specs = [
        ("SHP-DEMO-001", alex, vans["alex_demo"], origins["001"], "+155554375"),
        ("SHP-DEMO-002", priya, vans["priya"], origins["002"], "+155510002"),
        ("SHP-DEMO-003", ravi, vans["ravi"], origins["003"], "+155510003"),
        ("SHP-DEMO-004", maya, vans["maya"], origins["004"], "+155510004"),
        ("SHP-DEMO-005", daniel, vans["daniel"], origins["005"], "+155510005"),
    ]
    hero_shipments: dict[str, Shipment] = {}
    eta_ts = DEMO_DAY.replace(hour=15, minute=0)
    for number, driver, vehicle, origin, _phone in hero_specs:
        shipment = _shipment(
            session,
            carrier,
            shipment_number=number,
            driver=driver,
            vehicle=vehicle,
            origin=origin,
            destination="Chicago Cross-Dock",
            facility=chicago,
            status=ShipmentStatus.IN_TRANSIT,
            weight_kg="9500",
            pallet_count=12,
        )
        _ensure_eta(
            session,
            shipment,
            new_eta=ORIGINAL_START,
            timestamp=DEMO_DAY.replace(hour=8, minute=0),
            source=ETASource.DISPATCH,
            reason="Original scheduled arrival",
        )
        _ensure_eta(
            session,
            shipment,
            previous_eta=ORIGINAL_START,
            new_eta=ETA_COMPETE,
            timestamp=eta_ts,
            source=ETASource.DRIVER,
            reason="Delayed; competing for scarce evening capacity",
        )
        hero_shipments[number] = shipment

    _exception(
        session,
        shipment=hero_shipments["SHP-DEMO-003"],
        driver=ravi,
        exception_type=ExceptionType.TRAFFIC,
        description="I-90 congestion; still feasible for 8:00 PM windows",
        status=ExceptionStatus.RESOLVED,
        occurred_at=eta_ts - timedelta(hours=1),
        resolved_at=eta_ts,
    )
    _exception(
        session,
        shipment=hero_shipments["SHP-DEMO-005"],
        driver=daniel,
        exception_type=ExceptionType.DELAY,
        description="Late departure; needs later evening slot",
        status=ExceptionStatus.RESOLVED,
        occurred_at=eta_ts - timedelta(minutes=40),
        resolved_at=eta_ts,
    )

    _appointment(
        session,
        shipment=hero_shipments["SHP-DEMO-005"],
        facility=chicago,
        slot=morning_b,
        dock=dock_a,
        status=AppointmentStatus.CANCELLED,
        notes=DEMO_HISTORY_NOTES,
        tag="DEMO:HISTORY",
    )
    priya_proposal = _appointment(
        session,
        shipment=hero_shipments["SHP-DEMO-002"],
        facility=chicago,
        slot=slot_2000,
        dock=dock_a,
        status=AppointmentStatus.REQUESTED,
        notes=DEMO_PROPOSAL_NOTES,
        tag="DEMO:HERO-PROPOSAL",
    )
    priya_proposal.created_at = datetime.now(timezone.utc)
    priya_proposal.status = AppointmentStatus.REQUESTED

    race_driver = _driver(
        session,
        carrier,
        external_id="demo-driver-race",
        name="Race Confirm Driver",
        phone="+155519001",
    )
    race_shipment = _shipment(
        session,
        carrier,
        shipment_number="SHP-DEMO-RACE",
        driver=race_driver,
        vehicle=vans["race"],
        origin="Aurora, IL",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg="8800",
        pallet_count=11,
    )
    _ensure_eta(
        session,
        race_shipment,
        new_eta=ETA_COMPETE,
        timestamp=eta_ts,
        source=ETASource.DISPATCH,
        reason="DEMO:RACE latest ETA inside 8:00 PM capacity-1 slot",
    )
    for extra in (
        session.query(Appointment)
        .filter(
            Appointment.shipment_id == race_shipment.id,
            Appointment.status.in_(_CAPACITY_STATUSES),
        )
        .all()
    ):
        extra.status = AppointmentStatus.CANCELLED
        extra.notes = (extra.notes or "") + "\nDEMO:reset-on-reseed"
    race_proposal = _appointment(
        session,
        shipment=race_shipment,
        facility=chicago,
        slot=slot_2000,
        dock=dock_b,
        status=AppointmentStatus.REQUESTED,
        notes=DEMO_RACE_NOTES,
        tag="DEMO:RACE",
    )
    race_proposal.status = AppointmentStatus.REQUESTED
    race_proposal.notes = DEMO_RACE_NOTES
    race_proposal.created_at = datetime.now(timezone.utc)
    race_proposal.appointment_slot_id = slot_2000.id

    reschedule_shipment = _shipment(
        session,
        carrier,
        shipment_number="SHP-DEMO-RESCHEDULE",
        driver=kumar,
        vehicle=vans["kumar"],
        origin="Peoria, IL",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg="10200",
        pallet_count=15,
    )
    _ensure_eta(
        session,
        reschedule_shipment,
        new_eta=ORIGINAL_START,
        timestamp=DEMO_DAY.replace(hour=8, minute=0),
        source=ETASource.DISPATCH,
        reason="Original scheduled arrival",
    )
    _ensure_eta(
        session,
        reschedule_shipment,
        previous_eta=ORIGINAL_START,
        new_eta=ETA_RESCHEDULE,
        timestamp=eta_ts,
        source=ETASource.DRIVER,
        reason="Running late; new ETA 8:30 PM",
    )
    _exception(
        session,
        shipment=reschedule_shipment,
        driver=kumar,
        exception_type=ExceptionType.TRAFFIC,
        description="Delay on I-55; original 6:30 PM no longer feasible",
        status=ExceptionStatus.RESOLVED,
        occurred_at=eta_ts - timedelta(minutes=20),
        resolved_at=eta_ts,
    )
    reschedule_original = _appointment(
        session,
        shipment=reschedule_shipment,
        facility=chicago,
        slot=original_slot,
        dock=dock_a,
        status=AppointmentStatus.CONFIRMED,
        notes=DEMO_RESCHEDULE_NOTES,
        tag="DEMO:RESCHEDULE",
    )
    later_confirmed = (
        session.query(Appointment)
        .filter(
            Appointment.shipment_id == reschedule_shipment.id,
            Appointment.appointment_slot_id == alt_a.id,
            Appointment.status.in_(_CAPACITY_STATUSES),
        )
        .all()
    )
    for row in later_confirmed:
        row.status = AppointmentStatus.CANCELLED
        row.notes = (row.notes or "") + "\nDEMO:seed-will-not-preconfirm-8:30"

    nocap_shipment = _shipment(
        session,
        carrier,
        shipment_number="SHP-DEMO-NOCAP",
        driver=maya,
        vehicle=vans["nocap"],
        origin="Kenosha, WI",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg="9100",
        pallet_count=13,
    )
    _ensure_eta(
        session,
        nocap_shipment,
        new_eta=ETA_NOCAP,
        timestamp=eta_ts,
        source=ETASource.DRIVER,
        reason="DEMO:NOCAP ETA 9:15 PM; only 9:00 window could contain it",
    )

    occupier_2100 = _shipment(
        session,
        carrier,
        shipment_number="SHP-OCC-2100",
        driver=chen,
        vehicle=vans["chen"],
        origin="Naperville, IL",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg="8000",
        pallet_count=10,
    )
    _ensure_eta(
        session,
        occupier_2100,
        new_eta=CHI_2100_START,
        timestamp=eta_ts - timedelta(hours=2),
        source=ETASource.DISPATCH,
        reason="Occupies the only 9:00 PM compatible capacity",
    )
    _appointment(
        session,
        shipment=occupier_2100,
        facility=chicago,
        slot=slot_2100,
        dock=dock_b,
        status=AppointmentStatus.CONFIRMED,
        notes=DEMO_OCCUPIER_2100,
        tag="DEMO:OCC-2100",
    )

    occupier_alt_b = _shipment(
        session,
        carrier,
        shipment_number="SHP-OCC-2130",
        driver=walsh,
        vehicle=vans["walsh"],
        origin="Hammond, IN",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg="8100",
        pallet_count=10,
    )
    _ensure_eta(
        session,
        occupier_alt_b,
        new_eta=DEMO_DAY.replace(hour=20, minute=45),
        timestamp=eta_ts - timedelta(hours=2),
        source=ETASource.DISPATCH,
        reason="Occupies 20:30–21:30 so 9:15 PM has no remaining containing window",
    )
    _appointment(
        session,
        shipment=occupier_alt_b,
        facility=chicago,
        slot=alt_b,
        dock=dock_c,
        status=AppointmentStatus.CONFIRMED,
        notes="DEMO:OCC-2130 confirmed; consumes the 20:30–21:30 window",
        tag="DEMO:OCC-2130",
    )

    occupier_afternoon = _shipment(
        session,
        carrier,
        shipment_number="SHP-OCC-1400",
        driver=lopez,
        vehicle=vans["lopez"],
        origin="Elgin, IL",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg="7600",
        pallet_count=9,
    )
    _ensure_eta(
        session,
        occupier_afternoon,
        new_eta=DEMO_DAY.replace(hour=14, minute=10),
        timestamp=DEMO_DAY.replace(hour=9, minute=0),
        source=ETASource.DISPATCH,
        reason="Afternoon confirmed inbound",
    )
    _appointment(
        session,
        shipment=occupier_afternoon,
        facility=chicago,
        slot=afternoon,
        dock=dock_a,
        status=AppointmentStatus.CONFIRMED,
        notes=DEMO_OCCUPIER_1400,
        tag="DEMO:OCC-1400",
    )

    occupier_morning = _shipment(
        session,
        carrier,
        shipment_number="SHP-OCC-1000",
        driver=singh,
        vehicle=vans["singh"],
        origin="Waukegan, IL",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.ASSIGNED,
        weight_kg="6400",
        pallet_count=8,
    )
    _ensure_eta(
        session,
        occupier_morning,
        new_eta=DEMO_DAY.replace(hour=10, minute=5),
        timestamp=DEMO_DAY.replace(hour=7, minute=0),
        source=ETASource.DISPATCH,
        reason="Morning confirmed inbound",
    )
    _appointment(
        session,
        shipment=occupier_morning,
        facility=chicago,
        slot=morning_a,
        dock=dock_a,
        status=AppointmentStatus.CONFIRMED,
        notes=DEMO_OCCUPIER_1000,
        tag="DEMO:OCC-1000",
    )

    reefer_shipment = _shipment(
        session,
        carrier,
        shipment_number="SHP-DEMO-REEFER",
        driver=sarah,
        vehicle=vans["sarah"],
        origin="Green Bay, WI",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.IN_TRANSIT,
        weight_kg="12000",
        pallet_count=16,
    )
    _ensure_eta(
        session,
        reefer_shipment,
        new_eta=ETA_COMPETE,
        timestamp=eta_ts,
        source=ETASource.DISPATCH,
        reason="Reefer inbound; dock temperature constraint applies when a dock is bound",
    )

    arrived_shipment = _shipment(
        session,
        carrier,
        shipment_number="SHP-DEMO-ARRIVED",
        driver=ananya,
        vehicle=vans["ananya"],
        origin="Schaumburg, IL",
        destination="Chicago Cross-Dock",
        facility=chicago,
        status=ShipmentStatus.AT_FACILITY,
        weight_kg="5400",
        pallet_count=7,
    )
    _ensure_eta(
        session,
        arrived_shipment,
        new_eta=ETA_ARRIVED,
        timestamp=DEMO_DAY.replace(hour=15, minute=30),
        source=ETASource.FACILITY,
        reason="On site / waiting",
    )
    _appointment(
        session,
        shipment=arrived_shipment,
        facility=chicago,
        slot=waiting_slot,
        dock=dock_a,
        status=AppointmentStatus.CONFIRMED,
        notes=DEMO_ARRIVED_NOTES,
        tag="DEMO:ARRIVED",
    )
    _checkin(
        session,
        shipment=arrived_shipment,
        facility=chicago,
        dock=dock_a,
        checkin_type=CheckinType.GATE_IN,
        occurred_at=DEMO_DAY.replace(hour=15, minute=50),
        notes="DEMO:ARRIVED gate in",
    )
    _checkin(
        session,
        shipment=arrived_shipment,
        facility=chicago,
        dock=dock_a,
        checkin_type=CheckinType.YARD_ARRIVAL,
        occurred_at=DEMO_DAY.replace(hour=16, minute=5),
        notes="DEMO:ARRIVED yard",
    )

    contact = session.query(Contact).filter_by(email="receiving@chi-xd.example").one_or_none()
    if contact is None:
        contact = Contact(
            name="Chicago Receiving Desk",
            email="receiving@chi-xd.example",
            phone="+15559876",
            contact_type=ContactType.FACILITY,
            facility_id=chicago.id,
            status=EntityStatus.ACTIVE,
        )
        session.add(contact)
        session.flush()
    if (
        session.query(OperationalMessage)
        .filter_by(contact_id=contact.id, shipment_id=arrived_shipment.id)
        .one_or_none()
        is None
    ):
        session.add(
            OperationalMessage(
                contact_id=contact.id,
                shipment_id=arrived_shipment.id,
                channel=MessageChannel.EMAIL,
                subject="Driver on site",
                body="Ananya Driver / SHP-DEMO-ARRIVED is waiting at Chicago Cross-Dock.",
                status=OperationalMessageStatus.SENT,
                sent_at=DEMO_DAY.replace(hour=16, minute=10),
            )
        )

    for slot in (morning_a, morning_b, afternoon, waiting_slot, slot_1930, slot_2000, slot_2000_wide, slot_2100, alt_a, alt_b):
        _sync_slot_fill(session, slot)

    return {
        "hero_shipments": hero_shipments,
        "hero_drivers": [alex, priya, ravi, maya, daniel],
        "slot_1930": slot_1930,
        "slot_2000": slot_2000,
        "slot_2000_wide": slot_2000_wide,
        "slot_2100": slot_2100,
        "slot_0830": alt_a,
        "race_shipment": race_shipment,
        "race_proposal": race_proposal,
        "reschedule_shipment": reschedule_shipment,
        "reschedule_original": reschedule_original,
        "nocap_shipment": nocap_shipment,
        "reefer_shipment": reefer_shipment,
        "arrived_shipment": arrived_shipment,
        "docks": [dock_a, dock_b, dock_c, dock_d],
    }


def _seed_indianapolis(session: Session, carrier: Carrier) -> dict[str, Any]:
    indy = _facility(
        session,
        code="IND-HUB",
        name="Indianapolis Inbound Hub",
        address="7100 Jackson St, Indianapolis, IN",
    )
    docks = [
        _dock(session, indy, name="Dock 1"),
        _dock(session, indy, name="Dock 2"),
        _dock(session, indy, name="Dock 3", dock_type="reefer", temperature_controlled=True),
    ]
    _rule(
        session,
        indy,
        rule_type="max_daily_appointments",
        rule_value={"limit": 60},
        effective_start=ORIGINAL_START - timedelta(days=30),
    )
    slots = []
    for hour in (8, 9, 10, 12, 13, 15, 17, 19):
        slots.append(
            _slot_at(
                session,
                indy.id,
                DEMO_DAY.replace(hour=hour, minute=0),
                DEMO_DAY.replace(hour=hour, minute=30),
                1 if hour >= 17 else 2,
            )
        )
    roster = [
        ("demo-driver-omar", "Omar Indy", "IND-OMAR-VAN", "SHP-IND-001", "Louisville, KY", 8),
        ("demo-driver-elena", "Elena Indy", "IND-ELENA-VAN", "SHP-IND-002", "Cincinnati, OH", 9),
        ("demo-driver-brett", "Brett Indy", "IND-BRETT-VAN", "SHP-IND-003", "Fort Wayne, IN", 10),
        ("demo-driver-jade", "Jade Indy", "IND-JADE-VAN", "SHP-IND-004", "Bloomington, IN", 12),
        ("demo-driver-theo", "Theo Indy", "IND-THEO-VAN", "SHP-IND-005", "Columbus, OH", 13),
        ("demo-driver-nina-dal", "Nina Dallas", "DAL-NINA-VAN", "SHP-DAL-201", "Plano, TX", None),
        ("demo-driver-marcus", "Marcus Dallas", "DAL-MARCUS-VAN", "SHP-DAL-202", "Arlington, TX", None),
    ]
    dallas = session.query(Facility).filter_by(code="DAL-DC").one()
    created: list[Shipment] = []
    for external_id, name, plate, number, origin, hour in roster:
        driver = _driver(
            session,
            carrier,
            external_id=external_id,
            name=name,
            phone="+15552" + plate[-4:],
        )
        vehicle = _vehicle(session, carrier, license_plate=plate)
        if number.startswith("SHP-IND"):
            dest_facility = indy
            dest_name = "Indianapolis Inbound Hub"
            slot = next(s for s in slots if as_chicago(s.start_time).hour == hour)
            dock = docks[0]
            status = ShipmentStatus.IN_TRANSIT
        else:
            dest_facility = dallas
            dest_name = "Dallas Distribution Center"
            slot = _slot_at(
                session,
                dallas.id,
                DEMO_DAY.replace(hour=15 if "201" in number else 17, minute=0),
                DEMO_DAY.replace(hour=15 if "201" in number else 17, minute=30),
                1,
            )
            dock = session.query(Dock).filter_by(facility_id=dallas.id, name="Dock B").one()
            status = ShipmentStatus.ASSIGNED
        shipment = _shipment(
            session,
            carrier,
            shipment_number=number,
            driver=driver,
            vehicle=vehicle,
            origin=origin,
            destination=dest_name,
            facility=dest_facility,
            status=status,
            weight_kg="7200",
            pallet_count=9,
        )
        _ensure_eta(
            session,
            shipment,
            new_eta=slot.start_time + timedelta(minutes=5),
            timestamp=DEMO_DAY.replace(hour=7, minute=30),
            source=ETASource.DISPATCH,
            reason="Scheduled inbound",
        )
        appt_status = (
            AppointmentStatus.CONFIRMED
            if number in {"SHP-IND-001", "SHP-IND-002", "SHP-DAL-201"}
            else AppointmentStatus.REQUESTED
        )
        pad_tag = "DEMO:PAD-CONFIRMED" if appt_status == AppointmentStatus.CONFIRMED else "DEMO:PAD-REQUESTED"
        _appointment(
            session,
            shipment=shipment,
            facility=dest_facility,
            slot=slot,
            dock=dock,
            status=appt_status,
            notes=DEMO_PAD_CONFIRMED if appt_status == AppointmentStatus.CONFIRMED else DEMO_PAD_REQUESTED,
            tag=pad_tag,
        )
        if number == "SHP-IND-005":
            _appointment(
                session,
                shipment=shipment,
                facility=dest_facility,
                slot=slots[0],
                dock=dock,
                status=AppointmentStatus.CANCELLED,
                notes=DEMO_HISTORY_NOTES + " IND",
                tag="DEMO:HISTORY",
            )
        created.append(shipment)
        _sync_slot_fill(session, slot)
    return {"facility": indy, "docks": docks, "slots": slots, "shipments": created}


def seed_ops_demo(session: Session) -> dict[str, object]:
    carrier = _carrier(session)
    dallas = _seed_dallas_hero(session, carrier)
    chicago_base = _seed_chicago_base(session, carrier, dallas["original_eta_ts"])
    scarce = _seed_scarce_chicago(
        session,
        carrier,
        chicago_base["facility"],
        chicago_base["alex"],
        chicago_base["dock_a"],
        chicago_base["original_slot"],
        chicago_base["alt_a"],
        chicago_base["alt_b"],
    )
    _seed_indianapolis(session, carrier)
    session.commit()
    return {
        "carrier_id": str(carrier.id),
        "driver_id": str(dallas["driver"].id),
        "facility_id": str(dallas["facility"].id),
        "shipment_id": str(dallas["shipment"].id),
        "shipment_number": dallas["shipment"].shipment_number,
        "chicago_facility_id": str(chicago_base["facility"].id),
        "chicago_shipment_id": str(chicago_base["shipment"].id),
        "chicago_shipment_number": chicago_base["shipment"].shipment_number,
        "original_slot_id": str(dallas["original_slot"].id),
        "option_slot_ids": [str(dallas["alt_a"].id), str(dallas["alt_b"].id)],
        "dock_a_id": str(dallas["dock_a"].id),
        "dock_b_id": str(dallas["dock_b"].id),
        "hero_facility": chicago_base["facility"].name,
        "hero_facility_code": chicago_base["facility"].code,
        "hero_drivers": [driver.name for driver in scarce["hero_drivers"]],
        "hero_shipment_numbers": list(scarce["hero_shipments"].keys()),
        "hero_slot_ids": {
            "19:30": str(scarce["slot_1930"].id),
            "20:00": str(scarce["slot_2000"].id),
            "20:00-21:00": str(scarce["slot_2000_wide"].id),
            "21:00": str(scarce["slot_2100"].id),
            "20:30": str(scarce["slot_0830"].id),
        },
        "reschedule_shipment_id": str(scarce["reschedule_shipment"].id),
        "reschedule_shipment_number": scarce["reschedule_shipment"].shipment_number,
        "reschedule_original_appointment_id": str(scarce["reschedule_original"].id),
        "race_shipment_id": str(scarce["race_shipment"].id),
        "race_shipment_number": scarce["race_shipment"].shipment_number,
        "race_proposal_id": str(scarce["race_proposal"].id),
        "race_slot_id": str(scarce["slot_2000"].id),
        "nocap_shipment_id": str(scarce["nocap_shipment"].id),
        "nocap_shipment_number": scarce["nocap_shipment"].shipment_number,
    }


def collect_seed_counts(session: Session) -> dict[str, int]:
    return {
        "drivers": session.query(Driver).count(),
        "shipments": session.query(Shipment).count(),
        "facilities": session.query(Facility).count(),
        "docks": session.query(Dock).count(),
        "slots": session.query(AppointmentSlot).count(),
        "confirmed": session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count(),
        "held": session.query(Appointment).filter(Appointment.status == AppointmentStatus.HELD).count(),
        "requested": session.query(Appointment).filter(Appointment.status == AppointmentStatus.REQUESTED).count(),
        "proposals": session.query(Appointment)
        .filter(
            Appointment.status == AppointmentStatus.REQUESTED,
            Appointment.notes.contains(PROPOSAL_MARKER),
        )
        .count(),
        "cancelled": session.query(Appointment).filter(Appointment.status == AppointmentStatus.CANCELLED).count(),
        "exceptions": session.query(DriverException).count(),
        "eta_updates": session.query(ETAUpdate).count(),
        "checkins": session.query(FacilityCheckin).count(),
    }


def print_demo_report(session: Session, result: dict[str, object]) -> None:
    counts = collect_seed_counts(session)
    print()
    print("=" * 50)
    print("SETUHAUL DEMO SCENARIOS")
    print("=" * 50)
    print()
    print("HERO SCENARIO")
    print(f"Facility: {result['hero_facility']} ({result['hero_facility_code']})")
    print(f"Facility ID: {result['chicago_facility_id']}")
    print("Drivers: " + " / ".join(result["hero_drivers"]))  # type: ignore[arg-type]
    print("Shipments: " + ", ".join(result["hero_shipment_numbers"]))  # type: ignore[arg-type]
    print(f"Competition: 5 drivers / 3 compatible evening slots (ETA 8:00 PM)")
    print("Compatible slots (overlapping windows containing 8:00 PM):")
    slots = result["hero_slot_ids"]
    print(f"  7:30 PM  19:30-20:30  capacity=1  id={slots['19:30']}")  # type: ignore[index]
    print(f"  8:00 PM  20:00-20:30  capacity=1  id={slots['20:00']}")  # type: ignore[index]
    print(f"  8:00 PM  20:00-21:00  capacity=1  id={slots['20:00-21:00']}")  # type: ignore[index]
    print(f"  9:00 PM  21:00-21:30  occupied / not compatible with 8:00 PM ETA  id={slots['21:00']}")  # type: ignore[index]
    print()
    print("RESCHEDULE")
    print(f"Shipment: {result['reschedule_shipment_number']}")
    print(f"Shipment ID: {result['reschedule_shipment_id']}")
    print(f"Original appointment ID: {result['reschedule_original_appointment_id']}")
    print("Original: 6:30 PM CONFIRMED (seeded so history exists before the live delay demo)")
    print(f"Target: 8:30 PM open slot id={slots['20:30']}")  # type: ignore[index]
    print("Seed does not confirm 8:30 PM. Exercise: delay already recorded -> propose 8:30 -> confirm.")
    print()
    print("CONCURRENCY")
    print(f"Shipment: {result['race_shipment_number']}")
    print(f"Shipment ID: {result['race_shipment_id']}")
    print(f"Proposal: {result['race_proposal_id']}")
    print(f"Slot: {result['race_slot_id']}  20:00-20:30  Capacity: 1")
    print("Proposal status: requested (does not consume capacity). Re-seed refreshes created_at (30-minute TTL).")
    print("Do not pre-create winner/loser/stale rows. Race belongs to Stage 4.")
    print()
    print("NO CAPACITY")
    print(f"Shipment: {result['nocap_shipment_number']}")
    print(f"Shipment ID: {result['nocap_shipment_id']}")
    print("Expected: human escalation after get_available_options finds no feasible slot")
    print("Condition: latest ETA 9:15 PM; every Chicago slot that contains that ETA is already confirmed full.")
    print()
    print("COUNTS")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    print("=" * 50)


def main() -> None:
    assert_live_demo_target()
    session = SessionLocal()
    try:
        result = seed_ops_demo(session)
        print("Seeded operations demo:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        print_demo_report(session, result)
    finally:
        session.close()


if __name__ == "__main__":
    main()
