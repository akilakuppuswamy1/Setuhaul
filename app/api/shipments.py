from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    get_driver_exception_service,
    get_eta_update_service,
    get_pagination,
    get_shipment_service,
)
from app.models.enums import ShipmentStatus
from app.schemas.appointment import AppointmentResponse
from app.schemas.chat_thread import ChatThreadResponse
from app.schemas.common import PaginatedResponse
from app.schemas.driver_exception import DriverExceptionCreate, DriverExceptionResponse
from app.schemas.eta_update import ETAUpdateCreate, ETAUpdateResponse, LatestETAResponse
from app.schemas.facility_checkin import FacilityCheckinResponse
from app.schemas.shipment import ShipmentDetailResponse, ShipmentResponse
from app.services.operations import DriverExceptionService, ETAUpdateService
from app.services.shipment import ShipmentService

router = APIRouter(prefix="/shipments", tags=["Shipments"])


@router.get(
    "",
    response_model=PaginatedResponse[ShipmentResponse],
    summary="List shipments",
)
def list_shipments(
    pagination: tuple[int, int] = Depends(get_pagination),
    driver_id: UUID | None = Query(None, description="Filter by driver"),
    carrier_id: UUID | None = Query(None, description="Filter by carrier"),
    facility_id: UUID | None = Query(None, description="Filter by destination facility"),
    status: ShipmentStatus | None = Query(None, description="Filter by shipment status"),
    is_active: bool | None = Query(None, description="Filter by active flag"),
    service: ShipmentService = Depends(get_shipment_service),
) -> PaginatedResponse[ShipmentResponse]:
    page, page_size = pagination
    return service.list(
        page=page,
        page_size=page_size,
        driver_id=driver_id,
        carrier_id=carrier_id,
        facility_id=facility_id,
        status=status,
        is_active=is_active,
    )


@router.get(
    "/{shipment_id}",
    response_model=ShipmentDetailResponse,
    summary="Get shipment by ID",
    responses={404: {"description": "Shipment not found"}},
)
def get_shipment(
    shipment_id: UUID,
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentDetailResponse:
    return service.get(shipment_id)


@router.get(
    "/{shipment_id}/eta-updates",
    response_model=PaginatedResponse[ETAUpdateResponse],
    summary="List ETA update history for a shipment",
    responses={404: {"description": "Shipment not found"}},
)
def list_shipment_eta_updates(
    shipment_id: UUID,
    pagination: tuple[int, int] = Depends(get_pagination),
    service: ShipmentService = Depends(get_shipment_service),
) -> PaginatedResponse[ETAUpdateResponse]:
    page, page_size = pagination
    return service.list_eta_updates(shipment_id, page=page, page_size=page_size)


@router.post(
    "/{shipment_id}/eta-updates",
    response_model=ETAUpdateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record an ETA update for a shipment",
    responses={
        404: {"description": "Shipment not found"},
        422: {"description": "Invalid ETA payload"},
    },
)
def create_shipment_eta_update(
    shipment_id: UUID,
    payload: ETAUpdateCreate,
    service: ETAUpdateService = Depends(get_eta_update_service),
) -> ETAUpdateResponse:
    return service.create(shipment_id, payload)


@router.get(
    "/{shipment_id}/latest-eta",
    response_model=LatestETAResponse,
    summary="Get latest ETA derived from update history",
    responses={404: {"description": "Shipment not found"}},
)
def get_shipment_latest_eta(
    shipment_id: UUID,
    service: ETAUpdateService = Depends(get_eta_update_service),
) -> LatestETAResponse:
    return service.get_latest(shipment_id)


@router.get(
    "/{shipment_id}/exceptions",
    response_model=PaginatedResponse[DriverExceptionResponse],
    summary="List driver exceptions for a shipment",
    responses={404: {"description": "Shipment not found"}},
)
def list_shipment_exceptions(
    shipment_id: UUID,
    pagination: tuple[int, int] = Depends(get_pagination),
    service: ShipmentService = Depends(get_shipment_service),
) -> PaginatedResponse[DriverExceptionResponse]:
    page, page_size = pagination
    return service.list_exceptions(shipment_id, page=page, page_size=page_size)


@router.post(
    "/{shipment_id}/exceptions",
    response_model=DriverExceptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report a driver exception for a shipment",
    responses={
        404: {"description": "Shipment or driver not found"},
        422: {"description": "Invalid exception payload"},
    },
)
def create_shipment_exception(
    shipment_id: UUID,
    payload: DriverExceptionCreate,
    service: DriverExceptionService = Depends(get_driver_exception_service),
) -> DriverExceptionResponse:
    return service.create(shipment_id, payload)


@router.get(
    "/{shipment_id}/appointments",
    response_model=PaginatedResponse[AppointmentResponse],
    summary="List appointment history for a shipment",
    responses={404: {"description": "Shipment not found"}},
)
def list_shipment_appointments(
    shipment_id: UUID,
    pagination: tuple[int, int] = Depends(get_pagination),
    service: ShipmentService = Depends(get_shipment_service),
) -> PaginatedResponse[AppointmentResponse]:
    page, page_size = pagination
    return service.list_appointments(shipment_id, page=page, page_size=page_size)


@router.get(
    "/{shipment_id}/facility-checkins",
    response_model=PaginatedResponse[FacilityCheckinResponse],
    summary="List facility check-ins for a shipment",
    responses={404: {"description": "Shipment not found"}},
)
def list_shipment_checkins(
    shipment_id: UUID,
    pagination: tuple[int, int] = Depends(get_pagination),
    service: ShipmentService = Depends(get_shipment_service),
) -> PaginatedResponse[FacilityCheckinResponse]:
    page, page_size = pagination
    return service.list_checkins(shipment_id, page=page, page_size=page_size)


@router.get(
    "/{shipment_id}/chat-threads",
    response_model=PaginatedResponse[ChatThreadResponse],
    summary="List chat threads for a shipment",
    responses={404: {"description": "Shipment not found"}},
)
def list_shipment_chat_threads(
    shipment_id: UUID,
    pagination: tuple[int, int] = Depends(get_pagination),
    service: ShipmentService = Depends(get_shipment_service),
) -> PaginatedResponse[ChatThreadResponse]:
    page, page_size = pagination
    return service.list_chat_threads(shipment_id, page=page, page_size=page_size)
