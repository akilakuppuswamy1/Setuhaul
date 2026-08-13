"""Step 7 PostgreSQL concurrency tests for proposal acceptance."""

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
from app.schemas.proposal import ProposalCreateRequest, ProposalStatus
from app.services.proposal import ProposalService


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
        pytest.skip("PostgreSQL unavailable for Step 7 concurrency tests")
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
        shipment_number=f"SHP-{label}",
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


def _build_scenario(session: Session, *, slot_capacity: int = 1) -> dict[str, object]:
    now = _utc(2026, 8, 13, 10, 0)
    facility = Facility(
        name="PG Prop Facility",
        code=f"PG-{uuid.uuid4().hex[:4]}",
        timezone="UTC",
        status=EntityStatus.ACTIVE,
    )
    dock = Dock(
        facility=facility,
        name="Dock 1",
        dock_type="standard",
        max_weight_kg=Decimal("25000"),
        status=DockStatus.AVAILABLE,
    )
    slot = AppointmentSlot(
        facility=facility,
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
        capacity=slot_capacity,
        status=AppointmentSlotStatus.OPEN,
    )
    session.add_all([facility, dock, slot])
    session.commit()
    return {"facility": facility, "dock": dock, "slot": slot, "now": now}


def _confirmed_count(session: Session, slot_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.appointment_slot_id == slot_id)
            .where(Appointment.status == AppointmentStatus.CONFIRMED)
        )
        or 0
    )


class TestConcurrentProposalAcceptance:
    def test_two_proposals_competing_for_capacity(self, postgres_engine) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        data = _build_scenario(session, slot_capacity=1)
        shipment_a = _create_feasible_shipment(
            session,
            facility=data["facility"],
            slot=data["slot"],
            dock=data["dock"],
            now=data["now"],
            label="A",
        )
        shipment_b = _create_feasible_shipment(
            session,
            facility=data["facility"],
            slot=data["slot"],
            dock=data["dock"],
            now=data["now"],
            label="B",
        )
        service = ProposalService(session)
        proposal_a = service.create(
            shipment_a.id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        proposal_b = service.create(
            shipment_b.id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        slot_id = data["slot"].id
        proposal_a_id = proposal_a.proposal_id
        proposal_b_id = proposal_b.proposal_id
        session.close()

        def accept_proposal(proposal_id: uuid.UUID) -> tuple[str, str | None]:
            worker_session = session_factory()
            try:
                result = ProposalService(worker_session).accept(proposal_id)
                return ("confirmed", str(result.appointment_id))
            except ConflictError as exc:
                worker_session.rollback()
                return ("conflict", str(exc))
            finally:
                worker_session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(accept_proposal, proposal_a_id),
                executor.submit(accept_proposal, proposal_b_id),
            ]
            results = [future.result() for future in as_completed(futures)]

        verify_session = session_factory()
        confirmed = _confirmed_count(verify_session, slot_id)
        verify_session.close()

        outcomes = {outcome for outcome, _ in results}
        assert confirmed == 1
        assert "confirmed" in outcomes
        assert "conflict" in outcomes

    def test_same_proposal_accepted_concurrently(self, postgres_engine) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        data = _build_scenario(session, slot_capacity=1)
        shipment = _create_feasible_shipment(
            session,
            facility=data["facility"],
            slot=data["slot"],
            dock=data["dock"],
            now=data["now"],
            label="SINGLE",
        )
        service = ProposalService(session)
        proposal = service.create(
            shipment.id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        slot_id = data["slot"].id
        proposal_id = proposal.proposal_id
        session.close()

        def accept_once() -> tuple[str, str | None]:
            worker_session = session_factory()
            try:
                result = ProposalService(worker_session).accept(proposal_id)
                return ("confirmed", str(result.appointment_id))
            except ConflictError as exc:
                worker_session.rollback()
                return ("conflict", str(exc))
            finally:
                worker_session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(accept_once) for _ in range(2)]
            results = [future.result() for future in as_completed(futures)]

        verify_session = session_factory()
        confirmed = _confirmed_count(verify_session, slot_id)
        verify_session.close()

        confirmed_results = [aid for outcome, aid in results if outcome == "confirmed"]
        assert confirmed == 1
        assert len(confirmed_results) >= 1
        if len(confirmed_results) == 2:
            assert confirmed_results[0] == confirmed_results[1]

    def test_no_double_booking_under_concurrency(self, postgres_engine) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        data = _build_scenario(session, slot_capacity=2)
        shipments = [
            _create_feasible_shipment(
                session,
                facility=data["facility"],
                slot=data["slot"],
                dock=data["dock"],
                now=data["now"],
                label=f"S{i}",
            )
            for i in range(3)
        ]
        service = ProposalService(session)
        proposals = [
            service.create(
                shipment.id,
                ProposalCreateRequest(
                    appointment_slot_id=data["slot"].id,
                    dock_id=data["dock"].id,
                ),
            )
            for shipment in shipments
        ]
        slot_id = data["slot"].id
        proposal_ids = [proposal.proposal_id for proposal in proposals]
        session.close()

        def accept_proposal(proposal_id: uuid.UUID) -> str:
            worker_session = session_factory()
            try:
                ProposalService(worker_session).accept(proposal_id)
                return "confirmed"
            except ConflictError:
                worker_session.rollback()
                return "conflict"
            finally:
                worker_session.close()

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(
                executor.map(
                    accept_proposal,
                    proposal_ids,
                )
            )

        verify_session = session_factory()
        confirmed = _confirmed_count(verify_session, slot_id)
        verify_session.close()

        assert confirmed == 2
        assert results.count("confirmed") == 2
        assert results.count("conflict") == 1
