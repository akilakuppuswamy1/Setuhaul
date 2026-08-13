from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_driver_service, get_pagination
from app.models.enums import EntityStatus
from app.schemas.common import PaginatedResponse
from app.schemas.driver import DriverResponse
from app.services.driver import DriverService

router = APIRouter(prefix="/drivers", tags=["Drivers"])


@router.get(
    "",
    response_model=PaginatedResponse[DriverResponse],
    summary="List drivers",
)
def list_drivers(
    pagination: tuple[int, int] = Depends(get_pagination),
    carrier_id: UUID | None = Query(None, description="Filter by carrier"),
    driver_status: EntityStatus | None = Query(None, description="Filter by status"),
    service: DriverService = Depends(get_driver_service),
) -> PaginatedResponse[DriverResponse]:
    page, page_size = pagination
    return service.list(
        page=page,
        page_size=page_size,
        carrier_id=carrier_id,
        driver_status=driver_status,
    )


@router.get(
    "/{driver_id}",
    response_model=DriverResponse,
    summary="Get driver by ID",
    responses={404: {"description": "Driver not found"}},
)
def get_driver(
    driver_id: UUID,
    service: DriverService = Depends(get_driver_service),
) -> DriverResponse:
    return service.get(driver_id)
