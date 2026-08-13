"""Pydantic request/response schemas for SetuHaul APIs."""

from app.schemas.appointment import AppointmentResponse
from app.schemas.appointment_slot import AppointmentSlotResponse
from app.schemas.carrier import CarrierResponse
from app.schemas.chat_message import ChatMessageResponse
from app.schemas.chat_thread import ChatThreadResponse
from app.schemas.common import PaginatedResponse, PaginationParams
from app.schemas.contact import ContactResponse
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationCreateResponse,
    ConversationMessageRequest,
    ConversationMessageResponse,
)
from app.schemas.dock import DockResponse
from app.schemas.driver import DriverResponse
from app.schemas.driver_exception import (
    DriverExceptionCreate,
    DriverExceptionDetailResponse,
    DriverExceptionResponse,
    DriverExceptionStatusUpdate,
)
from app.schemas.eta_update import (
    ETAUpdateCreate,
    ETAUpdateResponse,
    LatestETAResponse,
)
from app.schemas.facility import FacilityResponse
from app.schemas.facility_checkin import FacilityCheckinResponse
from app.schemas.facility_rule import FacilityRuleResponse
from app.schemas.operational_message import OperationalMessageResponse
from app.schemas.proposal import ProposalResponse
from app.schemas.scheduling import (
    ScheduleEvaluateRequest,
    ScheduleEvaluateResponse,
)
from app.schemas.shipment import ShipmentDetailResponse, ShipmentResponse
from app.schemas.vehicle import VehicleResponse

__all__ = [
    "AppointmentResponse",
    "AppointmentSlotResponse",
    "CarrierResponse",
    "ChatMessageResponse",
    "ChatThreadResponse",
    "ContactResponse",
    "ConversationCreateRequest",
    "ConversationCreateResponse",
    "ConversationMessageRequest",
    "ConversationMessageResponse",
    "DockResponse",
    "DriverExceptionCreate",
    "DriverExceptionDetailResponse",
    "DriverExceptionResponse",
    "DriverExceptionStatusUpdate",
    "DriverResponse",
    "ETAUpdateCreate",
    "ETAUpdateResponse",
    "LatestETAResponse",
    "FacilityCheckinResponse",
    "FacilityResponse",
    "FacilityRuleResponse",
    "OperationalMessageResponse",
    "PaginatedResponse",
    "PaginationParams",
    "ShipmentDetailResponse",
    "ShipmentResponse",
    "VehicleResponse",
]
