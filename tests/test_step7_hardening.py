"""Step 7 adversarial hardening tests."""

import inspect
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base
from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError
from app.models import (
    Appointment,
    AppointmentSlot,
    Dock,
    DriverException,
    ETAUpdate,
    Facility,
)
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    DockStatus,
    EntityStatus,
    ETASource,
    ExceptionStatus,
    ExceptionType,
    ShipmentStatus,
)
from app.schemas.allocation import AllocationRequest
from app.schemas.proposal import ProposalCreateRequest, ProposalStatus
from app.services.allocation import AllocationService
from app.services.proposal import PROPOSAL_TTL_MINUTES, ProposalService
from tests.test_step7_proposals import (
    _add_shipment,
    _build_proposal_scenario,
    _confirmed_count,
    _utc,
)
from tests.test_step7_concurrency import (
    _build_scenario,
    _confirmed_count as _pg_confirmed_count,
    _create_feasible_shipment,
    _postgres_test_url,
)


@pytest.fixture
def postgres_url() -> str:
    url = _postgres_test_url()
    if url is None:
        pytest.skip("PostgreSQL unavailable for Step 7 hardening tests")
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


class TestStateMachineHardening:
    def test_all_invalid_terminal_transitions(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        proposal_id = created.proposal_id

        service.reject(proposal_id)
        with pytest.raises(SetuHaulError, match="rejected"):
            service.accept(proposal_id)
        assert _confirmed_count(db_session, data["slot"].id) == 0

        data2 = _build_proposal_scenario(db_session, shipment_number="PROP-TERM-2")
        created2 = service.create(
            data2["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data2["slot"].id),
        )
        appointment = db_session.get(Appointment, created2.proposal_id)
        appointment.created_at = datetime.now(timezone.utc) - timedelta(
            minutes=PROPOSAL_TTL_MINUTES + 1
        )
        db_session.commit()
        with pytest.raises(ConflictError, match="expired"):
            service.accept(created2.proposal_id)

        data3 = _build_proposal_scenario(db_session, shipment_number="PROP-TERM-3", slot_capacity=1)
        created3 = service.create(
            data3["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data3["slot"].id),
        )
        other = _add_shipment(
            db_session, data3["facility"], shipment_number="PROP-TERM-4", now=data3["now"]
        )
        AllocationService(db_session).allocate(
            other.id,
            AllocationRequest(
                appointment_slot_id=data3["slot"].id,
                evaluated_at=data3["now"],
            ),
        )
        with pytest.raises(ConflictError):
            service.accept(created3.proposal_id)
        with pytest.raises(SetuHaulError, match="stale"):
            service.accept(created3.proposal_id)

        data4 = _build_proposal_scenario(db_session, shipment_number="PROP-TERM-5")
        created4 = service.create(
            data4["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data4["slot"].id,
                dock_id=data4["dock"].id,
            ),
        )
        service.accept(created4.proposal_id)
        with pytest.raises(ConflictError, match="already confirmed"):
            service.reject(created4.proposal_id)
        second = service.accept(created4.proposal_id)
        assert second.status == ProposalStatus.CONFIRMED
        assert _confirmed_count(db_session, data4["slot"].id) == 1


class TestProposalCreationHardening:
    def test_creation_does_not_mutate_slot_or_dock(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        slot = data["slot"]
        dock = data["dock"]
        ProposalService(db_session).create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=slot.id,
                dock_id=dock.id,
            ),
        )
        db_session.refresh(slot)
        db_session.refresh(dock)
        assert slot.status == AppointmentSlotStatus.OPEN
        assert dock.status == DockStatus.AVAILABLE
        assert _confirmed_count(db_session, slot.id) == 0

    def test_repeated_proposal_creation_allowed(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        first = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        second = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        assert first.proposal_id != second.proposal_id
        assert first.status == ProposalStatus.PROPOSED
        assert second.status == ProposalStatus.PROPOSED

    def test_cross_facility_dock_rejected(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        other_facility = Facility(
            name="Other Dock Facility",
            code=f"ODF-{uuid.uuid4().hex[:4]}",
            timezone="UTC",
            status=EntityStatus.ACTIVE,
        )
        other_dock = Dock(
            facility=other_facility,
            name="Other Dock",
            dock_type="standard",
            status=DockStatus.AVAILABLE,
        )
        db_session.add_all([other_facility, other_dock])
        db_session.commit()
        with pytest.raises(SetuHaulError, match="destination facility"):
            ProposalService(db_session).create(
                data["shipment"].id,
                ProposalCreateRequest(
                    appointment_slot_id=data["slot"].id,
                    dock_id=other_dock.id,
                ),
            )

    def test_missing_destination_facility_rejected(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        data["shipment"].destination_facility_id = None
        db_session.commit()
        with pytest.raises(SetuHaulError, match="destination facility"):
            ProposalService(db_session).create(
                data["shipment"].id,
                ProposalCreateRequest(appointment_slot_id=data["slot"].id),
            )


class TestExpirationBoundaries:
    def test_just_before_expiry_still_proposed(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        appointment = db_session.get(Appointment, created.proposal_id)
        appointment.created_at = datetime.now(timezone.utc) - timedelta(
            minutes=PROPOSAL_TTL_MINUTES - 1,
        )
        db_session.commit()
        fetched = service.get(created.proposal_id)
        assert fetched.status == ProposalStatus.PROPOSED

    def test_just_after_expiry_is_expired(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        appointment = db_session.get(Appointment, created.proposal_id)
        appointment.created_at = datetime.now(timezone.utc) - timedelta(
            minutes=PROPOSAL_TTL_MINUTES,
            seconds=1,
        )
        db_session.commit()
        with pytest.raises(ConflictError, match="expired"):
            service.accept(created.proposal_id)

    def test_reject_expired_proposal_fails(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        appointment = db_session.get(Appointment, created.proposal_id)
        appointment.created_at = datetime.now(timezone.utc) - timedelta(
            minutes=PROPOSAL_TTL_MINUTES + 1
        )
        db_session.commit()
        with pytest.raises(SetuHaulError, match="expired"):
            service.reject(created.proposal_id)

    def test_repeated_accept_after_expiry(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        appointment = db_session.get(Appointment, created.proposal_id)
        appointment.created_at = datetime.now(timezone.utc) - timedelta(
            minutes=PROPOSAL_TTL_MINUTES + 1
        )
        db_session.commit()
        for _ in range(2):
            with pytest.raises(ConflictError, match="expired"):
                service.accept(created.proposal_id)
        assert _confirmed_count(db_session, data["slot"].id) == 0


class TestStaleScenarios:
    def test_dock_unavailable_after_proposal(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        data["dock"].status = DockStatus.OCCUPIED
        db_session.commit()
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)

    def test_blocking_exception_after_proposal(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        db_session.add(
            DriverException(
                shipment_id=data["shipment"].id,
                driver_id=data["shipment"].driver_id,
                exception_type=ExceptionType.TRAFFIC,
                description="Blocking delay",
                status=ExceptionStatus.OPEN,
                occurred_at=data["now"],
            )
        )
        db_session.commit()
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)

    def test_eta_change_invalidates_feasibility(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        db_session.add(
            ETAUpdate(
                shipment_id=data["shipment"].id,
                previous_eta=data["now"] + timedelta(hours=2, minutes=15),
                new_eta=data["now"] + timedelta(hours=10),
                update_timestamp=data["now"] + timedelta(minutes=5),
                source=ETASource.DRIVER,
                reason="Major delay",
            )
        )
        db_session.commit()
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)

    def test_stale_does_not_confirm_or_mutate_capacity(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session, slot_capacity=1)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        other = _add_shipment(
            db_session, data["facility"], shipment_number="PROP-STALE-1", now=data["now"]
        )
        AllocationService(db_session).allocate(
            other.id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        before = _confirmed_count(db_session, data["slot"].id)
        with pytest.raises(ConflictError):
            service.accept(created.proposal_id)
        assert _confirmed_count(db_session, data["slot"].id) == before
        proposal = service.get(created.proposal_id)
        assert proposal.status == ProposalStatus.STALE
        assert proposal.appointment_id is None


class TestTwoCommitBoundary:
    def test_recovery_when_proposal_update_fails_after_step6(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        fail_proposal_commit = {"armed": True}

        def flaky_proposal_commit(session: Session) -> None:
            if fail_proposal_commit["armed"]:
                fail_proposal_commit["armed"] = False
                session.rollback()
                raise RuntimeError("simulated proposal update failure")
            session.commit()

        monkeypatch.setattr("app.services.proposal.safe_commit", flaky_proposal_commit)

        with pytest.raises(RuntimeError, match="simulated proposal update failure"):
            service.accept(created.proposal_id)

        assert _confirmed_count(db_session, data["slot"].id) == 1
        proposal_row = db_session.get(Appointment, created.proposal_id)
        assert proposal_row.status == AppointmentStatus.REQUESTED

        result = ProposalService(db_session).accept(created.proposal_id)
        assert result.status == ProposalStatus.CONFIRMED
        assert result.appointment_id is not None
        assert _confirmed_count(db_session, data["slot"].id) == 1

    def test_recovery_without_explicit_dock_after_step6_commit(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        fail_proposal_commit = {"armed": True}

        def flaky_proposal_commit(session: Session) -> None:
            if fail_proposal_commit["armed"]:
                fail_proposal_commit["armed"] = False
                session.rollback()
                raise RuntimeError("simulated proposal update failure")
            session.commit()

        monkeypatch.setattr("app.services.proposal.safe_commit", flaky_proposal_commit)

        with pytest.raises(RuntimeError):
            service.accept(created.proposal_id)

        result = ProposalService(db_session).accept(created.proposal_id)
        assert result.status == ProposalStatus.CONFIRMED
        assert _confirmed_count(db_session, data["slot"].id) == 1

    def test_step6_failure_leaves_no_confirmed_appointment(
        self, db_session: Session,
    ) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )

        def fail_allocate(*_args, **_kwargs):
            raise ConflictError("simulated allocation failure")

        with patch.object(service._allocation_service, "allocate", side_effect=fail_allocate):
            with pytest.raises(ConflictError):
                service.accept(created.proposal_id)

        assert _confirmed_count(db_session, data["slot"].id) == 0
        proposal = service.get(created.proposal_id)
        assert proposal.status == ProposalStatus.STALE


class TestStep5Integration:
    def test_feasibility_called_on_accept(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        with patch.object(
            service._feasibility_service,
            "evaluate",
            wraps=service._feasibility_service.evaluate,
        ) as mock_evaluate:
            service.accept(created.proposal_id)
            mock_evaluate.assert_called_once()

    def test_no_cached_feasibility_on_accept(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        data["shipment"].status = ShipmentStatus.CANCELLED
        db_session.commit()
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)


class TestStep6Integration:
    def test_proposal_service_does_not_duplicate_locking(self) -> None:
        source = Path(inspect.getfile(ProposalService))
        content = source.read_text(encoding="utf-8")
        assert "lock_by_id" not in content
        assert "pg_advisory" not in content
        assert "FOR UPDATE" not in content.upper()


class TestRetrySemantics:
    def test_accept_twice_idempotent(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        first = service.accept(created.proposal_id)
        for _ in range(3):
            again = service.accept(created.proposal_id)
            assert again.status == ProposalStatus.CONFIRMED
            assert again.appointment_id == first.appointment_id
        assert _confirmed_count(db_session, data["slot"].id) == 1

    def test_reject_twice_idempotent(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        service.reject(created.proposal_id)
        again = service.reject(created.proposal_id)
        assert again.status == ProposalStatus.REJECTED


class TestSessionRecovery:
    def test_session_usable_after_create_failure(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = _build_proposal_scenario(db_session)

        fail_count = {"n": 0}

        def fail_commit(session: Session) -> None:
            if fail_count["n"] == 0:
                fail_count["n"] += 1
                session.rollback()
                raise RuntimeError("create commit failure")
            session.commit()

        monkeypatch.setattr("app.services.proposal.safe_commit", fail_commit)
        with pytest.raises(RuntimeError):
            ProposalService(db_session).create(
                data["shipment"].id,
                ProposalCreateRequest(appointment_slot_id=data["slot"].id),
            )
        result = ProposalService(db_session).create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        assert result.status == ProposalStatus.PROPOSED


class TestAPISafety:
    def test_proposal_errors_do_not_leak_internals(self, db_session: Session) -> None:
        from app.core.database import get_db
        from app.main import app as fastapi_app

        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_db] = override_get_db
        with TestClient(fastapi_app) as client:
            for response in (
                client.get(f"/proposals/{uuid.uuid4()}"),
                client.post(f"/proposals/{uuid.uuid4()}/accept"),
                client.post(
                    f"/shipments/{uuid.uuid4()}/proposals",
                    json={"appointment_slot_id": str(uuid.uuid4())},
                ),
            ):
                detail = response.json().get("detail", "").lower()
                for forbidden in ("traceback", "sqlalchemy", "postgresql", "password", "secret"):
                    assert forbidden not in detail
        fastapi_app.dependency_overrides.clear()

    def test_get_is_read_only(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        before = db_session.get(Appointment, created.proposal_id).status
        service.get(created.proposal_id)
        after = db_session.get(Appointment, created.proposal_id).status
        assert before == after == AppointmentStatus.REQUESTED


class TestArchitectureBoundary:
    def test_no_ai_imports_in_step7_modules(self) -> None:
        forbidden = ("openai", "anthropic", "langchain", "langgraph", "llamaindex")
        for path in (
            Path("app/services/proposal.py"),
            Path("app/api/proposals.py"),
            Path("app/schemas/proposal.py"),
        ):
            content = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                assert term not in content


class TestPostgreSQLConcurrencyHardening:
    def test_same_proposal_five_concurrent_accepts(self, postgres_engine) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        data = _build_scenario(session, slot_capacity=1)
        shipment = _create_feasible_shipment(
            session,
            facility=data["facility"],
            slot=data["slot"],
            dock=data["dock"],
            now=data["now"],
            label="FIVE",
        )
        proposal_id = ProposalService(session).create(
            shipment.id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        ).proposal_id
        slot_id = data["slot"].id
        session.close()

        def accept_once() -> str:
            worker = session_factory()
            try:
                ProposalService(worker).accept(proposal_id)
                return "confirmed"
            except ConflictError:
                worker.rollback()
                return "conflict"
            finally:
                worker.close()

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(accept_once) for _ in range(5)]
            results = [future.result() for future in as_completed(futures)]

        verify = session_factory()
        confirmed = _pg_confirmed_count(verify, slot_id)
        verify.close()
        assert confirmed == 1
        assert results.count("confirmed") >= 1

    def test_capacity_three_five_concurrent(self, postgres_engine) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        data = _build_scenario(session, slot_capacity=3)
        shipments = [
            _create_feasible_shipment(
                session,
                facility=data["facility"],
                slot=data["slot"],
                dock=data["dock"],
                now=data["now"],
                label=f"C3-{i}",
            )
            for i in range(5)
        ]
        proposal_ids = [
            ProposalService(session)
            .create(
                shipment.id,
                ProposalCreateRequest(
                    appointment_slot_id=data["slot"].id,
                    dock_id=data["dock"].id,
                ),
            )
            .proposal_id
            for shipment in shipments
        ]
        slot_id = data["slot"].id
        session.close()

        def accept_once(proposal_id: uuid.UUID) -> str:
            worker = session_factory()
            try:
                ProposalService(worker).accept(proposal_id)
                return "confirmed"
            except ConflictError:
                worker.rollback()
                return "conflict"
            finally:
                worker.close()

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(accept_once, proposal_ids))

        verify = session_factory()
        confirmed = _pg_confirmed_count(verify, slot_id)
        verify.close()
        assert confirmed == 3
        assert results.count("confirmed") == 3
        assert results.count("conflict") == 2

    def test_same_proposal_three_concurrent_accepts(self, postgres_engine) -> None:
        session_factory = sessionmaker(bind=postgres_engine)
        session = session_factory()
        data = _build_scenario(session, slot_capacity=1)
        shipment = _create_feasible_shipment(
            session,
            facility=data["facility"],
            slot=data["slot"],
            dock=data["dock"],
            now=data["now"],
            label="THREE",
        )
        proposal_id = ProposalService(session).create(
            shipment.id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        ).proposal_id
        slot_id = data["slot"].id
        session.close()

        def accept_once() -> tuple[str, str | None]:
            worker = session_factory()
            try:
                result = ProposalService(worker).accept(proposal_id)
                return ("confirmed", str(result.appointment_id))
            except ConflictError:
                worker.rollback()
                return ("conflict", None)
            finally:
                worker.close()

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = [future.result() for future in as_completed(executor.submit(accept_once) for _ in range(3))]

        verify = session_factory()
        assert _pg_confirmed_count(verify, slot_id) == 1
        verify.close()
        appointment_ids = {aid for status, aid in results if status == "confirmed" and aid}
        assert len(appointment_ids) <= 1
