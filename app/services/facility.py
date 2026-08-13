from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.repositories.appointment_slot import AppointmentSlotRepository
from app.repositories.dock import DockRepository
from app.repositories.facility import FacilityRepository
from app.repositories.facility_checkin import FacilityCheckinRepository
from app.repositories.facility_rule import FacilityRuleRepository
from app.schemas.appointment_slot import AppointmentSlotResponse
from app.schemas.common import PaginatedResponse
from app.schemas.dock import DockResponse
from app.schemas.facility import FacilityResponse
from app.schemas.facility_checkin import FacilityCheckinResponse
from app.schemas.facility_rule import FacilityRuleResponse
from app.services.helpers import to_paginated


class FacilityService:
    def __init__(self, session: Session) -> None:
        self._repo = FacilityRepository(session)
        self._dock_repo = DockRepository(session)
        self._rule_repo = FacilityRuleRepository(session)
        self._slot_repo = AppointmentSlotRepository(session)
        self._checkin_repo = FacilityCheckinRepository(session)

    def _ensure_exists(self, facility_id: UUID) -> None:
        if self._repo.get_by_id(facility_id) is None:
            raise NotFoundError(f"Facility {facility_id} not found")

    def get(self, facility_id: UUID) -> FacilityResponse:
        facility = self._repo.get_by_id(facility_id)
        if facility is None:
            raise NotFoundError(f"Facility {facility_id} not found")
        return FacilityResponse.model_validate(facility)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        facility_name: str | None = None,
    ) -> PaginatedResponse[FacilityResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            facility_name=facility_name,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=FacilityResponse,
        )

    def list_docks(
        self,
        facility_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[DockResponse]:
        self._ensure_exists(facility_id)
        items, total = self._dock_repo.list_by_facility(
            facility_id, page=page, page_size=page_size
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=DockResponse,
        )

    def list_rules(
        self,
        facility_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[FacilityRuleResponse]:
        self._ensure_exists(facility_id)
        items, total = self._rule_repo.list_by_facility(
            facility_id, page=page, page_size=page_size
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=FacilityRuleResponse,
        )

    def list_appointment_slots(
        self,
        facility_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[AppointmentSlotResponse]:
        self._ensure_exists(facility_id)
        items, total = self._slot_repo.list_by_facility(
            facility_id, page=page, page_size=page_size
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=AppointmentSlotResponse,
        )

    def list_checkins(
        self,
        facility_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[FacilityCheckinResponse]:
        self._ensure_exists(facility_id)
        items, total = self._checkin_repo.list_by_facility(
            facility_id, page=page, page_size=page_size
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=FacilityCheckinResponse,
        )
