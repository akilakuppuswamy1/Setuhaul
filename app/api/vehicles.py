from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_pagination, get_vehicle_service
from app.schemas.common import PaginatedResponse
from app.schemas.vehicle import VehicleResponse
from app.services.vehicle import VehicleService

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.get(
    "",
    response_model=PaginatedResponse[VehicleResponse],
    summary="List vehicles",
)
def list_vehicles(
    pagination: tuple[int, int] = Depends(get_pagination),
    carrier_id: UUID | None = Query(None, description="Filter by carrier"),
    service: VehicleService = Depends(get_vehicle_service),
) -> PaginatedResponse[VehicleResponse]:
    page, page_size = pagination
    return service.list(page=page, page_size=page_size, carrier_id=carrier_id)


@router.get(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    summary="Get vehicle by ID",
    responses={404: {"description": "Vehicle not found"}},
)
def get_vehicle(
    vehicle_id: UUID,
    service: VehicleService = Depends(get_vehicle_service),
) -> VehicleResponse:
    return service.get(vehicle_id)
