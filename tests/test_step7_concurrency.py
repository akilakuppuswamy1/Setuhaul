"""Step 7 PostgreSQL concurrency tests for proposal acceptance."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.core.database import Base
from tests.db import postgres_test_url as _postgres_test_url
from tests.db import reset_public_schema
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
from app.repositories.appointment import AppointmentRepository
from app.schemas.allocation import AllocationRequest
from app.schemas.proposal import ProposalCreateRequest, ProposalStatus
from app.services.allocation import AllocationService
from app.services.proposal import ProposalService


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


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
        reset_public_schema(connection)
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
        conflict_results = [detail for outcome, detail in results if outcome == "conflict"]
        assert confirmed == 1
        assert len(confirmed_results) == 1
        assert len(conflict_results) == 1
        assert "stale" in (conflict_results[0] or "").lower() or "conflict" in (
            conflict_results[0] or ""
        ).lower()

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

    def test_same_proposal_two_concurrent_confirms_one_winner(self, postgres_engine) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        data = _build_scenario(session, slot_capacity=1)
        shipment = _create_feasible_shipment(
            session,
            facility=data["facility"],
            slot=data["slot"],
            dock=data["dock"],
            now=data["now"],
            label="RACE",
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
        dock_id = data["dock"].id
        shipment_id = shipment.id
        proposal_id = proposal.proposal_id
        session.close()

        def accept_once() -> tuple[str, str | None]:
            worker_session = session_factory()
            try:
                worker_session.execute(text("SET lock_timeout = '10s'"))
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

        verify = session_factory()
        confirmed_rows = list(
            verify.scalars(
                select(Appointment).where(
                    Appointment.appointment_slot_id == slot_id,
                    Appointment.status == AppointmentStatus.CONFIRMED,
                )
            ).all()
        )
        proposal_row = verify.get(Appointment, proposal_id)
        slot_row = verify.get(AppointmentSlot, slot_id)
        dock_row = verify.get(Dock, dock_id)
        consuming = int(
            verify.scalar(
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
        retry = ProposalService(verify).accept(proposal_id)
        verify.close()

        outcomes = [outcome for outcome, _ in results]
        winner_ids = {aid for outcome, aid in results if outcome == "confirmed" and aid}
        loser_details = [detail or "" for outcome, detail in results if outcome == "conflict"]

        assert outcomes.count("confirmed") == 1
        assert outcomes.count("conflict") == 1
        assert len(confirmed_rows) == 1
        assert len(winner_ids) == 1
        assert confirmed_rows[0].id.hex == next(iter(winner_ids)).replace("-", "")
        assert consuming == 1
        assert slot_row is not None and slot_row.status == AppointmentSlotStatus.FULL
        assert dock_row is not None and dock_row.status == DockStatus.OCCUPIED
        assert proposal_row is not None
        assert proposal_row.status == AppointmentStatus.CANCELLED
        notes = proposal_row.notes or ""
        assert notes.count("confirmed_appointment_id=") == 1
        assert "stale_reason=" not in notes
        assert str(confirmed_rows[0].id) in notes
        assert confirmed_rows[0].shipment_id == shipment_id
        assert any("stale" in detail.lower() for detail in loser_details)
        assert retry.status == ProposalStatus.CONFIRMED
        assert str(retry.appointment_id) == str(confirmed_rows[0].id)

    def test_same_proposal_two_concurrent_conversation_confirms(self, postgres_engine) -> None:
        from app.ai.conversation.provider import FakeLLMProvider
        from app.models.chat_message import ChatMessage
        from app.models.chat_thread import ChatThread
        from app.models.enums import ChatThreadStatus
        from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
        from app.services.conversation import ConversationService
        from tests.test_step8_conversation import _build_world

        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        world = _build_world(session, slot_capacity=1)
        service = ConversationService(session, provider=FakeLLMProvider())
        created = service.create_thread(
            ConversationCreateRequest(
                driver_id=world["driver"].id,
                shipment_id=world["shipment"].id,
            )
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Can you find another appointment?"),
        )
        proposed = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The first one works."),
        )
        thread_id = created.thread_id
        proposal_id = proposed.proposal_id
        slot_id = world["slot_a"].id
        session.close()
        assert proposal_id is not None

        def confirm_once() -> tuple[str, str]:
            worker = session_factory()
            try:
                worker.execute(text("SET lock_timeout = '10s'"))
                result = ConversationService(worker, provider=FakeLLMProvider()).handle_message(
                    thread_id,
                    ConversationMessageRequest(message="Confirm it."),
                )
                accept_calls = [call for call in result.tool_calls if call.name == "accept_proposal"]
                if any(call.success for call in accept_calls):
                    return ("confirmed", result.response)
                if any(
                    call.error and ("stale" in call.error.lower() or "conflict" in call.error.lower())
                    for call in accept_calls
                ):
                    return ("conflict", result.response)
                if result.status in {"stale", "conflict"}:
                    return ("conflict", result.response)
                return ("other", result.response)
            finally:
                worker.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(confirm_once) for _ in range(2)]
            results = [future.result() for future in as_completed(futures)]

        verify = session_factory()
        confirmed = _confirmed_count(verify, slot_id)
        proposal_row = verify.get(Appointment, proposal_id)
        thread = verify.get(ChatThread, thread_id)
        messages = list(
            verify.scalars(
                select(ChatMessage).where(ChatMessage.chat_thread_id == thread_id)
            ).all()
        )
        verify.close()

        outcomes = [outcome for outcome, _ in results]
        winner_text = next(text for outcome, text in results if outcome == "confirmed")
        loser_text = next(text for outcome, text in results if outcome == "conflict")
        assert outcomes.count("confirmed") == 1
        assert outcomes.count("conflict") == 1
        assert confirmed == 1
        assert "confirmed" in winner_text.lower()
        assert "confirmed" not in loser_text.lower() or "no longer available" in loser_text.lower()
        assert "appointment is confirmed" not in loser_text.lower()
        assert proposal_row is not None
        assert (proposal_row.notes or "").count("confirmed_appointment_id=") == 1
        assert "stale_reason=" not in (proposal_row.notes or "")
        assert thread is not None
        assert thread.status == ChatThreadStatus.OPEN
        assert thread.shipment_id is not None
        inbound = [item for item in messages if item.direction.value == "inbound"]
        outbound = [item for item in messages if item.direction.value == "outbound"]
        assert len(inbound) >= 4
        assert len(outbound) >= 4
        assert all(item.content for item in messages)


class TestConcurrentRescheduleConfirmation:
    def test_same_reschedule_proposal_two_concurrent_accepts(
        self, postgres_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        now = _utc(2026, 8, 13, 10, 0)
        facility = Facility(
            name="PG Reschedule Facility",
            code=f"PGR-{uuid.uuid4().hex[:4]}",
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
        session.add_all([facility, dock_a, dock_b, original_slot, new_slot])
        session.commit()
        shipment = _create_feasible_shipment(
            session,
            facility=facility,
            slot=original_slot,
            dock=dock_a,
            now=now,
            label="RS",
        )
        original = AllocationService(session).allocate(
            shipment.id,
            AllocationRequest(
                appointment_slot_id=original_slot.id,
                dock_id=dock_a.id,
                evaluated_at=now,
            ),
        )
        session.add(
            ETAUpdate(
                shipment_id=shipment.id,
                previous_eta=now + timedelta(hours=2, minutes=15),
                new_eta=now + timedelta(hours=4, minutes=15),
                update_timestamp=now + timedelta(minutes=5),
                source=ETASource.DRIVER,
                reason="traffic / driver delay",
            )
        )
        session.commit()
        proposal = ProposalService(session).create(
            shipment.id,
            ProposalCreateRequest(appointment_slot_id=new_slot.id, dock_id=dock_b.id),
        )
        proposal_id = proposal.proposal_id
        original_id = original.appointment.id
        new_slot_id = new_slot.id
        original_slot_id = original_slot.id
        shipment_id = shipment.id
        session.close()

        lock_gate = threading.Barrier(2, timeout=15)
        original_try = AppointmentRepository.try_acquire_shipment_advisory_lock
        seen = {"n": 0}
        seen_lock = threading.Lock()

        def gated_try(self: AppointmentRepository, shipment_id: uuid.UUID) -> bool:
            with seen_lock:
                seen["n"] += 1
                call_number = seen["n"]
            if call_number <= 2:
                lock_gate.wait()
            return original_try(self, shipment_id)

        monkeypatch.setattr(
            AppointmentRepository,
            "try_acquire_shipment_advisory_lock",
            gated_try,
        )

        def accept_once() -> str:
            worker_session = session_factory()
            try:
                ProposalService(worker_session).accept(proposal_id)
                return "confirmed"
            except ConflictError:
                worker_session.rollback()
                return "conflict"
            finally:
                worker_session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result() for future in as_completed([executor.submit(accept_once) for _ in range(2)])]

        verify = session_factory()
        confirmed_new = _confirmed_count(verify, new_slot_id)
        confirmed_old = _confirmed_count(verify, original_slot_id)
        active = list(
            verify.scalars(
                select(Appointment)
                .where(Appointment.shipment_id == shipment_id)
                .where(Appointment.status == AppointmentStatus.CONFIRMED)
            ).all()
        )
        original_row = verify.get(Appointment, original_id)
        retry = ProposalService(verify).accept(proposal_id)
        verify.close()

        assert results.count("confirmed") == 1
        assert results.count("conflict") == 1
        assert confirmed_new == 1
        assert confirmed_old == 0
        assert len(active) == 1
        assert original_row is not None
        assert original_row.status == AppointmentStatus.CANCELLED
        assert retry.status == ProposalStatus.CONFIRMED
        assert retry.appointment_id == active[0].id
