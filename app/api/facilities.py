from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_facility_service, get_pagination
from app.schemas.appointment_slot import AppointmentSlotResponse
from app.schemas.common import PaginatedResponse
from app.schemas.dock import DockResponse
from app.schemas.facility import FacilityResponse
from app.schemas.facility_checkin import FacilityCheckinResponse
from app.schemas.facility_rule import FacilityRuleResponse
from app.services.facility import FacilityService

router = APIRouter(prefix="/facilities", tags=["Facilities"])


@router.get(
    "",
    response_model=PaginatedResponse[FacilityResponse],
    summary="List facilities",
)
def list_facilities(
    pagination: tuple[int, int] = Depends(get_pagination),
    facility_name: str | None = Query(None, description="Filter by facility name (partial match)"),
    service: FacilityService = Depends(get_facility_service),
) -> PaginatedResponse[FacilityResponse]:
    page, page_size = pagination
    return service.list(page=page, page_size=page_size, facility_name=facility_name)


@router.get(
    "/{facility_id}",
    response_model=FacilityResponse,
    summary="Get facility by ID",
    responses={404: {"description": "Facility not found"}},
)
def get_facility(
    facility_id: UUID,
    service: FacilityService = Depends(get_facility_service),
) -> FacilityResponse:
    return service.get(facility_id)


@router.get(
    "/{facility_id}/docks",
    response_model=PaginatedResponse[DockResponse],
    summary="List docks at a facility",
    responses={404: {"description": "Facility not found"}},
)
def list_facility_docks(
    facility_id: UUID,
    pagination: tuple[int, int] = Depends(get_pagination),
    service: FacilityService = Depends(get_facility_service),
) -> PaginatedResponse[DockResponse]:
    page, page_size = pagination
    return service.list_docks(facility_id, page=page, page_size=page_size)


@router.get(
    "/{facility_id}/rules",
    response_model=PaginatedResponse[FacilityRuleResponse],
    summary="List rules for a facility",
    responses={404: {"description": "Facility not found"}},
)
def list_facility_rules(
    facility_id: UUID,
    pagination: tuple[int, int] = Depends(get_pagination),
    service: FacilityService = Depends(get_facility_service),
) -> PaginatedResponse[FacilityRuleResponse]:
    page, page_size = pagination
    return service.list_rules(facility_id, page=page, page_size=page_size)


@router.get(
    "/{facility_id}/appointment-slots",
    response_model=PaginatedResponse[AppointmentSlotResponse],
    summary="List appointment slots at a facility",
    responses={404: {"description": "Facility not found"}},
)
def list_facility_appointment_slots(
    facility_id: UUID,
    pagination: tuple[int, int] = Depends(get_pagination),
    service: FacilityService = Depends(get_facility_service),
) -> PaginatedResponse[AppointmentSlotResponse]:
    page, page_size = pagination
    return service.list_appointment_slots(facility_id, page=page, page_size=page_size)


@router.get(
    "/{facility_id}/check-ins",
    response_model=PaginatedResponse[FacilityCheckinResponse],
    summary="List check-ins at a facility",
    responses={404: {"description": "Facility not found"}},
)
def list_facility_checkins(
    facility_id: UUID,
    pagination: tuple[int, int] = Depends(get_pagination),
    service: FacilityService = Depends(get_facility_service),
) -> PaginatedResponse[FacilityCheckinResponse]:
    page, page_size = pagination
    return service.list_checkins(facility_id, page=page, page_size=page_size)
