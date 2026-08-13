"""Database access layer for SetuHaul domain entities."""

from app.repositories.appointment import AppointmentRepository
from app.repositories.appointment_slot import AppointmentSlotRepository
from app.repositories.carrier import CarrierRepository
from app.repositories.chat_message import ChatMessageRepository
from app.repositories.chat_thread import ChatThreadRepository
from app.repositories.contact import ContactRepository
from app.repositories.dock import DockRepository
from app.repositories.driver import DriverRepository
from app.repositories.driver_exception import DriverExceptionRepository
from app.repositories.eta_update import ETAUpdateRepository
from app.repositories.facility import FacilityRepository
from app.repositories.facility_checkin import FacilityCheckinRepository
from app.repositories.facility_rule import FacilityRuleRepository
from app.repositories.operational_message import OperationalMessageRepository
from app.repositories.shipment import ShipmentRepository
from app.repositories.vehicle import VehicleRepository

__all__ = [
    "AppointmentRepository",
    "AppointmentSlotRepository",
    "CarrierRepository",
    "ChatMessageRepository",
    "ChatThreadRepository",
    "ContactRepository",
    "DockRepository",
    "DriverExceptionRepository",
    "DriverRepository",
    "ETAUpdateRepository",
    "FacilityCheckinRepository",
    "FacilityRepository",
    "FacilityRuleRepository",
    "OperationalMessageRepository",
    "ShipmentRepository",
    "VehicleRepository",
]
