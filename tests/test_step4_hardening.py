"""Step 4 hardening regression tests for ETA and driver exception services."""

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base
from app.core.exceptions import SetuHaulError
from app.models import Carrier, DriverException, ETAUpdate, Shipment
from app.models.enums import ETASource, ExceptionStatus, ExceptionType
from app.repositories.shipment import ShipmentRepository
from app.schemas.driver_exception import DriverExceptionCreate, DriverExceptionStatusUpdate
from app.schemas.eta_update import ETAUpdateCreate
from app.services.operations import DriverExceptionService, ETAUpdateService


def _utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _make_shipment(
    db_session: Session,
    shipment_number: str = "HARD-1",
    *,
    with_facility: bool = False,
) -> Shipment:
    carrier = Carrier(name="Hardening Carrier", code=f"H-{shipment_number}")
    shipment = Shipment(
        carrier=carrier,
        shipment_number=shipment_number,
        origin_location="A",
        destination_location="B",
    )
    db_session.add_all([carrier, shipment])
    db_session.commit()
    db_session.refresh(shipment)
    return shipment


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
        pytest.skip("PostgreSQL unavailable for Step 4 hardening tests")
    return url


@pytest.fixture
def postgres_session(postgres_url: str) -> Session:
    engine = create_engine(postgres_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


class TestETAHistoryHardening:
    def test_previous_eta_chain_across_three_updates(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "HARD-CHAIN")
        service = ETAUpdateService(db_session)
        first = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 10, 0),
                update_timestamp=_utc(2026, 8, 13, 8, 0),
                source=ETASource.DISPATCH,
            ),
        )
        second = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 12, 0),
                update_timestamp=_utc(2026, 8, 13, 9, 0),
                source=ETASource.DRIVER,
            ),
        )
        third = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 14, 0),
                update_timestamp=_utc(2026, 8, 13, 10, 0),
                source=ETASource.CARRIER,
            ),
        )
        assert first.previous_eta is None
        assert second.previous_eta == first.new_eta
        assert third.previous_eta == second.new_eta

    def test_historical_eta_records_remain_immutable(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "HARD-IMMUT")
        service = ETAUpdateService(db_session)
        original = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 10, 0),
                update_timestamp=_utc(2026, 8, 13, 8, 0),
                source=ETASource.DISPATCH,
            ),
        )
        service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 16, 0),
                update_timestamp=_utc(2026, 8, 13, 11, 0),
                source=ETASource.DRIVER,
                reason="Later update",
            ),
        )
        persisted = db_session.get(ETAUpdate, original.id)
        assert persisted is not None
        assert persisted.new_eta == original.new_eta
        assert persisted.source == ETASource.DISPATCH
        assert persisted.reason is None

    def test_same_timestamp_latest_is_deterministic(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "HARD-TIEBRK")
        service = ETAUpdateService(db_session)
        same_ts = _utc(2026, 8, 13, 10, 0)
        first = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 12, 0),
                update_timestamp=same_ts,
                source=ETASource.DISPATCH,
            ),
        )
        second = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 13, 0),
                update_timestamp=same_ts,
                source=ETASource.DRIVER,
            ),
        )
        repo = ShipmentRepository(db_session)
        first_latest = repo.get_latest_eta(shipment.id)
        second_latest = repo.get_latest_eta(shipment.id)
        assert first_latest is not None
        assert second_latest is not None
        assert first_latest.id == second_latest.id
        assert first_latest.id in {first.id, second.id}

    def test_latest_eta_matches_shipment_detail(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "HARD-DETAIL")
        service = ETAUpdateService(db_session)
        service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 15, 0),
                update_timestamp=_utc(2026, 8, 13, 9, 0),
                source=ETASource.DISPATCH,
            ),
        )
        latest = service.get_latest(shipment.id)
        repo_latest = ShipmentRepository(db_session).get_latest_eta(shipment.id)
        assert latest.latest_eta == repo_latest.new_eta
        assert latest.eta_update is not None
        assert latest.eta_update.id == repo_latest.id


class TestExceptionLifecycleHardening:
    def test_open_to_resolved_direct(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "HARD-O2R")
        service = DriverExceptionService(db_session)
        created = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.DELAY,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        resolved = service.update_status(
            created.id,
            DriverExceptionStatusUpdate(status=ExceptionStatus.RESOLVED),
        )
        assert resolved.status == ExceptionStatus.RESOLVED
        assert resolved.resolved_at is not None

    def test_repeated_acknowledge_rejected(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "HARD-REACK")
        service = DriverExceptionService(db_session)
        created = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.TRAFFIC,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        service.update_status(
            created.id,
            DriverExceptionStatusUpdate(status=ExceptionStatus.ACKNOWLEDGED),
        )
        with pytest.raises(SetuHaulError, match="Cannot transition"):
            service.update_status(
                created.id,
                DriverExceptionStatusUpdate(status=ExceptionStatus.ACKNOWLEDGED),
            )

    def test_repeated_resolve_rejected(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "HARD-RERES")
        service = DriverExceptionService(db_session)
        created = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.REPAIR,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        service.update_status(
            created.id,
            DriverExceptionStatusUpdate(status=ExceptionStatus.RESOLVED),
        )
        with pytest.raises(SetuHaulError, match="Cannot transition"):
            service.update_status(
                created.id,
                DriverExceptionStatusUpdate(status=ExceptionStatus.RESOLVED),
            )

    def test_mixed_exception_statuses_preserved(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "HARD-MIXED")
        service = DriverExceptionService(db_session)
        exc1 = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.TRAFFIC,
                occurred_at=_utc(2026, 8, 13, 7, 0),
            ),
        )
        exc2 = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.DELAY,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        exc3 = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.OTHER,
                occurred_at=_utc(2026, 8, 13, 9, 0),
            ),
        )
        service.update_status(
            exc1.id,
            DriverExceptionStatusUpdate(status=ExceptionStatus.RESOLVED),
        )
        service.update_status(
            exc3.id,
            DriverExceptionStatusUpdate(status=ExceptionStatus.ACKNOWLEDGED),
        )

        history = service.list(shipment_id=shipment.id, page=1, page_size=50)
        by_id = {item.id: item for item in history.items}
        assert by_id[exc1.id].status == ExceptionStatus.RESOLVED
        assert by_id[exc2.id].status == ExceptionStatus.OPEN
        assert by_id[exc3.id].status == ExceptionStatus.ACKNOWLEDGED
        assert history.total == 3


