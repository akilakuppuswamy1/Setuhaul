"""Step 4 operational service tests for ETA and driver exceptions."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, SetuHaulError
from app.models import Carrier, DriverException, ETAUpdate, Shipment
from app.models.enums import ETASource, ExceptionStatus, ExceptionType
from app.repositories.eta_update import ETAUpdateRepository
from app.repositories.shipment import ShipmentRepository
from app.schemas.driver_exception import DriverExceptionCreate, DriverExceptionStatusUpdate
from app.schemas.eta_update import ETAUpdateCreate
from app.services.operations import DriverExceptionService, ETAUpdateService


def _utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _assert_datetime_equal(actual: datetime, expected: datetime) -> None:
    """Compare datetimes across SQLite (naive) and PostgreSQL (aware) storage."""
    if actual.tzinfo is None and expected.tzinfo is not None:
        assert actual == expected.replace(tzinfo=None)
    else:
        assert actual == expected


def _make_shipment(db_session: Session, shipment_number: str = "STEP4-1") -> Shipment:
    carrier = Carrier(name="Step4 Carrier", code=f"S4-{shipment_number}")
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


class TestETAService:
    def test_create_eta_update(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session)
        service = ETAUpdateService(db_session)
        payload = ETAUpdateCreate(
            new_eta=_utc(2026, 8, 14, 15, 0),
            update_timestamp=_utc(2026, 8, 13, 10, 0),
            source=ETASource.DISPATCH,
        )
        result = service.create(shipment.id, payload)
        assert result.shipment_id == shipment.id
        assert result.previous_eta is None
        _assert_datetime_equal(result.new_eta, payload.new_eta)

    def test_retrieve_eta_history(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-HIST")
        service = ETAUpdateService(db_session)
        first = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 12, 0),
                update_timestamp=_utc(2026, 8, 13, 8, 0),
                source=ETASource.DISPATCH,
            ),
        )
        second = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 14, 0),
                update_timestamp=_utc(2026, 8, 13, 9, 0),
                source=ETASource.DRIVER,
            ),
        )
        history = service.list(shipment_id=shipment.id, page=1, page_size=50)
        assert history.total == 2
        assert {item.id for item in history.items} == {first.id, second.id}

    def test_latest_eta_derived_correctly(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-LATEST")
        service = ETAUpdateService(db_session)
        service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 12, 0),
                update_timestamp=_utc(2026, 8, 13, 8, 0),
                source=ETASource.DISPATCH,
            ),
        )
        latest_record = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 16, 30),
                update_timestamp=_utc(2026, 8, 13, 11, 0),
                source=ETASource.DRIVER,
                reason="Updated en route",
            ),
        )
        latest = service.get_latest(shipment.id)
        assert latest.latest_eta == latest_record.new_eta
        assert latest.eta_update is not None
        assert latest.eta_update.id == latest_record.id

    def test_multiple_eta_updates_preserve_history(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-MULTI")
        service = ETAUpdateService(db_session)
        for hour in (12, 13, 14):
            service.create(
                shipment.id,
                ETAUpdateCreate(
                    new_eta=_utc(2026, 8, 14, hour, 0),
                    update_timestamp=_utc(2026, 8, 13, hour - 6, 0),
                    source=ETASource.DISPATCH,
                ),
            )
        repo = ETAUpdateRepository(db_session)
        items, total = repo.list_by_shipment(shipment.id)
        assert total == 3
        assert len(items) == 3

    def test_eta_correction_creates_new_record(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-CORR")
        service = ETAUpdateService(db_session)
        original = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 12, 0),
                update_timestamp=_utc(2026, 8, 13, 8, 0),
                source=ETASource.DRIVER,
            ),
        )
        correction = service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 15, 0),
                update_timestamp=_utc(2026, 8, 13, 9, 0),
                source=ETASource.DISPATCH,
                reason="Correction",
            ),
        )
        assert correction.previous_eta == original.new_eta
        assert correction.id != original.id
        persisted_original = db_session.get(ETAUpdate, original.id)
        assert persisted_original is not None
        assert persisted_original.new_eta == original.new_eta

    def test_shipment_without_eta_has_no_latest(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-NOETA")
        latest = ETAUpdateService(db_session).get_latest(shipment.id)
        assert latest.latest_eta is None
        assert latest.eta_update is None

    def test_invalid_shipment_rejected(self, db_session: Session) -> None:
        service = ETAUpdateService(db_session)
        payload = ETAUpdateCreate(
            new_eta=_utc(2026, 8, 14, 12, 0),
            update_timestamp=_utc(2026, 8, 13, 8, 0),
            source=ETASource.DISPATCH,
        )
        with pytest.raises(NotFoundError, match="Shipment"):
            service.create(uuid.uuid4(), payload)

    def test_deterministic_ordering(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-ORDER")
        service = ETAUpdateService(db_session)
        same_ts = _utc(2026, 8, 13, 10, 0)
        service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 12, 0),
                update_timestamp=same_ts,
                source=ETASource.DISPATCH,
            ),
        )
        service.create(
            shipment.id,
            ETAUpdateCreate(
                new_eta=_utc(2026, 8, 14, 13, 0),
                update_timestamp=same_ts,
                source=ETASource.DRIVER,
            ),
        )
        latest = ShipmentRepository(db_session).get_latest_eta(shipment.id)
        assert latest is not None
        history = service.list(shipment_id=shipment.id, page=1, page_size=50)
        timestamps = [item.update_timestamp for item in history.items]
        assert timestamps == sorted(timestamps)


class TestDriverExceptionService:
    def test_create_driver_exception(
        self, db_session: Session, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][0]
        driver = seeded_session["drivers"][0]
        service = DriverExceptionService(db_session)
        result = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.BREAKDOWN,
                occurred_at=_utc(2026, 8, 13, 11, 0),
                driver_id=driver.id,
                description="Flat tire",
            ),
        )
        assert result.shipment_id == shipment.id
        assert result.driver_id == driver.id
        assert result.status == ExceptionStatus.OPEN

    def test_retrieve_exception_history(
        self, db_session: Session, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][0]
        service = DriverExceptionService(db_session)
        service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.DELAY,
                occurred_at=_utc(2026, 8, 13, 9, 0),
            ),
        )
        service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.TRAFFIC,
                occurred_at=_utc(2026, 8, 13, 10, 0),
            ),
        )
        history = service.list(shipment_id=shipment.id, page=1, page_size=50)
        assert history.total >= 3

    def test_multiple_exceptions_preserve_history(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-EXC-MULTI")
        service = DriverExceptionService(db_session)
        first = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.OTHER,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        second = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.REPAIR,
                occurred_at=_utc(2026, 8, 13, 9, 0),
            ),
        )
        assert db_session.get(DriverException, first.id) is not None
        assert db_session.get(DriverException, second.id) is not None

    def test_exception_without_driver(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-EXC-NODRV")
        result = DriverExceptionService(db_session).create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.DELAY,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        assert result.driver_id is None

    def test_invalid_shipment_rejected(self, db_session: Session) -> None:
        with pytest.raises(NotFoundError, match="Shipment"):
            DriverExceptionService(db_session).create(
                uuid.uuid4(),
                DriverExceptionCreate(
                    exception_type=ExceptionType.DELAY,
                    occurred_at=_utc(2026, 8, 13, 8, 0),
                ),
            )

    def test_invalid_driver_rejected(
        self, db_session: Session, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][0]
        with pytest.raises(NotFoundError, match="Driver"):
            DriverExceptionService(db_session).create(
                shipment.id,
                DriverExceptionCreate(
                    exception_type=ExceptionType.DELAY,
                    occurred_at=_utc(2026, 8, 13, 8, 0),
                    driver_id=uuid.uuid4(),
                ),
            )

    def test_exception_lifecycle(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-LIFE")
        service = DriverExceptionService(db_session)
        created = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.TRAFFIC,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        acknowledged = service.update_status(
            created.id,
            DriverExceptionStatusUpdate(status=ExceptionStatus.ACKNOWLEDGED),
        )
        assert acknowledged.status == ExceptionStatus.ACKNOWLEDGED
        assert acknowledged.resolved_at is None

    def test_exception_resolution(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-RES")
        service = DriverExceptionService(db_session)
        created = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.BREAKDOWN,
                occurred_at=_utc(2026, 8, 13, 8, 0),
            ),
        )
        resolved_at = _utc(2026, 8, 13, 12, 0)
        resolved = service.update_status(
            created.id,
            DriverExceptionStatusUpdate(
                status=ExceptionStatus.RESOLVED,
                resolved_at=resolved_at,
            ),
        )
        assert resolved.status == ExceptionStatus.RESOLVED
        _assert_datetime_equal(resolved.resolved_at, resolved_at)

    def test_resolved_exception_cannot_transition(self, db_session: Session) -> None:
        shipment = _make_shipment(db_session, "STEP4-LOCK")
        service = DriverExceptionService(db_session)
        created = service.create(
            shipment.id,
            DriverExceptionCreate(
                exception_type=ExceptionType.OTHER,
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
                DriverExceptionStatusUpdate(status=ExceptionStatus.ACKNOWLEDGED),
            )

    def test_exception_context(
        self, db_session: Session, seeded_session: dict
    ) -> None:
        exception = seeded_session["exception"]
        detail = DriverExceptionService(db_session).get_detail(exception.id)
        assert detail.destination_facility_id is not None
        assert detail.driver_name is not None
        assert len(detail.chat_thread_ids) >= 1


class TestStep4API:
    def test_create_eta_update_api(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][1]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/eta-updates",
            json={
                "new_eta": "2026-08-14T18:00:00+00:00",
                "update_timestamp": "2026-08-13T12:00:00+00:00",
                "source": "dispatch",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["shipment_id"] == str(shipment.id)
        assert data["previous_eta"] is None

    def test_get_latest_eta_api(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.get(f"/shipments/{shipment.id}/latest-eta")
        assert response.status_code == 200
        data = response.json()
        assert data["latest_eta"] is not None
        assert data["eta_update"] is not None

    def test_latest_eta_empty_shipment(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][1]
        response = seeded_client.get(f"/shipments/{shipment.id}/latest-eta")
        assert response.status_code == 200
        data = response.json()
        assert data["latest_eta"] is None
        assert data["eta_update"] is None

    def test_invalid_eta_payload_rejected(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/eta-updates",
            json={
                "new_eta": "2026-08-14T18:00:00",
                "update_timestamp": "2026-08-13T12:00:00+00:00",
                "source": "dispatch",
            },
        )
        assert response.status_code == 422

    def test_create_exception_api(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][1]
        driver = seeded_session["drivers"][0]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/exceptions",
            json={
                "exception_type": "delay",
                "occurred_at": "2026-08-13T11:00:00+00:00",
                "driver_id": str(driver.id),
            },
        )
        assert response.status_code == 201
        assert response.json()["status"] == "open"

    def test_resolve_exception_api(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        exception = seeded_session["exception"]
        response = seeded_client.patch(
            f"/driver-exceptions/{exception.id}",
            json={"status": "acknowledged"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "acknowledged"

    def test_exception_detail_api(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        exception = seeded_session["exception"]
        response = seeded_client.get(f"/driver-exceptions/{exception.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["destination_facility_id"] is not None
        assert len(data["chat_thread_ids"]) >= 1

    def test_eta_history_grows_after_create(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][0]
        before = seeded_client.get(f"/shipments/{shipment.id}/eta-updates").json()["total"]
        seeded_client.post(
            f"/shipments/{shipment.id}/eta-updates",
            json={
                "new_eta": "2026-08-15T10:00:00+00:00",
                "update_timestamp": "2026-08-13T13:00:00+00:00",
                "source": "carrier",
                "reason": "Carrier correction",
            },
        )
        after = seeded_client.get(f"/shipments/{shipment.id}/eta-updates").json()["total"]
        assert after == before + 1

    def test_shipment_not_found_on_create_eta(self, seeded_client: TestClient) -> None:
        response = seeded_client.post(
            f"/shipments/{uuid.uuid4()}/eta-updates",
            json={
                "new_eta": "2026-08-14T18:00:00+00:00",
                "update_timestamp": "2026-08-13T12:00:00+00:00",
                "source": "dispatch",
            },
        )
        assert response.status_code == 404

    def test_invalid_driver_on_create_exception(
        self, seeded_client: TestClient, seeded_session: dict
    ) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/exceptions",
            json={
                "exception_type": "delay",
                "occurred_at": "2026-08-13T11:00:00+00:00",
                "driver_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 404
