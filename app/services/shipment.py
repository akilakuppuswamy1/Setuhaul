from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import ShipmentStatus
from app.repositories.appointment import AppointmentRepository
from app.repositories.chat_thread import ChatThreadRepository
from app.repositories.driver_exception import DriverExceptionRepository
from app.repositories.eta_update import ETAUpdateRepository
from app.repositories.facility_checkin import FacilityCheckinRepository
from app.repositories.shipment import ShipmentRepository
from app.schemas.appointment import AppointmentResponse
from app.schemas.chat_thread import ChatThreadResponse
from app.schemas.common import PaginatedResponse
from app.schemas.driver_exception import DriverExceptionResponse
from app.schemas.eta_update import ETAUpdateResponse
from app.schemas.facility_checkin import FacilityCheckinResponse
from app.schemas.shipment import ShipmentDetailResponse, ShipmentResponse
from app.services.helpers import to_paginated


class ShipmentService:
    def __init__(self, session: Session) -> None:
        self._repo = ShipmentRepository(session)
        self._eta_repo = ETAUpdateRepository(session)
        self._exception_repo = DriverExceptionRepository(session)
        self._checkin_repo = FacilityCheckinRepository(session)
        self._appointment_repo = AppointmentRepository(session)
        self._chat_thread_repo = ChatThreadRepository(session)

    def _ensure_exists(self, shipment_id: UUID) -> None:
        if self._repo.get_by_id(shipment_id) is None:
            raise NotFoundError(f"Shipment {shipment_id} not found")

    def get(self, shipment_id: UUID) -> ShipmentDetailResponse:
        shipment = self._repo.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found")
        latest_eta_update = self._repo.get_latest_eta(shipment_id)
        base = ShipmentResponse.model_validate(shipment)
        return ShipmentDetailResponse(
            **base.model_dump(),
            latest_eta=latest_eta_update.new_eta if latest_eta_update else None,
        )

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        driver_id: UUID | None = None,
        carrier_id: UUID | None = None,
        facility_id: UUID | None = None,
        destination_facility_id: UUID | None = None,
        status: ShipmentStatus | None = None,
        current_status: ShipmentStatus | None = None,
        is_active: bool | None = None,
    ) -> PaginatedResponse[ShipmentResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            driver_id=driver_id,
            carrier_id=carrier_id,
            facility_id=facility_id,
            destination_facility_id=destination_facility_id,
            status=status,
            current_status=current_status,
            is_active=is_active,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=ShipmentResponse,
        )

    def list_eta_updates(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[ETAUpdateResponse]:
        self._ensure_exists(shipment_id)
        items, total = self._eta_repo.list_by_shipment(
            shipment_id, page=page, page_size=page_size
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=ETAUpdateResponse,
        )

    def list_exceptions(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[DriverExceptionResponse]:
        self._ensure_exists(shipment_id)
        items, total = self._exception_repo.list_by_shipment(
            shipment_id, page=page, page_size=page_size
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=DriverExceptionResponse,
        )

    def list_appointments(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[AppointmentResponse]:
        self._ensure_exists(shipment_id)
        items, total = self._appointment_repo.list_by_shipment(
            shipment_id, page=page, page_size=page_size
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=AppointmentResponse,
        )

    def list_checkins(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[FacilityCheckinResponse]:
        self._ensure_exists(shipment_id)
        items, total = self._checkin_repo.list_by_shipment(
            shipment_id, page=page, page_size=page_size
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=FacilityCheckinResponse,
        )

    def list_chat_threads(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[ChatThreadResponse]:
        self._ensure_exists(shipment_id)
        items, total = self._chat_thread_repo.list_by_shipment(
            shipment_id, page=page, page_size=page_size
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=ChatThreadResponse,
        )