class TestExceptionContextHardening:
    def test_detail_without_facility_driver_or_threads(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "HARD-SPARSE")
        service = DriverExceptionService(db_session)
        created = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.OTHER,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        detail = service.get_detail(created.id)
        assert detail.destination_facility_id is None
        assert detail.driver_name is None
        assert detail.chat_thread_ids == []


class TestStep4APIHardening:
    def test_invalid_source_rejected(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/eta-updates",
            json={
                "new_eta": "2026-08-14T18:00:00+00:00",
                "update_timestamp": "2026-08-13T12:00:00+00:00",
                "source": "not_a_valid_source",
            },
        )
        assert response.status_code == 422

    def test_invalid_exception_transition_returns_400(
        self, seeded_client: TestClient, db_session: Session
    ) -> None:
        shipment = _make_shipment(db_session, "HARD-API400")
        service = DriverExceptionService(db_session)
        created = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.DELAY,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        service.update_status(
            created.id,
            DriverExceptionStatusUpdate(status=ExceptionStatus.RESOLVED),
        )

        def override_get_db():
            try:
                yield db_session
            finally:
                pass

        from app.core.database import get_db
        from app.main import app as fastapi_app

        fastapi_app.dependency_overrides[get_db] = override_get_db
        with TestClient(fastapi_app) as client:
            response = client.patch(
                f"/driver-exceptions/{created.id}",
                json={"status": "open"},
            )
        fastapi_app.dependency_overrides.clear()
        assert response.status_code == 400
        assert "cannot transition" in response.json()["detail"].lower()

    def test_eta_update_not_found(self, seeded_client: TestClient) -> None:
        response = seeded_client.get(f"/eta-updates/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_exception_not_found(self, seeded_client: TestClient) -> None:
        response = seeded_client.get(f"/driver-exceptions/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_error_responses_do_not_leak_internals(
        self, seeded_client: TestClient
    ) -> None:
        response = seeded_client.get(f"/shipments/{uuid.uuid4()}/latest-eta")
        assert response.status_code == 404
        body = response.json()
        assert "detail" in body
        assert "sqlalchemy" not in body["detail"].lower()
        assert "traceback" not in body["detail"].lower()


class TestTransactionHardening:
    def test_session_usable_after_rollback_on_not_found(self, db_session: Session) -> None:
        service = ETAUpdateService(db_session)
        payload = ETAUpdateCreate(
            new_eta=_utc(2026, 8, 14, 12, 0),
            update_timestamp=_utc(2026, 8, 13, 8, 0),
            source=ETASource.DISPATCH,
        )
        with pytest.raises(Exception):
            service.create(uuid.uuid4(), payload)

        shipment = _make_shipment(db_session, "HARD-TXN")
        result = service.create(shipment.id, payload)
        assert result.shipment_id == shipment.id


class TestPostgreSQLStep4:
    def test_eta_timezone_preserved_on_postgresql(self, postgres_session: Session) -> None:
        carrier = Carrier(name="PG Carrier", code="PG-ETA")
        shipment = Shipment(
            carrier=carrier,
            shipment_number="PG-ETA-1",
            origin_location="A",
            destination_location="B",
        )
        postgres_session.add_all([carrier, shipment])
        postgres_session.commit()
        postgres_session.refresh(shipment)

        service = ETAUpdateService(postgres_session)
        created = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 15, 30),
                update_timestamp=_utc(2026, 8, 13, 10, 15),
                source=ETASource.DISPATCH,
            ),
        )
        persisted = postgres_session.get(ETAUpdate, created.id)
        assert persisted is not None
        assert persisted.new_eta.tzinfo is not None
        assert persisted.update_timestamp.tzinfo is not None

    def test_exception_resolution_timestamp_on_postgresql(
        self, postgres_session: Session
    ) -> None:
        carrier = Carrier(name="PG Exc Carrier", code="PG-EXC")
        shipment = Shipment(
            carrier=carrier,
            shipment_number="PG-EXC-1",
            origin_location="A",
            destination_location="B",
        )
        postgres_session.add_all([carrier, shipment])
        postgres_session.commit()
        postgres_session.refresh(shipment)

        service = DriverExceptionService(postgres_session)
        created = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.BREAKDOWN,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        resolved_at = _utc(2026, 8, 13, 14, 0)
        service.update_status(
            created.id,
            DriverExceptionStatusUpdate(
                status=ExceptionStatus.RESOLVED,
                resolved_at=resolved_at,
            ),
        )
        persisted = postgres_session.get(DriverException, created.id)
        assert persisted is not None
        assert persisted.status == ExceptionStatus.RESOLVED
        assert persisted.resolved_at is not None
        assert persisted.resolved_at.tzinfo is not None
