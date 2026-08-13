"""Step 6 adversarial hardening tests for allocation + concurrency."""

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
from app.core.exceptions import ConflictError, SetuHaulError
from app.models import (
    Appointment,
    AppointmentSlot,
    Dock,
    DriverException,
    Facility,
)
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    DockStatus,
    EntityStatus,
    ExceptionStatus,
    ExceptionType,
)
from app.repositories.appointment import AppointmentRepository
from app.repositories.appointment_slot import AppointmentSlotRepository
from app.repositories.dock import DockRepository
from app.schemas.allocation import AllocationRequest
from app.services.allocation import ALLOCATION_LOCK_ORDER, AllocationService
from app.services.feasibility import FeasibilityService
from tests.test_step6_allocation import (
    _add_shipment_to_facility,
    _build_allocation_scenario,
    _count_appointments,
)
from tests.test_step6_concurrency import (
    _allocate_worker,
    _count_slot_appointments,
    _create_feasible_shipment,
    _postgres_test_url,
    _setup_facility_slot,
)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def postgres_url() -> str:
    url = _postgres_test_url()
    if url is None:
        pytest.skip("PostgreSQL unavailable for Step 6 hardening tests")
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


class TestTransactionBoundaries:
    def test_commit_failure_rolls_back_appointment_and_statuses(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = _build_allocation_scenario(db_session, slot_capacity=1)

        def fail_commit(_session: Session) -> None:
            _session.rollback()
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr("app.services.allocation.safe_commit", fail_commit)

        with pytest.raises(RuntimeError, match="simulated commit failure"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    dock_id=data["dock"].id,
                    evaluated_at=data["now"],
                ),
            )

        assert _count_appointments(db_session, data["slot"].id) == 0
        db_session.refresh(data["slot"])
        db_session.refresh(data["dock"])
        assert data["slot"].status == AppointmentSlotStatus.OPEN
        assert data["dock"].status == DockStatus.AVAILABLE

    def test_failure_after_appointment_create_rolls_back(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = _build_allocation_scenario(db_session)
        original_create = AppointmentRepository.create

        def create_then_fail(self, **kwargs):  # type: ignore[no-untyped-def]
            original_create(self, **kwargs)
            raise RuntimeError("simulated failure after appointment create")

        monkeypatch.setattr(AppointmentRepository, "create", create_then_fail)

        with pytest.raises(RuntimeError, match="simulated failure after appointment"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )

        assert _count_appointments(db_session, data["slot"].id) == 0
        db_session.refresh(data["slot"])
        assert data["slot"].status == AppointmentSlotStatus.OPEN

    def test_session_usable_after_commit_failure(self, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
        data = _build_allocation_scenario(db_session)

        def fail_commit(_session: Session) -> None:
            _session.rollback()
            raise RuntimeError("commit failed")

        monkeypatch.setattr("app.services.allocation.safe_commit", fail_commit)

        with pytest.raises(RuntimeError):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )

        FeasibilityService(db_session).evaluate(data["shipment"].id)


class TestLockOrder:
    def test_documented_lock_order_constant(self) -> None:
        assert ALLOCATION_LOCK_ORDER == ("shipment", "slot", "dock")

    def test_runtime_lock_order_shipment_slot_dock(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = _build_allocation_scenario(db_session)
        order: list[str] = []

        original_advisory = AppointmentRepository.acquire_shipment_advisory_lock
        original_slot_lock = AppointmentSlotRepository.lock_by_id
        original_dock_lock = DockRepository.lock_by_id

        def track_advisory(self, shipment_id: uuid.UUID) -> None:
            order.append("shipment")
            original_advisory(self, shipment_id)

        def track_slot(self, slot_id: uuid.UUID):
            order.append("slot")
            return original_slot_lock(self, slot_id)

        def track_dock(self, dock_id: uuid.UUID):
            order.append("dock")
            return original_dock_lock(self, dock_id)

        monkeypatch.setattr(
            AppointmentRepository, "acquire_shipment_advisory_lock", track_advisory
        )
        monkeypatch.setattr(AppointmentSlotRepository, "lock_by_id", track_slot)
        monkeypatch.setattr(DockRepository, "lock_by_id", track_dock)

        AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
                evaluated_at=data["now"],
            ),
        )

        assert order == ["shipment", "slot", "dock"]


class TestStaleCandidateRevalidation:
    def test_slot_filled_before_lock_rejected_on_recheck(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, slot_capacity=1)
        filler = _add_shipment_to_facility(
            db_session, data["facility"], shipment_number="FILL-1", now=data["now"]
        )
        AllocationService(db_session).allocate(
            filler.id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )

        with pytest.raises(ConflictError, match="capacity exhausted|not available"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )


