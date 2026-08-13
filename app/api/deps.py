"""FastAPI dependency injection for services."""

from collections.abc import Callable, Generator
from typing import TypeVar

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.services.allocation import AllocationService
from app.services.appointment import (
    AppointmentService,
    AppointmentSlotService,
    DockService,
    FacilityRuleService,
)
from app.services.carrier import CarrierService
from app.services.conversation import ConversationService
from app.services.conversations import ChatMessageService, ChatThreadService, ContactService
from app.services.driver import DriverService
from app.services.facility import FacilityService
from app.services.feasibility import FeasibilityService
from app.services.operations import (
    DriverExceptionService,
    ETAUpdateService,
    FacilityCheckinService,
    OperationalMessageService,
)
from app.services.proposal import ProposalService
from app.services.shipment import ShipmentService
from app.services.vehicle import VehicleService

T = TypeVar("T")


def get_pagination(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Items per page",
    ),
) -> tuple[int, int]:
    return page, page_size


def _service_factory(service_cls: type[T]) -> Callable[[Session], T]:
    def _get_service(db: Session = Depends(get_db)) -> T:
        return service_cls(db)

    return _get_service


get_carrier_service = _service_factory(CarrierService)
get_driver_service = _service_factory(DriverService)
get_vehicle_service = _service_factory(VehicleService)
get_shipment_service = _service_factory(ShipmentService)
get_facility_service = _service_factory(FacilityService)
get_appointment_service = _service_factory(AppointmentService)
get_appointment_slot_service = _service_factory(AppointmentSlotService)
get_dock_service = _service_factory(DockService)
get_facility_rule_service = _service_factory(FacilityRuleService)
get_feasibility_service = _service_factory(FeasibilityService)
get_allocation_service = _service_factory(AllocationService)
get_proposal_service = _service_factory(ProposalService)
get_eta_update_service = _service_factory(ETAUpdateService)
get_driver_exception_service = _service_factory(DriverExceptionService)
get_facility_checkin_service = _service_factory(FacilityCheckinService)
get_operational_message_service = _service_factory(OperationalMessageService)
get_chat_thread_service = _service_factory(ChatThreadService)
get_chat_message_service = _service_factory(ChatMessageService)
get_contact_service = _service_factory(ContactService)
get_conversation_service = _service_factory(ConversationService)
