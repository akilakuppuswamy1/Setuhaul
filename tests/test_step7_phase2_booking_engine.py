"""Phase 2 booking-engine verification: SHOW ≠ PROPOSE ≠ CONFIRM ≠ ALLOCATE.

Uses isolated fixtures only. PostgreSQL concurrency tests target setuhaul_test.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.core.database import Base, get_db
from app.core.exceptions import ConflictError
from app.engines.feasibility.models import FeasibilityOutcome
from app.engines.feasibility.rules import CAPACITY_CONSUMING_APPOINTMENT_STATUSES
from app.main import app as fastapi_app
from app.models import Appointment, AppointmentSlot, Carrier, Dock, Driver, Facility, Shipment, Vehicle
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    DockStatus,
    EntityStatus,
    ETASource,
    ExceptionType,
    ShipmentStatus,
)
from app.repositories.appointment import AppointmentRepository
from app.schemas.allocation import AllocationRequest
from app.schemas.driver_exception import DriverExceptionCreate
from app.schemas.eta_update import ETAUpdateCreate
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.schemas.proposal import ProposalCreateRequest, ProposalStatus
from app.services.allocation import AllocationService
from app.services.appointment import AppointmentSlotService
from app.services.feasibility import FeasibilityService
from app.services.operations import DriverExceptionService, ETAUpdateService
from app.services.proposal import PROPOSAL_MARKER, ProposalService
from tests.db import DEMO_DATABASE_NAME, TEST_DATABASE_NAME, postgres_test_url, reset_public_schema

_CONSUMING = tuple(AppointmentStatus(status) for status in CAPACITY_CONSUMING_APPOINTMENT_STATUSES)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _count_status(session: Session, slot_id: uuid.UUID, *statuses: AppointmentStatus) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.appointment_slot_id == slot_id)
            .where(Appointment.status.in_(list(statuses)))
        )
        or 0
    )


def _consuming(session: Session, slot_id: uuid.UUID) -> int:
    return _count_status(session, slot_id, *_CONSUMING)


def _confirmed(session: Session, slot_id: uuid.UUID) -> int:
    return _count_status(session, slot_id, AppointmentStatus.CONFIRMED)


def _active_confirmed(session: Session, shipment_id: uuid.UUID) -> list[Appointment]:
    return list(
        session.scalars(
            select(Appointment)
            .where(Appointment.shipment_id == shipment_id)
            .where(Appointment.status == AppointmentStatus.CONFIRMED)
        ).all()
    )


def _feasible_options(session: Session, shipment_id: uuid.UUID, facility_id: uuid.UUID):
    slots = AppointmentSlotService(session).list_open_for_facility(facility_id)
    feasibility = FeasibilityService(session)
    options = []
    for slot in sorted(slots, key=lambda item: (item.start_time, str(item.id))):
        evaluation = feasibility.evaluate(
            shipment_id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=slot.id,
                ignore_delay_exceptions=True,
            ),
        )
        if evaluation.feasible:
            options.append((slot, evaluation))
    return options


def _snapshot_capacity(session: Session, slot: AppointmentSlot, dock: Dock) -> dict[str, object]:
    session.refresh(slot)
    session.refresh(dock)
    return {
        "consuming": _consuming(session, slot.id),
        "confirmed": _confirmed(session, slot.id),
        "slot_status": slot.status,
        "dock_status": dock.status,
    }


def _build_world(
    session: Session,
    *,
    with_original: bool = False,
    alt_capacity: int = 1,
    original_capacity: int = 1,
) -> dict[str, object]:
    now = _utc(2026, 8, 13, 10, 0)
    carrier = Carrier(
        name="P2 Carrier",
        code=f"P2C-{uuid.uuid4().hex[:6]}",
        status=EntityStatus.ACTIVE,
    )
    driver = Driver(carrier=carrier, name="P2 Driver", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate=f"P2-{uuid.uuid4().hex[:4]}",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        status=EntityStatus.ACTIVE,
    )
    facility = Facility(
        name="P2 Facility",
        code=f"P2F-{uuid.uuid4().hex[:6]}",
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
        capacity=original_capacity,
        status=AppointmentSlotStatus.OPEN,
    )
    alt_slot = AppointmentSlot(
        facility=facility,
        start_time=now + timedelta(hours=4),
        end_time=now + timedelta(hours=5),
        capacity=alt_capacity,
        status=AppointmentSlotStatus.OPEN,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number=f"P2-{uuid.uuid4().hex[:8]}",
        origin_location="Origin",
        destination_location="P2 Facility",
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("8000"),
        pallet_count=12,
    )
    session.add_all(
        [carrier, driver, vehicle, facility, dock_a, dock_b, original_slot, alt_slot, shipment]
    )
    session.flush()
    shipment.destination_facility_id = facility.id
    session.commit()
    ETAUpdateService(session).create(
        shipment.id,
        ETAUpdateCreate(
            new_eta=now + timedelta(hours=2, minutes=15),
            update_timestamp=now,
            source=ETASource.DISPATCH,
        ),
    )

    original_appointment_id = None
    if with_original:
        allocated = AllocationService(session).allocate(
            shipment.id,
            AllocationRequest(
                appointment_slot_id=original_slot.id,
                dock_id=dock_a.id,
                evaluated_at=now,
            ),
        )
        original_appointment_id = allocated.appointment.id

    return {
        "now": now,
        "carrier": carrier,
        "driver": driver,
        "shipment": shipment,
        "facility": facility,
        "dock_a": dock_a,
        "dock_b": dock_b,
        "original_slot": original_slot,
        "alt_slot": alt_slot,
        "original_appointment_id": original_appointment_id,
    }


def _second_shipment(session: Session, world: dict[str, object], label: str) -> Shipment:
    facility = session.get(Facility, world["facility"].id)
    assert facility is not None
    carrier = session.get(Carrier, world["carrier"].id)
    assert carrier is not None
    driver = Driver(carrier=carrier, name=f"Driver {label}", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate=f"V-{label}-{uuid.uuid4().hex[:3]}",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        status=EntityStatus.ACTIVE,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number=f"P2-{label}-{uuid.uuid4().hex[:6]}",
        origin_location="Origin",
        destination_location=facility.name,
        destination_facility_id=facility.id,
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("5000"),
        pallet_count=10,
    )
    session.add_all([driver, vehicle, shipment])
    session.flush()
    ETAUpdateService(session).create(
        shipment.id,
        ETAUpdateCreate(
            new_eta=world["now"] + timedelta(hours=4, minutes=15),
            update_timestamp=world["now"],
            source=ETASource.DISPATCH,
        ),
    )
    return shipment


def _report_delay(session: Session, world: dict[str, object]) -> None:
    DriverExceptionService(session).create(
        world["shipment"].id,
        DriverExceptionCreate(
            exception_type=ExceptionType.TRAFFIC,
            occurred_at=world["now"] + timedelta(minutes=5),
            driver_id=world["driver"].id,
            description="traffic delay",
        ),
    )
    ETAUpdateService(session).create(
        world["shipment"].id,
        ETAUpdateCreate(
            new_eta=world["now"] + timedelta(hours=4, minutes=15),
            update_timestamp=world["now"] + timedelta(minutes=5),
            source=ETASource.DRIVER,
            reason="traffic / driver delay",
        ),
    )


@pytest.fixture
def postgres_url() -> str:
    url = postgres_test_url()
    if url is None:
        pytest.skip("PostgreSQL unavailable for Phase 2 concurrency tests")
    return url


@pytest.fixture
def postgres_engine(postgres_url: str):
    engine = create_engine(postgres_url, poolclass=NullPool)
    with engine.connect() as connection:
        connected = connection.execute(text("SELECT current_database()")).scalar()
        assert connected == TEST_DATABASE_NAME
        assert connected != DEMO_DATABASE_NAME
    with engine.begin() as connection:
        reset_public_schema(connection)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


class TestDatabaseIsolation:
    def test_postgres_target_is_setuhaul_test(self, postgres_url: str) -> None:
        engine = create_engine(postgres_url, poolclass=NullPool)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_database()")).scalar() == TEST_DATABASE_NAME
        engine.dispose()


class TestNormalBookingEndToEnd:
    def test_delay_options_proposal_confirm_allocation(self, db_session: Session) -> None:
        world = _build_world(db_session)
        shipment_id = world["shipment"].id
        original_slot = world["original_slot"]
        alt_slot = world["alt_slot"]
        dock_b = world["dock_b"]

        before_exception = {
            "confirmed_original": _confirmed(db_session, original_slot.id),
            "confirmed_alt": _confirmed(db_session, alt_slot.id),
            "consuming_alt": _consuming(db_session, alt_slot.id),
        }
        assert before_exception["confirmed_original"] == 0
        assert before_exception["confirmed_alt"] == 0

        _report_delay(db_session, world)

        original_eval = FeasibilityService(db_session).evaluate(
            shipment_id,
            FeasibilityEvaluateRequest(appointment_slot_id=original_slot.id),
        )
        assert original_eval.outcome != FeasibilityOutcome.FEASIBLE
        assert original_eval.feasible is False

        before_options = _snapshot_capacity(db_session, alt_slot, dock_b)
        options = _feasible_options(db_session, shipment_id, world["facility"].id)
        assert [slot.id for slot, _ in options] == [alt_slot.id]
        assert _snapshot_capacity(db_session, alt_slot, dock_b) == before_options
        assert _confirmed(db_session, original_slot.id) == before_exception["confirmed_original"]
        assert _confirmed(db_session, alt_slot.id) == before_exception["confirmed_alt"]

        created = ProposalService(db_session).create(
            shipment_id,
            ProposalCreateRequest(appointment_slot_id=alt_slot.id, dock_id=dock_b.id),
        )
        assert created.status == ProposalStatus.PROPOSED
        assert created.appointment_id is None
        assert "confirm" not in created.message.lower() or created.status != ProposalStatus.CONFIRMED

        proposal_row = db_session.get(Appointment, created.proposal_id)
        assert proposal_row is not None
        assert proposal_row.status == AppointmentStatus.REQUESTED
        assert PROPOSAL_MARKER in (proposal_row.notes or "")
        assert _confirmed(db_session, alt_slot.id) == 0
        assert _consuming(db_session, alt_slot.id) == 0
        db_session.refresh(alt_slot)
        db_session.refresh(dock_b)
        assert alt_slot.status == AppointmentSlotStatus.OPEN
        assert dock_b.status == DockStatus.AVAILABLE

        accepted = ProposalService(db_session).accept(created.proposal_id)
        assert accepted.status == ProposalStatus.CONFIRMED
        assert accepted.appointment_id is not None
        assert accepted.message == "Proposal confirmed"

        booked = db_session.get(Appointment, accepted.appointment_id)
        proposal_row = db_session.get(Appointment, created.proposal_id)
        db_session.refresh(alt_slot)
        db_session.refresh(dock_b)
        assert booked is not None
        assert booked.status == AppointmentStatus.CONFIRMED
        assert booked.appointment_slot_id == alt_slot.id
        assert booked.dock_id == dock_b.id
        assert _confirmed(db_session, alt_slot.id) == 1
        assert _consuming(db_session, alt_slot.id) == 1
        assert alt_slot.status == AppointmentSlotStatus.FULL
        assert dock_b.status == DockStatus.OCCUPIED
        assert proposal_row is not None
        assert proposal_row.status == AppointmentStatus.CANCELLED
        assert f"confirmed_appointment_id={booked.id}" in (proposal_row.notes or "")
        assert "stale_reason=" not in (proposal_row.notes or "")
        assert len(_active_confirmed(db_session, shipment_id)) == 1


class TestProposalDoesNotConsumeCapacity:
    def test_create_proposal_leaves_slot_open_for_competitor(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _report_delay(db_session, world)
        service = ProposalService(db_session)
        created = service.create(
            world["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
            ),
        )
        assert created.status == ProposalStatus.PROPOSED
        proposal_row = db_session.get(Appointment, created.proposal_id)
        assert proposal_row is not None
        assert proposal_row.status == AppointmentStatus.REQUESTED
        assert _consuming(db_session, world["alt_slot"].id) == 0
        db_session.refresh(world["alt_slot"])
        db_session.refresh(world["dock_b"])
        assert world["alt_slot"].status == AppointmentSlotStatus.OPEN
        assert world["dock_b"].status == DockStatus.AVAILABLE

        rival = _second_shipment(db_session, world, "RIVAL")
        AllocationService(db_session).allocate(
            rival.id,
            AllocationRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
                evaluated_at=world["now"],
            ),
        )
        assert _confirmed(db_session, world["alt_slot"].id) == 1
        assert _consuming(db_session, world["alt_slot"].id) == 1


class TestConfirmationRevalidates:
    def test_stale_when_competitor_consumes_before_accept(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _report_delay(db_session, world)
        service = ProposalService(db_session)
        created = service.create(
            world["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
            ),
        )
        rival = _second_shipment(db_session, world, "B")
        AllocationService(db_session).allocate(
            rival.id,
            AllocationRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
                evaluated_at=world["now"],
            ),
        )
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)

        fetched = service.get(created.proposal_id)
        assert fetched.status == ProposalStatus.STALE
        assert fetched.appointment_id is None
        assert fetched.reason in ("slot_capacity_changed", "feasibility_changed")
        assert _confirmed(db_session, world["alt_slot"].id) == 1
        assert _consuming(db_session, world["alt_slot"].id) == 1
        assert len(_active_confirmed(db_session, world["shipment"].id)) == 0
        assert _confirmed(db_session, world["original_slot"].id) == 0


class TestStaleProposal:
    def test_accept_after_capacity_change_is_conflict(self, db_session: Session) -> None:
        world = _build_world(db_session, alt_capacity=1)
        _report_delay(db_session, world)
        service = ProposalService(db_session)
        created = service.create(
            world["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=world["alt_slot"].id),
        )
        world["alt_slot"].capacity = 0
        db_session.commit()
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)
        fetched = service.get(created.proposal_id)
        assert fetched.status == ProposalStatus.STALE
        assert len(_active_confirmed(db_session, world["shipment"].id)) == 0
        assert _consuming(db_session, world["alt_slot"].id) == 0


class TestSequentialIdempotentRetry:
    def test_second_accept_returns_same_appointment(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _report_delay(db_session, world)
        service = ProposalService(db_session)
        created = service.create(
            world["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
            ),
        )
        first = service.accept(created.proposal_id)
        second = service.accept(created.proposal_id)
        assert second.status == ProposalStatus.CONFIRMED
        assert second.appointment_id == first.appointment_id
        assert "already confirmed" in second.message.lower()
        assert _confirmed(db_session, world["alt_slot"].id) == 1
        assert _consuming(db_session, world["alt_slot"].id) == 1


class TestConfirmedReschedule:
    def test_atomic_reschedule_preserves_history(self, db_session: Session) -> None:
        world = _build_world(db_session, with_original=True)
        original_id = world["original_appointment_id"]
        assert original_id is not None
        _report_delay(db_session, world)

        original_eval = FeasibilityService(db_session).evaluate(
            world["shipment"].id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=world["original_slot"].id,
                ignore_delay_exceptions=True,
            ),
        )
        assert original_eval.feasible is False

        service = ProposalService(db_session)
        created = service.create(
            world["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
            ),
        )
        original = db_session.get(Appointment, original_id)
        assert original is not None
        assert original.status == AppointmentStatus.CONFIRMED
        assert created.status == ProposalStatus.PROPOSED
        assert _confirmed(db_session, world["original_slot"].id) == 1
        assert _confirmed(db_session, world["alt_slot"].id) == 0

        accepted = service.accept(created.proposal_id)
        original = db_session.get(Appointment, original_id)
        booked = db_session.get(Appointment, accepted.appointment_id)
        db_session.refresh(world["original_slot"])
        db_session.refresh(world["alt_slot"])
        db_session.refresh(world["dock_a"])
        db_session.refresh(world["dock_b"])

        assert original is not None and booked is not None
        assert original.status == AppointmentStatus.CANCELLED
        assert original.appointment_slot_id == world["original_slot"].id
        assert f"superseded_by={booked.id}" in (original.notes or "")
        assert booked.status == AppointmentStatus.CONFIRMED
        assert booked.id != original.id
        assert booked.appointment_slot_id == world["alt_slot"].id
        assert booked.dock_id == world["dock_b"].id
        assert world["original_slot"].status == AppointmentSlotStatus.OPEN
        assert world["alt_slot"].status == AppointmentSlotStatus.FULL
        assert world["dock_a"].status == DockStatus.AVAILABLE
        assert world["dock_b"].status == DockStatus.OCCUPIED
        assert len(_active_confirmed(db_session, world["shipment"].id)) == 1
        listed = db_session.scalars(
            select(Appointment).where(Appointment.shipment_id == world["shipment"].id)
        ).all()
        assert original in listed


class TestRescheduleRollback:
    def test_failure_after_supersede_rolls_back(self, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        world = _build_world(db_session, with_original=True)
        original_id = world["original_appointment_id"]
        _report_delay(db_session, world)
        service = ProposalService(db_session)
        created = service.create(
            world["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
            ),
        )
        original_supersede = AllocationService._supersede_active

        def fail_after_supersede(self: AllocationService, existing: Appointment) -> None:
            original_supersede(self, existing)
            raise ConflictError("forced allocation failure after supersede")

        monkeypatch.setattr(AllocationService, "_supersede_active", fail_after_supersede)
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)

        original = db_session.get(Appointment, original_id)
        db_session.refresh(world["original_slot"])
        db_session.refresh(world["alt_slot"])
        db_session.refresh(world["dock_a"])
        db_session.refresh(world["dock_b"])
        assert original is not None
        assert original.status == AppointmentStatus.CONFIRMED
        assert world["original_slot"].status == AppointmentSlotStatus.FULL
        assert world["alt_slot"].status == AppointmentSlotStatus.OPEN
        assert world["dock_a"].status == DockStatus.OCCUPIED
        assert world["dock_b"].status == DockStatus.AVAILABLE
        assert _confirmed(db_session, world["original_slot"].id) == 1
        assert _confirmed(db_session, world["alt_slot"].id) == 0
        assert len(_active_confirmed(db_session, world["shipment"].id)) == 1


class TestNoCapacity:
    def test_zero_options_does_not_book_or_mutate(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _report_delay(db_session, world)
        world["alt_slot"].status = AppointmentSlotStatus.CLOSED
        db_session.commit()

        before_original = _snapshot_capacity(db_session, world["original_slot"], world["dock_a"])
        before_alt = _snapshot_capacity(db_session, world["alt_slot"], world["dock_b"])
        appointments_before = int(db_session.scalar(select(func.count()).select_from(Appointment)) or 0)

        options = _feasible_options(db_session, world["shipment"].id, world["facility"].id)
        assert options == []

        from tests.test_step8_conversation import _service
        from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest

        convo = _service(db_session)
        created = convo.create_thread(
            ConversationCreateRequest(
                driver_id=world["driver"].id,
                shipment_id=world["shipment"].id,
            )
        )
        result = convo.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="What options do I have?"),
        )
        names = [call.name for call in result.tool_calls]
        assert "get_available_options" in names
        assert "create_proposal" not in names
        assert "accept_proposal" not in names
        assert "request_human_escalation" in names
        assert result.requires_human is True

        assert _snapshot_capacity(db_session, world["original_slot"], world["dock_a"]) == before_original
        assert _snapshot_capacity(db_session, world["alt_slot"], world["dock_b"]) == before_alt
        appointments_after = int(db_session.scalar(select(func.count()).select_from(Appointment)) or 0)
        assert appointments_after == appointments_before
        assert len(_active_confirmed(db_session, world["shipment"].id)) == 0


class TestOriginalRetainedWhileProposalPending:
    def test_proposal_does_not_cancel_confirmed_original(self, db_session: Session) -> None:
        world = _build_world(db_session, with_original=True)
        original_id = world["original_appointment_id"]
        _report_delay(db_session, world)
        created = ProposalService(db_session).create(
            world["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
            ),
        )
        original = db_session.get(Appointment, original_id)
        proposal = db_session.get(Appointment, created.proposal_id)
        assert original is not None and proposal is not None
        assert original.status == AppointmentStatus.CONFIRMED
        assert proposal.status == AppointmentStatus.REQUESTED
        assert _consuming(db_session, world["original_slot"].id) == 1
        assert _consuming(db_session, world["alt_slot"].id) == 0

        ProposalService(db_session).accept(created.proposal_id)
        original = db_session.get(Appointment, original_id)
        assert original is not None
        assert original.status == AppointmentStatus.CANCELLED
        assert len(_active_confirmed(db_session, world["shipment"].id)) == 1


class TestCapacityInvariants:
    def test_requested_does_not_count_as_consuming(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _report_delay(db_session, world)
        ProposalService(db_session).create(
            world["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=world["alt_slot"].id),
        )
        requested = _count_status(db_session, world["alt_slot"].id, AppointmentStatus.REQUESTED)
        assert requested == 1
        assert _consuming(db_session, world["alt_slot"].id) == 0
        assert _consuming(db_session, world["alt_slot"].id) <= world["alt_slot"].capacity


class TestApiDbConsistency:
    def test_accept_http_matches_database(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _report_delay(db_session, world)
        created = ProposalService(db_session).create(
            world["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
            ),
        )

        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(fastapi_app) as client:
                response = client.post(f"/proposals/{created.proposal_id}/accept")
                assert response.status_code == 200
                body = response.json()
                assert body["status"] == "confirmed"
                appointment_id = uuid.UUID(body["appointment_id"])
                booked = db_session.get(Appointment, appointment_id)
                assert booked is not None
                assert booked.status == AppointmentStatus.CONFIRMED
                assert _confirmed(db_session, world["alt_slot"].id) == 1
                fetched = client.get(f"/proposals/{created.proposal_id}")
                assert fetched.status_code == 200
                assert fetched.json()["status"] == "confirmed"
                assert fetched.json()["appointment_id"] == body["appointment_id"]
        finally:
            fastapi_app.dependency_overrides.clear()

    def test_stale_http_does_not_create_confirmed_row(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _report_delay(db_session, world)
        created = ProposalService(db_session).create(
            world["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=world["alt_slot"].id),
        )
        rival = _second_shipment(db_session, world, "HTTPB")
        AllocationService(db_session).allocate(
            rival.id,
            AllocationRequest(
                appointment_slot_id=world["alt_slot"].id,
                evaluated_at=world["now"],
            ),
        )

        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(fastapi_app) as client:
                response = client.post(f"/proposals/{created.proposal_id}/accept")
            assert response.status_code == 409
            detail = response.json()["detail"].lower()
            assert "stale" in detail
            assert "appointment_id" not in response.json() or response.json().get("appointment_id") in (None, "")
            assert len(_active_confirmed(db_session, world["shipment"].id)) == 0
            fetched = ProposalService(db_session).get(created.proposal_id)
            assert fetched.status == ProposalStatus.STALE
        finally:
            fastapi_app.dependency_overrides.clear()


def _gated_try_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    original = AppointmentRepository.try_acquire_shipment_advisory_lock
    gate = threading.Barrier(2, timeout=15)
    seen = {"n": 0}
    lock = threading.Lock()

    def gated(self: AppointmentRepository, shipment_id: uuid.UUID) -> bool:
        with lock:
            seen["n"] += 1
            call_number = seen["n"]
        if call_number <= 2:
            gate.wait()
        return original(self, shipment_id)

    monkeypatch.setattr(AppointmentRepository, "try_acquire_shipment_advisory_lock", gated)


class TestConcurrentSameProposalHttp:
    def test_two_overlapping_accepts_one_winner_one_loser(
        self, postgres_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        world = _build_world(session)
        _report_delay(session, world)
        created = ProposalService(session).create(
            world["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
            ),
        )
        proposal_id = created.proposal_id
        slot_id = world["alt_slot"].id
        dock_id = world["dock_b"].id
        shipment_id = world["shipment"].id
        session.close()

        def override_get_db():
            worker = session_factory()
            try:
                yield worker
            finally:
                worker.close()

        fastapi_app.dependency_overrides[get_db] = override_get_db
        _gated_try_acquire(monkeypatch)
        client = TestClient(fastapi_app)

        def post_accept() -> tuple[int, dict]:
            response = client.post(f"/proposals/{proposal_id}/accept")
            try:
                body = response.json()
            except Exception:  # noqa: BLE001
                body = {"detail": response.text}
            return response.status_code, body

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = [future.result() for future in as_completed([executor.submit(post_accept) for _ in range(2)])]
        finally:
            fastapi_app.dependency_overrides.clear()

        statuses = [status for status, _ in results]
        winners = [body for status, body in results if status == 200]
        losers = [body for status, body in results if status == 409]
        assert statuses.count(200) == 1
        assert statuses.count(409) == 1
        assert winners[0]["status"] == "confirmed"
        assert winners[0]["appointment_id"] is not None
        loser_detail = str(losers[0].get("detail", "")).lower()
        assert "stale" in loser_detail or "conflict" in loser_detail
        assert losers[0].get("status") != "confirmed"
        assert losers[0].get("appointment_id") in (None, "", [])

        verify = session_factory()
        assert _confirmed(verify, slot_id) == 1
        assert _consuming(verify, slot_id) == 1
        slot_row = verify.get(AppointmentSlot, slot_id)
        dock_row = verify.get(Dock, dock_id)
        proposal_row = verify.get(Appointment, proposal_id)
        assert slot_row is not None and slot_row.status == AppointmentSlotStatus.FULL
        assert dock_row is not None and dock_row.status == DockStatus.OCCUPIED
        assert proposal_row is not None
        assert (proposal_row.notes or "").count("confirmed_appointment_id=") == 1
        assert "stale_reason=" not in (proposal_row.notes or "")
        retry = ProposalService(verify).accept(proposal_id)
        assert retry.status == ProposalStatus.CONFIRMED
        assert str(retry.appointment_id) == str(winners[0]["appointment_id"])
        assert len(_active_confirmed(verify, shipment_id)) == 1
        verify.close()


class TestConcurrentRescheduleHttp:
    def test_two_overlapping_reschedule_accepts(
        self, postgres_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        world = _build_world(session, with_original=True)
        original_id = world["original_appointment_id"]
        _report_delay(session, world)
        created = ProposalService(session).create(
            world["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=world["alt_slot"].id,
                dock_id=world["dock_b"].id,
            ),
        )
        proposal_id = created.proposal_id
        shipment_id = world["shipment"].id
        original_slot_id = world["original_slot"].id
        new_slot_id = world["alt_slot"].id
        session.close()

        def override_get_db():
            worker = session_factory()
            try:
                yield worker
            finally:
                worker.close()

        fastapi_app.dependency_overrides[get_db] = override_get_db
        _gated_try_acquire(monkeypatch)
        client = TestClient(fastapi_app)

        def post_accept() -> tuple[int, dict]:
            response = client.post(f"/proposals/{proposal_id}/accept")
            try:
                body = response.json()
            except Exception:  # noqa: BLE001
                body = {"detail": response.text}
            return response.status_code, body

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = [future.result() for future in as_completed([executor.submit(post_accept) for _ in range(2)])]
        finally:
            fastapi_app.dependency_overrides.clear()

        statuses = [status for status, _ in results]
        assert statuses.count(200) == 1
        assert statuses.count(409) == 1
        winner = next(body for status, body in results if status == 200)
        loser = next(body for status, body in results if status == 409)
        assert winner["status"] == "confirmed"
        assert "stale" in str(loser.get("detail", "")).lower() or "conflict" in str(loser.get("detail", "")).lower()

        verify = session_factory()
        original = verify.get(Appointment, original_id)
        assert original is not None
        assert original.status == AppointmentStatus.CANCELLED
        assert _confirmed(verify, new_slot_id) == 1
        assert _confirmed(verify, original_slot_id) == 0
        assert len(_active_confirmed(verify, shipment_id)) == 1
        retry = ProposalService(verify).accept(proposal_id)
        assert retry.status == ProposalStatus.CONFIRMED
        assert str(retry.appointment_id) == winner["appointment_id"]
        verify.close()