class TestStep5Integration:
    def test_allocation_invokes_feasibility_service(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = _build_allocation_scenario(db_session)
        calls: list[uuid.UUID] = []
        original_evaluate = FeasibilityService.evaluate

        def track_evaluate(self, shipment_id: uuid.UUID, request=None):  # type: ignore[no-untyped-def]
            calls.append(shipment_id)
            return original_evaluate(self, shipment_id, request)

        monkeypatch.setattr(FeasibilityService, "evaluate", track_evaluate)

        AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        assert calls == [data["shipment"].id]

    def test_blocking_exception_prevents_allocation(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        db_session.add(
            DriverException(
                shipment_id=data["shipment"].id,
                driver_id=data["shipment"].driver_id,
                exception_type=ExceptionType.TRAFFIC,
                description="Blocking",
                status=ExceptionStatus.OPEN,
                occurred_at=data["now"],
            )
        )
        db_session.commit()

        with pytest.raises(SetuHaulError, match="not feasible"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )
        assert _count_appointments(db_session, data["slot"].id) == 0


class TestExplicitResourceBehavior:
    def test_cross_facility_slot_rejected(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        other_facility = Facility(
            name="Other",
            code=f"OTH-{uuid.uuid4().hex[:4]}",
            timezone="UTC",
            status=EntityStatus.ACTIVE,
        )
        foreign_slot = AppointmentSlot(
            facility=other_facility,
            start_time=data["now"] + timedelta(hours=2),
            end_time=data["now"] + timedelta(hours=3),
            capacity=3,
            status=AppointmentSlotStatus.OPEN,
        )
        db_session.add_all([other_facility, foreign_slot])
        db_session.commit()

        with pytest.raises(SetuHaulError, match="not feasible|not belong"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=foreign_slot.id,
                    evaluated_at=data["now"],
                ),
            )

    def test_cross_facility_dock_rejected(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        other_facility = Facility(
            name="Other Dock Fac",
            code=f"ODF-{uuid.uuid4().hex[:4]}",
            timezone="UTC",
            status=EntityStatus.ACTIVE,
        )
        foreign_dock = Dock(
            facility=other_facility,
            name="Foreign Dock",
            dock_type="standard",
            status=DockStatus.AVAILABLE,
        )
        db_session.add_all([other_facility, foreign_dock])
        db_session.commit()

        with pytest.raises(SetuHaulError, match="not feasible|not belong"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    dock_id=foreign_dock.id,
                    evaluated_at=data["now"],
                ),
            )

    def test_explicit_unavailable_dock_does_not_fallback(
        self, db_session: Session
    ) -> None:
        data = _build_allocation_scenario(db_session, dock_status=DockStatus.OCCUPIED)
        dock_b = Dock(
            facility=data["facility"],
            name="Dock B",
            dock_type="standard",
            status=DockStatus.AVAILABLE,
        )
        db_session.add(dock_b)
        db_session.commit()

        with pytest.raises(ConflictError, match="not available"):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    dock_id=data["dock"].id,
                    evaluated_at=data["now"],
                ),
            )

        assert _count_appointments(db_session, data["slot"].id) == 0


