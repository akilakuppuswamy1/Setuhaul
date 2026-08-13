from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.repositories.vehicle import VehicleRepository
from app.schemas.common import PaginatedResponse
from app.schemas.vehicle import VehicleResponse
from app.services.helpers import to_paginated


class VehicleService:
    def __init__(self, session: Session) -> None:
        self._repo = VehicleRepository(session)

    def get(self, vehicle_id: UUID) -> VehicleResponse:
        vehicle = self._repo.get_by_id(vehicle_id)
        if vehicle is None:
            raise NotFoundError(f"Vehicle {vehicle_id} not found")
        return VehicleResponse.model_validate(vehicle)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        carrier_id: UUID | None = None,
    ) -> PaginatedResponse[VehicleResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            carrier_id=carrier_id,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=VehicleResponse,
        )
