from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import EntityStatus
from app.repositories.driver import DriverRepository
from app.schemas.common import PaginatedResponse
from app.schemas.driver import DriverResponse
from app.services.helpers import to_paginated


class DriverService:
    def __init__(self, session: Session) -> None:
        self._repo = DriverRepository(session)

    def get(self, driver_id: UUID) -> DriverResponse:
        driver = self._repo.get_by_id(driver_id)
        if driver is None:
            raise NotFoundError(f"Driver {driver_id} not found")
        return DriverResponse.model_validate(driver)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        carrier_id: UUID | None = None,
        driver_status: EntityStatus | None = None,
    ) -> PaginatedResponse[DriverResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            carrier_id=carrier_id,
            driver_status=driver_status,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=DriverResponse,
        )
