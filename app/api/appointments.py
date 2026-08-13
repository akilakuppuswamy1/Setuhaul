from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    get_appointment_service,
    get_appointment_slot_service,
    get_dock_service,
    get_facility_rule_service,
    get_pagination,
)
from app.models.enums import AppointmentStatus
from app.schemas.appointment import AppointmentResponse
from app.schemas.appointment_slot import AppointmentSlotResponse
from app.schemas.common import PaginatedResponse
from app.schemas.dock import DockResponse
from app.schemas.facility_rule import FacilityRuleResponse
from app.services.appointment import (
    AppointmentService,
    AppointmentSlotService,
    DockService,
    FacilityRuleService,
)

router = APIRouter(tags=["Appointments"])


@router.get(
    "/appointments",
    response_model=PaginatedResponse[AppointmentResponse],
    summary="List appointments",
)
def list_appointments(
    pagination: tuple[int, int] = Depends(get_pagination),
    shipment_id: UUID | None = Query(None, description="Filter by shipment"),
    facility_id: UUID | None = Query(None, description="Filter by facility"),
    appointment_status: AppointmentStatus | None = Query(None, description="Filter by status"),
    service: AppointmentService = Depends(get_appointment_service),
) -> PaginatedResponse[AppointmentResponse]:
    page, page_size = pagination
    return service.list(
        page=page,
        page_size=page_size,
        shipment_id=shipment_id,
        facility_id=facility_id,
        appointment_status=appointment_status,
    )


@router.get(
    "/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    summary="Get appointment by ID",
    responses={404: {"description": "Appointment not found"}},
)
def get_appointment(
    appointment_id: UUID,
    service: AppointmentService = Depends(get_appointment_service),
) -> AppointmentResponse:
    return service.get(appointment_id)


@router.get(
    "/appointment-slots",
    response_model=PaginatedResponse[AppointmentSlotResponse],
    summary="List appointment slots",
)
def list_appointment_slots(
    pagination: tuple[int, int] = Depends(get_pagination),
    facility_id: UUID | None = Query(None, description="Filter by facility"),
    service: AppointmentSlotService = Depends(get_appointment_slot_service),
) -> PaginatedResponse[AppointmentSlotResponse]:
    page, page_size = pagination
    return service.list(page=page, page_size=page_size, facility_id=facility_id)


@router.get(
    "/appointment-slots/{slot_id}",
    response_model=AppointmentSlotResponse,
    summary="Get appointment slot by ID",
    responses={404: {"description": "Appointment slot not found"}},
)
def get_appointment_slot(
    slot_id: UUID,
    service: AppointmentSlotService = Depends(get_appointment_slot_service),
) -> AppointmentSlotResponse:
    return service.get(slot_id)


@router.get(
    "/docks",
    response_model=PaginatedResponse[DockResponse],
    summary="List docks",
)
def list_docks(
    pagination: tuple[int, int] = Depends(get_pagination),
    facility_id: UUID | None = Query(None, description="Filter by facility"),
    service: DockService = Depends(get_dock_service),
) -> PaginatedResponse[DockResponse]:
    page, page_size = pagination
    return service.list(page=page, page_size=page_size, facility_id=facility_id)


@router.get(
    "/docks/{dock_id}",
    response_model=DockResponse,
    summary="Get dock by ID",
    responses={404: {"description": "Dock not found"}},
)
def get_dock(
    dock_id: UUID,
    service: DockService = Depends(get_dock_service),
) -> DockResponse:
    return service.get(dock_id)


@router.get(
    "/facility-rules",
    response_model=PaginatedResponse[FacilityRuleResponse],
    summary="List facility rules",
)
def list_facility_rules(
    pagination: tuple[int, int] = Depends(get_pagination),
    facility_id: UUID | None = Query(None, description="Filter by facility"),
    is_active: bool | None = Query(None, description="Filter by active flag"),
    service: FacilityRuleService = Depends(get_facility_rule_service),
) -> PaginatedResponse[FacilityRuleResponse]:
    page, page_size = pagination
    return service.list(
        page=page,
        page_size=page_size,
        facility_id=facility_id,
        is_active=is_active,
    )


@router.get(
    "/facility-rules/{rule_id}",
    response_model=FacilityRuleResponse,
    summary="Get facility rule by ID",
    responses={404: {"description": "Facility rule not found"}},
)
def get_facility_rule(
    rule_id: UUID,
    service: FacilityRuleService = Depends(get_facility_rule_service),
) -> FacilityRuleResponse:
    return service.get(rule_id)
