from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import AppointmentStatus
from app.repositories.appointment import AppointmentRepository
from app.repositories.appointment_slot import AppointmentSlotRepository
from app.repositories.dock import DockRepository
from app.repositories.facility_rule import FacilityRuleRepository
from app.repositories.shipment import ShipmentRepository
from app.schemas.appointment import AppointmentResponse
from app.schemas.appointment_slot import AppointmentSlotResponse
from app.schemas.common import PaginatedResponse
from app.schemas.dock import DockResponse
from app.schemas.facility_rule import FacilityRuleResponse
from app.services.helpers import to_paginated


class AppointmentService:
    def __init__(self, session: Session) -> None:
        self._repo = AppointmentRepository(session)
        self._shipments = ShipmentRepository(session)

    def get(self, appointment_id: UUID) -> AppointmentResponse:
        appointment = self._repo.get_by_id(appointment_id)
        if appointment is None:
            raise NotFoundError(f"Appointment {appointment_id} not found")
        return self._to_response(appointment)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        shipment_id: UUID | None = None,
        facility_id: UUID | None = None,
        appointment_status: AppointmentStatus | None = None,
    ) -> PaginatedResponse[AppointmentResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            shipment_id=shipment_id,
            facility_id=facility_id,
            appointment_status=appointment_status,
        )
        return PaginatedResponse(
            items=[self._to_response(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def _to_response(self, appointment) -> AppointmentResponse:
        payload = AppointmentResponse.model_validate(appointment)
        shipment = self._shipments.get_by_id(appointment.shipment_id)
        number = shipment.shipment_number if shipment is not None else None
        return payload.model_copy(update={"shipment_number": number})


class AppointmentSlotService:
    def __init__(self, session: Session) -> None:
        self._repo = AppointmentSlotRepository(session)

    def get(self, slot_id: UUID) -> AppointmentSlotResponse:
        slot = self._repo.get_by_id(slot_id)
        if slot is None:
            raise NotFoundError(f"Appointment slot {slot_id} not found")
        return AppointmentSlotResponse.model_validate(slot)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        facility_id: UUID | None = None,
    ) -> PaginatedResponse[AppointmentSlotResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            facility_id=facility_id,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=AppointmentSlotResponse,
        )

    def list_open_for_facility(self, facility_id: UUID) -> list[AppointmentSlotResponse]:
        items = self._repo.list_open_by_facility(facility_id)
        return [AppointmentSlotResponse.model_validate(item) for item in items]


class DockService:
    def __init__(self, session: Session) -> None:
        self._repo = DockRepository(session)

    def get(self, dock_id: UUID) -> DockResponse:
        dock = self._repo.get_by_id(dock_id)
        if dock is None:
            raise NotFoundError(f"Dock {dock_id} not found")
        return DockResponse.model_validate(dock)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        facility_id: UUID | None = None,
    ) -> PaginatedResponse[DockResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            facility_id=facility_id,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=DockResponse,
        )


class FacilityRuleService:
    def __init__(self, session: Session) -> None:
        self._repo = FacilityRuleRepository(session)

    def get(self, rule_id: UUID) -> FacilityRuleResponse:
        rule = self._repo.get_by_id(rule_id)
        if rule is None:
            raise NotFoundError(f"Facility rule {rule_id} not found")
        return FacilityRuleResponse.model_validate(rule)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        facility_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> PaginatedResponse[FacilityRuleResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            facility_id=facility_id,
            is_active=is_active,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=FacilityRuleResponse,
        )
