import enum


class EntityStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ShipmentStatus(str, enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    AT_FACILITY = "at_facility"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ETASource(str, enum.Enum):
    DRIVER = "driver"
    CARRIER = "carrier"
    DISPATCH = "dispatch"
    SYSTEM = "system"
    FACILITY = "facility"


class ExceptionType(str, enum.Enum):
    TRAFFIC = "traffic"
    BREAKDOWN = "breakdown"
    REPAIR = "repair"
    DELAY = "delay"
    OTHER = "other"


class ExceptionStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class CheckinType(str, enum.Enum):
    GATE_IN = "gate_in"
    YARD_ARRIVAL = "yard_arrival"
    DOCK_ARRIVAL = "dock_arrival"
    UNLOADING_COMPLETE = "unloading_complete"


class DockStatus(str, enum.Enum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    MAINTENANCE = "maintenance"
    INACTIVE = "inactive"


class AppointmentSlotStatus(str, enum.Enum):
    OPEN = "open"
    FULL = "full"
    CLOSED = "closed"


class AppointmentStatus(str, enum.Enum):
    REQUESTED = "requested"
    HELD = "held"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ChatThreadStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class SenderType(str, enum.Enum):
    DRIVER = "driver"
    DISPATCHER = "dispatcher"
    FACILITY = "facility"
    SYSTEM = "system"
    CARRIER = "carrier"


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class ContactType(str, enum.Enum):
    FACILITY = "facility"
    CARRIER = "carrier"
    CUSTOMER = "customer"
    DRIVER = "driver"
    OTHER = "other"


class MessageChannel(str, enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PHONE = "phone"


class OperationalMessageStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERED = "delivered"
