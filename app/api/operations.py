from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    get_driver_exception_service,
    get_eta_update_service,
    get_facility_checkin_service,
    get_operational_message_service,
    get_pagination,
)
from app.models.enums import ETASource, ExceptionStatus
from app.schemas.common import PaginatedResponse
from app.schemas.driver_exception import (
    DriverExceptionDetailResponse,
    DriverExceptionResponse,
    DriverExceptionStatusUpdate,
)
from app.schemas.eta_update import ETAUpdateResponse
from app.schemas.facility_checkin import FacilityCheckinResponse
from app.schemas.operational_message import OperationalMessageResponse
from app.services.operations import (
    DriverExceptionService,
    ETAUpdateService,
    FacilityCheckinService,
    OperationalMessageService,
)

router = APIRouter(tags=["Operations"])


@router.get(
    "/eta-updates",
    response_model=PaginatedResponse[ETAUpdateResponse],
    summary="List ETA updates",
)
def list_eta_updates(
    pagination: tuple[int, int] = Depends(get_pagination),
    shipment_id: UUID | None = Query(None, description="Filter by shipment"),
    source: ETASource | None = Query(None, description="Filter by ETA source"),
    service: ETAUpdateService = Depends(get_eta_update_service),
) -> PaginatedResponse[ETAUpdateResponse]:
    page, page_size = pagination
    return service.list(page=page, page_size=page_size, shipment_id=shipment_id, source=source)


@router.get(
    "/eta-updates/{eta_update_id}",
    response_model=ETAUpdateResponse,
    summary="Get ETA update by ID",
    responses={404: {"description": "ETA update not found"}},
)
def get_eta_update(
    eta_update_id: UUID,
    service: ETAUpdateService = Depends(get_eta_update_service),
) -> ETAUpdateResponse:
    return service.get(eta_update_id)


@router.get(
    "/driver-exceptions",
    response_model=PaginatedResponse[DriverExceptionResponse],
    summary="List driver exceptions",
)
def list_driver_exceptions(
    pagination: tuple[int, int] = Depends(get_pagination),
    shipment_id: UUID | None = Query(None, description="Filter by shipment"),
    driver_id: UUID | None = Query(None, description="Filter by driver"),
    exception_status: ExceptionStatus | None = Query(None, description="Filter by status"),
    service: DriverExceptionService = Depends(get_driver_exception_service),
) -> PaginatedResponse[DriverExceptionResponse]:
    page, page_size = pagination
    return service.list(
        page=page,
        page_size=page_size,
        shipment_id=shipment_id,
        driver_id=driver_id,
        exception_status=exception_status,
    )


@router.get(
    "/driver-exceptions/{exception_id}",
    response_model=DriverExceptionDetailResponse,
    summary="Get driver exception by ID with operational context",
    responses={404: {"description": "Driver exception not found"}},
)
def get_driver_exception(
    exception_id: UUID,
    service: DriverExceptionService = Depends(get_driver_exception_service),
) -> DriverExceptionDetailResponse:
    return service.get_detail(exception_id)


@router.patch(
    "/driver-exceptions/{exception_id}",
    response_model=DriverExceptionResponse,
    summary="Update driver exception status",
    responses={
        404: {"description": "Driver exception not found"},
        400: {"description": "Invalid status transition"},
        422: {"description": "Invalid payload"},
    },
)
def update_driver_exception_status(
    exception_id: UUID,
    payload: DriverExceptionStatusUpdate,
    service: DriverExceptionService = Depends(get_driver_exception_service),
) -> DriverExceptionResponse:
    return service.update_status(exception_id, payload)


@router.get(
    "/facility-checkins",
    response_model=PaginatedResponse[FacilityCheckinResponse],
    summary="List facility check-ins",
)
def list_facility_checkins(
    pagination: tuple[int, int] = Depends(get_pagination),
    shipment_id: UUID | None = Query(None, description="Filter by shipment"),
    facility_id: UUID | None = Query(None, description="Filter by facility"),
    service: FacilityCheckinService = Depends(get_facility_checkin_service),
) -> PaginatedResponse[FacilityCheckinResponse]:
    page, page_size = pagination
    return service.list(
        page=page,
        page_size=page_size,
        shipment_id=shipment_id,
        facility_id=facility_id,
    )


@router.get(
    "/facility-checkins/{checkin_id}",
    response_model=FacilityCheckinResponse,
    summary="Get facility check-in by ID",
    responses={404: {"description": "Facility check-in not found"}},
)
def get_facility_checkin(
    checkin_id: UUID,
    service: FacilityCheckinService = Depends(get_facility_checkin_service),
) -> FacilityCheckinResponse:
    return service.get(checkin_id)


@router.get(
    "/operational-messages",
    response_model=PaginatedResponse[OperationalMessageResponse],
    summary="List operational messages",
)
def list_operational_messages(
    pagination: tuple[int, int] = Depends(get_pagination),
    shipment_id: UUID | None = Query(None, description="Filter by shipment"),
    contact_id: UUID | None = Query(None, description="Filter by contact"),
    service: OperationalMessageService = Depends(get_operational_message_service),
) -> PaginatedResponse[OperationalMessageResponse]:
    page, page_size = pagination
    return service.list(
        page=page,
        page_size=page_size,
        shipment_id=shipment_id,
        contact_id=contact_id,
    )


@router.get(
    "/operational-messages/{message_id}",
    response_model=OperationalMessageResponse,
    summary="Get operational message by ID",
    responses={404: {"description": "Operational message not found"}},
)
def get_operational_message(
    message_id: UUID,
    service: OperationalMessageService = Depends(get_operational_message_service),
) -> OperationalMessageResponse:
    return service.get(message_id)
