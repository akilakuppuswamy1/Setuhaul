from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import ETASource, ExceptionStatus
from app.repositories.driver_exception import DriverExceptionRepository
from app.repositories.eta_update import ETAUpdateRepository
from app.repositories.facility_checkin import FacilityCheckinRepository
from app.repositories.operational_message import OperationalMessageRepository
from app.schemas.common import PaginatedResponse
from app.schemas.driver_exception import DriverExceptionResponse
from app.schemas.eta_update import ETAUpdateResponse
from app.schemas.facility_checkin import FacilityCheckinResponse
from app.schemas.operational_message import OperationalMessageResponse
from app.services.helpers import to_paginated


class ETAUpdateService:
    def __init__(self, session: Session) -> None:
        self._repo = ETAUpdateRepository(session)

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


class DriverExceptionService:
    def __init__(self, session: Session) -> None:
        self._repo = DriverExceptionRepository(session)

    def get(self, exception_id: UUID) -> DriverExceptionResponse:
        exception = self._repo.get_by_id(exception_id)
        if exception is None:
            raise NotFoundError(f"Driver exception {exception_id} not found")
        return DriverExceptionResponse.model_validate(exception)

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
