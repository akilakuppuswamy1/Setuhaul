from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, SetuHaulError
from app.models.enums import ETASource, ExceptionStatus
from app.repositories.chat_thread import ChatThreadRepository
from app.repositories.driver import DriverRepository
from app.repositories.driver_exception import DriverExceptionRepository
from app.repositories.eta_update import ETAUpdateRepository
from app.repositories.facility_checkin import FacilityCheckinRepository
from app.repositories.operational_message import OperationalMessageRepository
from app.repositories.shipment import ShipmentRepository
from app.schemas.common import PaginatedResponse
from app.schemas.driver_exception import (
    DriverExceptionCreate,
    DriverExceptionDetailResponse,
    DriverExceptionResponse,
    DriverExceptionStatusUpdate,
)
from app.schemas.eta_update import ETAUpdateCreate, ETAUpdateResponse, LatestETAResponse
from app.schemas.facility_checkin import FacilityCheckinResponse
from app.schemas.operational_message import OperationalMessageResponse
from app.services.helpers import safe_commit, to_paginated

_VALID_EXCEPTION_TRANSITIONS: dict[ExceptionStatus, set[ExceptionStatus]] = {
    ExceptionStatus.OPEN: {ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.RESOLVED},
    ExceptionStatus.ACKNOWLEDGED: {ExceptionStatus.RESOLVED},
    ExceptionStatus.RESOLVED: set(),
}


class ETAUpdateService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ETAUpdateRepository(session)
        self._shipment_repo = ShipmentRepository(session)

    def _ensure_shipment_exists(self, shipment_id: UUID) -> None:
        if self._shipment_repo.get_by_id(shipment_id) is None:
            raise NotFoundError(f"Shipment {shipment_id} not found")

    def get(self, eta_update_id: UUID) -> ETAUpdateResponse:
        eta_update = self._repo.get_by_id(eta_update_id)
        if eta_update is None:
            raise NotFoundError(f"ETA update {eta_update_id} not found")
        return ETAUpdateResponse.model_validate(eta_update)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        shipment_id: UUID | None = None,
        source: ETASource | None = None,
    ) -> PaginatedResponse[ETAUpdateResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            shipment_id=shipment_id,
            source=source,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=ETAUpdateResponse,
        )

    def create(self, shipment_id: UUID, payload: ETAUpdateCreate) -> ETAUpdateResponse:
        """Record a new immutable ETA update; previous_eta is derived from history."""
        self._ensure_shipment_exists(shipment_id)
        latest = self._shipment_repo.get_latest_eta(shipment_id)
        previous_eta = latest.new_eta if latest is not None else None
        eta_update = self._repo.create(
            shipment_id=shipment_id,
            previous_eta=previous_eta,
            new_eta=payload.new_eta,
            update_timestamp=payload.update_timestamp,
            source=payload.source,
            reason=payload.reason,
        )
        safe_commit(self._session)
        return ETAUpdateResponse.model_validate(eta_update)

    def get_latest(self, shipment_id: UUID) -> LatestETAResponse:
        """Derive the latest ETA strictly from ETAUpdate history."""
        self._ensure_shipment_exists(shipment_id)
        latest = self._shipment_repo.get_latest_eta(shipment_id)
        if latest is None:
            return LatestETAResponse(
                shipment_id=shipment_id,
                latest_eta=None,
                eta_update=None,
            )
        return LatestETAResponse(
            shipment_id=shipment_id,
            latest_eta=latest.new_eta,
            eta_update=ETAUpdateResponse.model_validate(latest),
        )


class DriverExceptionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = DriverExceptionRepository(session)
        self._shipment_repo = ShipmentRepository(session)
        self._driver_repo = DriverRepository(session)
        self._chat_thread_repo = ChatThreadRepository(session)

    def _ensure_shipment_exists(self, shipment_id: UUID) -> None:
        if self._shipment_repo.get_by_id(shipment_id) is None:
            raise NotFoundError(f"Shipment {shipment_id} not found")

    def _ensure_driver_exists(self, driver_id: UUID) -> None:
        if self._driver_repo.get_by_id(driver_id) is None:
            raise NotFoundError(f"Driver {driver_id} not found")

    def get(self, exception_id: UUID) -> DriverExceptionResponse:
        exception = self._repo.get_by_id(exception_id)
        if exception is None:
            raise NotFoundError(f"Driver exception {exception_id} not found")
        return DriverExceptionResponse.model_validate(exception)

    def get_detail(self, exception_id: UUID) -> DriverExceptionDetailResponse:
        exception = self._repo.get_by_id(exception_id)
        if exception is None:
            raise NotFoundError(f"Driver exception {exception_id} not found")

        shipment = self._shipment_repo.get_by_id(exception.shipment_id)
        driver_name = None
        if exception.driver_id is not None:
            driver = self._driver_repo.get_by_id(exception.driver_id)
            driver_name = driver.name if driver is not None else None

        chat_threads = self._chat_thread_repo.list_by_driver_exception(exception_id)
        base = DriverExceptionResponse.model_validate(exception)
        return DriverExceptionDetailResponse(
            **base.model_dump(),
            destination_facility_id=(
                shipment.destination_facility_id if shipment is not None else None
            ),
            driver_name=driver_name,
            chat_thread_ids=[thread.id for thread in chat_threads],
        )

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        shipment_id: UUID | None = None,
        driver_id: UUID | None = None,
        exception_status: ExceptionStatus | None = None,
    ) -> PaginatedResponse[DriverExceptionResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            shipment_id=shipment_id,
            driver_id=driver_id,
            exception_status=exception_status,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=DriverExceptionResponse,
        )

    def create(
        self,
        shipment_id: UUID,
        payload: DriverExceptionCreate,
    ) -> DriverExceptionResponse:
        self._ensure_shipment_exists(shipment_id)
        if payload.driver_id is not None:
            self._ensure_driver_exists(payload.driver_id)

        exception = self._repo.create(
            shipment_id=shipment_id,
            driver_id=payload.driver_id,
            exception_type=payload.exception_type,
            description=payload.description,
            occurred_at=payload.occurred_at,
        )
        safe_commit(self._session)
        return DriverExceptionResponse.model_validate(exception)

    def update_status(
        self,
        exception_id: UUID,
        payload: DriverExceptionStatusUpdate,
    ) -> DriverExceptionResponse:
        exception = self._repo.get_by_id(exception_id)
        if exception is None:
            raise NotFoundError(f"Driver exception {exception_id} not found")

        allowed = _VALID_EXCEPTION_TRANSITIONS.get(exception.status, set())
        if payload.status not in allowed:
            raise SetuHaulError(
                f"Cannot transition exception from {exception.status.value} "
                f"to {payload.status.value}"
            )

        exception.status = payload.status
        if payload.status == ExceptionStatus.RESOLVED:
            exception.resolved_at = payload.resolved_at or datetime.now(timezone.utc)
        elif payload.status == ExceptionStatus.ACKNOWLEDGED:
            exception.resolved_at = None

        safe_commit(self._session)
        self._session.refresh(exception)
        return DriverExceptionResponse.model_validate(exception)


class FacilityCheckinService:
    def __init__(self, session: Session) -> None:
        self._repo = FacilityCheckinRepository(session)

    def get(self, checkin_id: UUID) -> FacilityCheckinResponse:
        checkin = self._repo.get_by_id(checkin_id)
        if checkin is None:
            raise NotFoundError(f"Facility check-in {checkin_id} not found")
        return FacilityCheckinResponse.model_validate(checkin)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        shipment_id: UUID | None = None,
        facility_id: UUID | None = None,
    ) -> PaginatedResponse[FacilityCheckinResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            shipment_id=shipment_id,
            facility_id=facility_id,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=FacilityCheckinResponse,
        )


class OperationalMessageService:
    def __init__(self, session: Session) -> None:
        self._repo = OperationalMessageRepository(session)

    def get(self, message_id: UUID) -> OperationalMessageResponse:
        message = self._repo.get_by_id(message_id)
        if message is None:
            raise NotFoundError(f"Operational message {message_id} not found")
        return OperationalMessageResponse.model_validate(message)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        shipment_id: UUID | None = None,
        contact_id: UUID | None = None,
    ) -> PaginatedResponse[OperationalMessageResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            shipment_id=shipment_id,
            contact_id=contact_id,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=OperationalMessageResponse,
        )
