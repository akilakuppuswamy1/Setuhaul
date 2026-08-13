"""Step 6 PostgreSQL concurrency tests for allocation."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base
from app.core.exceptions import ConflictError
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
from app.schemas.allocation import AllocationRequest
from app.services.allocation import AllocationService


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _postgres_test_url() -> str | None:
    url = os.environ.get("DATABASE_URL", settings.database_url)
    if not url.startswith("postgresql"):
        return None
    try:
        engine = create_engine(url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return url
    except Exception:
        return None


@pytest.fixture
def postgres_url() -> str:
    url = _postgres_test_url()
    if url is None:
        pytest.skip("PostgreSQL unavailable for Step 6 concurrency tests")
    return url


@pytest.fixture
def postgres_engine(postgres_url: str):
    engine = create_engine(postgres_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _create_feasible_shipment(
    session: Session,
    *,
    facility: Facility,
    slot: AppointmentSlot,
    dock: Dock | None,
    now: datetime,
    label: str,
) -> Shipment:
    carrier = Carrier(
        name=f"Carrier {label}",
        code=f"C-{label}-{uuid.uuid4().hex[:4]}",
        status=EntityStatus.ACTIVE,
    )
    driver = Driver(carrier=carrier, name=f"Driver {label}", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate=f"V-{label}",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        status=EntityStatus.ACTIVE,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number=f"CONC-{label}-{uuid.uuid4().hex[:6]}",
        origin_location="Origin",
        destination_location=facility.name,
        destination_facility_id=facility.id,
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("5000"),
        pallet_count=10,
    )
    session.add_all([carrier, driver, vehicle, shipment])
    session.flush()
    session.add(
        ETAUpdate(
            shipment_id=shipment.id,
            previous_eta=None,
            new_eta=now + timedelta(hours=2, minutes=15),
            update_timestamp=now,
            source=ETASource.DISPATCH,
        )
    )
    session.commit()
    return shipment


def _setup_facility_slot(
    session: Session,
    *,
    capacity: int,
    dock_count: int = 0,
) -> dict[str, object]:
    now = _utc(2026, 8, 13, 10, 0)
    facility = Facility(
        name="Concurrency Facility",
        code=f"CF-{uuid.uuid4().hex[:6]}",
        timezone="UTC",
        status=EntityStatus.ACTIVE,
    )
    session.add(facility)
    session.flush()
    slot = AppointmentSlot(
        facility_id=facility.id,
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
        capacity=capacity,
        status=AppointmentSlotStatus.OPEN,
    )
    docks = [
        Dock(
            facility_id=facility.id,
            name=f"Dock-{i}",
            dock_type="standard",
            status=DockStatus.AVAILABLE,
        )
        for i in range(dock_count)
    ]
    session.add(slot)
    if docks:
        session.add_all(docks)
    session.commit()
    return {"facility": facility, "slot": slot, "docks": docks, "now": now}


def _allocate_worker(
    postgres_url: str,
    shipment_id: uuid.UUID,
    slot_id: uuid.UUID,
    dock_id: uuid.UUID | None,
    evaluated_at: datetime,
) -> str:
    engine = create_engine(postgres_url, poolclass=NullPool)
    session = sessionmaker(bind=engine)()
    try:
        session.execute(text("SET lock_timeout = '10s'"))
        AllocationService(session).allocate(
            shipment_id,
            AllocationRequest(
                appointment_slot_id=slot_id,
                dock_id=dock_id,
                evaluated_at=evaluated_at,
            ),
        )
        return "success"
    except ConflictError:
        session.rollback()
        return "conflict"
    except Exception:
        session.rollback()
        return "error"
    finally:
        session.close()
        engine.dispose()


def _count_slot_appointments(postgres_url: str, slot_id: uuid.UUID) -> int:
    engine = create_engine(postgres_url)
    session = sessionmaker(bind=engine)()
    try:
        return int(
            session.scalar(
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
    finally:
        session.close()
        engine.dispose()


class TestPostgreSQLConcurrency:
    def test_capacity_one_two_concurrent(self, postgres_url: str, postgres_engine) -> None:
        setup_session = sessionmaker(bind=postgres_engine)()
        data = _setup_facility_slot(setup_session, capacity=1)
        shipments = [
            _create_feasible_shipment(
                setup_session,
                facility=data["facility"],
                slot=data["slot"],
                dock=data["docks"][0] if data["docks"] else None,
                now=data["now"],
                label=str(i),
            )
            for i in range(2)
        ]
        slot_id = data["slot"].id
        shipment_ids = [s.id for s in shipments]
        setup_session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _allocate_worker,
                    postgres_url,
                    shipment_id,
                    slot_id,
                    None,
                    data["now"],
                )
                for shipment_id in shipment_ids
            ]
            results = [future.result() for future in as_completed(futures)]

        assert results.count("success") == 1
        assert results.count("conflict") == 1
        assert _count_slot_appointments(postgres_url, slot_id) == 1

    def test_capacity_two_three_concurrent(self, postgres_url: str, postgres_engine) -> None:
        setup_session = sessionmaker(bind=postgres_engine)()
        data = _setup_facility_slot(setup_session, capacity=2)
        shipments = [
            _create_feasible_shipment(
                setup_session,
                facility=data["facility"],
                slot=data["slot"],
                dock=None,
                now=data["now"],
                label=str(i),
            )
            for i in range(3)
        ]
        slot_id = data["slot"].id
        shipment_ids = [s.id for s in shipments]
        now = data["now"]
        setup_session.close()

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(
                    _allocate_worker,
                    postgres_url,
                    shipment_id,
                    slot_id,
                    None,
                    now,
                )
                for shipment_id in shipment_ids
            ]
            results = [future.result() for future in as_completed(futures)]

        assert results.count("success") == 2
        assert results.count("conflict") == 1
        assert _count_slot_appointments(postgres_url, slot_id) == 2

    def test_same_shipment_two_concurrent(self, postgres_url: str, postgres_engine) -> None:
        setup_session = sessionmaker(bind=postgres_engine)()
        data = _setup_facility_slot(setup_session, capacity=5)
        shipment = _create_feasible_shipment(
            setup_session,
            facility=data["facility"],
            slot=data["slot"],
            dock=None,
            now=data["now"],
            label="same",
        )
        slot_id = data["slot"].id
        shipment_id = shipment.id
        now = data["now"]
        setup_session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _allocate_worker,
                    postgres_url,
                    shipment_id,
                    slot_id,
                    None,
                    now,
                )
                for _ in range(2)
            ]
            results = [future.result() for future in as_completed(futures)]

        assert results.count("success") == 1
        assert results.count("conflict") == 1
        assert _count_slot_appointments(postgres_url, slot_id) == 1

    def test_same_dock_two_concurrent(self, postgres_url: str, postgres_engine) -> None:
        setup_session = sessionmaker(bind=postgres_engine)()
        data = _setup_facility_slot(setup_session, capacity=5, dock_count=1)
        dock = data["docks"][0]
        shipments = [
            _create_feasible_shipment(
                setup_session,
                facility=data["facility"],
                slot=data["slot"],
                dock=dock,
                now=data["now"],
                label=str(i),
            )
            for i in range(2)
        ]
        slot_id = data["slot"].id
        dock_id = dock.id
        shipment_ids = [s.id for s in shipments]
        now = data["now"]
        setup_session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _allocate_worker,
                    postgres_url,
                    shipment_id,
                    slot_id,
                    dock_id,
                    now,
                )
                for shipment_id in shipment_ids
            ]
            results = [future.result() for future in as_completed(futures)]

        assert results.count("success") == 1
        assert results.count("conflict") == 1

    def test_rollback_during_contention_allows_next(
        self, postgres_url: str, postgres_engine
    ) -> None:
        setup_session = sessionmaker(bind=postgres_engine)()
        data = _setup_facility_slot(setup_session, capacity=1)
        first = _create_feasible_shipment(
            setup_session,
            facility=data["facility"],
            slot=data["slot"],
            dock=None,
            now=data["now"],
            label="first",
        )
        second = _create_feasible_shipment(
            setup_session,
            facility=data["facility"],
            slot=data["slot"],
            dock=None,
            now=data["now"],
            label="second",
        )
        slot_id = data["slot"].id
        first_id = first.id
        second_id = second.id
        now = data["now"]

        assert _allocate_worker(postgres_url, first_id, slot_id, None, now) == "success"
        assert _allocate_worker(postgres_url, second_id, slot_id, None, now) == "conflict"

        third = _create_feasible_shipment(
            setup_session,
            facility=data["facility"],
            slot=data["slot"],
            dock=None,
            now=now,
            label="third",
        )
        new_slot = AppointmentSlot(
            facility_id=data["facility"].id,
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=3),
            capacity=1,
            status=AppointmentSlotStatus.OPEN,
        )
        setup_session.add(new_slot)
        setup_session.commit()
        third_id = third.id
        new_slot_id = new_slot.id
        setup_session.close()

        assert _allocate_worker(postgres_url, third_id, new_slot_id, None, now) == "success"
