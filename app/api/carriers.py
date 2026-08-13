from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_carrier_service, get_pagination
from app.schemas.carrier import CarrierResponse
from app.schemas.common import PaginatedResponse
from app.services.carrier import CarrierService

router = APIRouter(prefix="/carriers", tags=["Carriers"])


@router.get(
    "",
    response_model=PaginatedResponse[CarrierResponse],
    summary="List carriers",
)
def list_carriers(
    pagination: tuple[int, int] = Depends(get_pagination),
    service: CarrierService = Depends(get_carrier_service),
) -> PaginatedResponse[CarrierResponse]:
    page, page_size = pagination
    return service.list(page=page, page_size=page_size)


@router.get(
    "/{carrier_id}",
    response_model=CarrierResponse,
    summary="Get carrier by ID",
    responses={404: {"description": "Carrier not found"}},
)
def get_carrier(
    carrier_id: UUID,
    service: CarrierService = Depends(get_carrier_service),
) -> CarrierResponse:
    return service.get(carrier_id)