class TestDeterministicDockSelection:
    def test_auto_selects_earliest_dock_by_name(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        dock_b = Dock(
            facility=data["facility"],
            name="Dock B",
            dock_type="standard",
            status=DockStatus.AVAILABLE,
        )
        data["dock"].name = "Dock A"
        db_session.add(dock_b)
        db_session.commit()

        result = AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        assert result.dock is not None
        assert result.dock.name == "Dock A"


class TestRetrySemantics:
    def test_retry_after_success_returns_409(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session)
        service = AllocationService(db_session)
        service.allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        with pytest.raises(ConflictError, match="already has an active allocation"):
            service.allocate(
                data["shipment"].id,
                AllocationRequest(
                    appointment_slot_id=data["slot"].id,
                    evaluated_at=data["now"],
                ),
            )

    def test_retry_after_failure_can_succeed(self, db_session: Session) -> None:
        data = _build_allocation_scenario(db_session, include_eta=False)
        with pytest.raises(SetuHaulError):
            AllocationService(db_session).allocate(
                data["shipment"].id,
                AllocationRequest(appointment_slot_id=data["slot"].id),
            )
        from app.models import ETAUpdate
        from app.models.enums import ETASource

        db_session.add(
            ETAUpdate(
                shipment_id=data["shipment"].id,
                previous_eta=None,
                new_eta=data["now"] + timedelta(hours=2, minutes=15),
                update_timestamp=data["now"],
                source=ETASource.DISPATCH,
            )
        )
        db_session.commit()

        result = AllocationService(db_session).allocate(
            data["shipment"].id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        assert result.success is True


class TestAPISafety:
    def test_allocate_errors_do_not_leak_internals(
        self, db_session: Session, client: TestClient
    ) -> None:
        data = _build_allocation_scenario(db_session, include_eta=False)
        response = client.post(
            f"/shipments/{data['shipment'].id}/allocate",
            json={"appointment_slot_id": str(data["slot"].id)},
        )
        lowered = response.text.lower()
        assert response.status_code in (400, 409)
        for forbidden in ("traceback", "sqlalchemy", "postgresql", "psycopg", "password"):
            assert forbidden not in lowered


class TestArchitectureBoundary:
    def test_allocation_module_has_no_ai_imports(self) -> None:
        allocation_path = Path(__file__).resolve().parents[1] / "app" / "services" / "allocation.py"
        source = allocation_path.read_text(encoding="utf-8").lower()
        forbidden = (
            "langchain",
            "openai",
            "anthropic",
            "langgraph",
            "vector",
            "embedding",
            "llm",
        )
        for term in forbidden:
            assert term not in source

    def test_allocation_service_has_no_direct_sql(self) -> None:
        source = inspect.getsource(AllocationService)
        assert "session.execute" not in source
        assert "text(" not in source


class TestPostgreSQLHardening:
    def test_capacity_three_five_concurrent(self, postgres_url: str, postgres_engine) -> None:
        setup_session = sessionmaker(bind=postgres_engine)()
        data = _setup_facility_slot(setup_session, capacity=3)
        shipments = [
            _create_feasible_shipment(
                setup_session,
                facility=data["facility"],
                slot=data["slot"],
                dock=None,
                now=data["now"],
                label=str(i),
            )
            for i in range(5)
        ]
        slot_id = data["slot"].id
        shipment_ids = [s.id for s in shipments]
        now = data["now"]
        setup_session.close()

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(
                    _allocate_worker, postgres_url, sid, slot_id, None, now
                )
                for sid in shipment_ids
            ]
            results = [f.result() for f in as_completed(futures)]

        assert results.count("success") == 3
        assert results.count("conflict") == 2
        assert _count_slot_appointments(postgres_url, slot_id) == 3

    def test_same_shipment_three_concurrent(self, postgres_url: str, postgres_engine) -> None:
        setup_session = sessionmaker(bind=postgres_engine)()
        data = _setup_facility_slot(setup_session, capacity=5)
        shipment = _create_feasible_shipment(
            setup_session,
            facility=data["facility"],
            slot=data["slot"],
            dock=None,
            now=data["now"],
            label="triple",
        )
        slot_id = data["slot"].id
        shipment_id = shipment.id
        now = data["now"]
        setup_session.close()

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(
                    _allocate_worker, postgres_url, shipment_id, slot_id, None, now
                )
                for _ in range(3)
            ]
            results = [f.result() for f in as_completed(futures)]

        assert results.count("success") == 1
        assert results.count("conflict") == 2
        assert _count_slot_appointments(postgres_url, slot_id) == 1

    def test_postgres_commit_failure_rolls_back(
        self, postgres_url: str, postgres_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        setup_session = sessionmaker(bind=postgres_engine)()
        data = _setup_facility_slot(setup_session, capacity=1, dock_count=1)
        shipment = _create_feasible_shipment(
            setup_session,
            facility=data["facility"],
            slot=data["slot"],
            dock=data["docks"][0],
            now=data["now"],
            label="pg-rollback",
        )
        slot_id = data["slot"].id
        dock_id = data["docks"][0].id
        shipment_id = shipment.id
        now = data["now"]
        setup_session.close()

        def fail_commit(_session: Session) -> None:
            _session.rollback()
            raise RuntimeError("postgres commit failure")

        monkeypatch.setattr("app.services.allocation.safe_commit", fail_commit)

        engine = create_engine(postgres_url, poolclass=NullPool)
        session = sessionmaker(bind=engine)()
        try:
            with pytest.raises(RuntimeError, match="postgres commit failure"):
                AllocationService(session).allocate(
                    shipment_id,
                    AllocationRequest(
                        appointment_slot_id=slot_id,
                        dock_id=dock_id,
                        evaluated_at=now,
                    ),
                )
        finally:
            session.close()
            engine.dispose()

        assert _count_slot_appointments(postgres_url, slot_id) == 0

        verify_engine = create_engine(postgres_url, poolclass=NullPool)
        verify_session = sessionmaker(bind=verify_engine)()
        try:
            slot = verify_session.get(AppointmentSlot, slot_id)
            dock = verify_session.get(Dock, dock_id)
            assert slot is not None and slot.status == AppointmentSlotStatus.OPEN
            assert dock is not None and dock.status == DockStatus.AVAILABLE
        finally:
            verify_session.close()
            verify_engine.dispose()
