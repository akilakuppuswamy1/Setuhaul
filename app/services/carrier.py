from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.repositories.carrier import CarrierRepository
from app.schemas.carrier import CarrierResponse
from app.schemas.common import PaginatedResponse
from app.services.helpers import to_paginated


class CarrierService:
    def __init__(self, session: Session) -> None:
        self._repo = CarrierRepository(session)

    def get(self, carrier_id: UUID) -> CarrierResponse:
        carrier = self._repo.get_by_id(carrier_id)
        if carrier is None:
            raise NotFoundError(f"Carrier {carrier_id} not found")
        return CarrierResponse.model_validate(carrier)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResponse[CarrierResponse]:
        items, total = self._repo.list_paginated(page=page, page_size=page_size)
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=CarrierResponse,
        )
