"""Domain fact and result models for deterministic feasibility evaluation."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


class FeasibilityOutcome(str, Enum):
    FEASIBLE = "feasible"
    NOT_FEASIBLE = "not_feasible"
    NOT_EVALUABLE = "not_evaluable"


class RuleSeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"


class RuleCategory(str, Enum):
    SHIPMENT = "shipment"
    FACILITY = "facility"
    CARRIER = "carrier"
    DRIVER = "driver"
    VEHICLE = "vehicle"
    APPOINTMENT = "appointment"
    SLOT = "slot"
    DOCK = "dock"
    FACILITY_RULE = "facility_rule"
    ETA = "eta"
    EXCEPTION = "exception"


@dataclass(frozen=True)
class ShipmentFacts:
    shipment_id: UUID
    shipment_number: str
    is_active: bool
    status: str
    destination_facility_id: UUID | None
    carrier_id: UUID
    driver_id: UUID | None
    vehicle_id: UUID | None
    weight_kg: Decimal | None
    volume_cbm: Decimal | None
    pallet_count: int | None
    scheduled_delivery_at: datetime | None


@dataclass(frozen=True)
class EntityStatusFacts:
    entity_id: UUID
    name: str
    status: str


@dataclass(frozen=True)
class VehicleFacts:
    vehicle_id: UUID
    vehicle_type: str
    status: str
    max_weight_kg: Decimal | None
    max_volume_cbm: Decimal | None


@dataclass(frozen=True)
class FacilityFacts:
    facility_id: UUID
    code: str
    status: str
    timezone: str


@dataclass(frozen=True)
class AppointmentFacts:
    appointment_id: UUID
    status: str
    facility_id: UUID
    appointment_slot_id: UUID | None
    dock_id: UUID | None


@dataclass(frozen=True)
class SlotFacts:
    slot_id: UUID
    facility_id: UUID
    start_time: datetime
    end_time: datetime
    capacity: int
    status: str
    booked_count: int
    includes_current_shipment: bool = False


@dataclass(frozen=True)
class DockFacts:
    dock_id: UUID
    facility_id: UUID
    name: str
    status: str
    max_weight_kg: Decimal | None
    temperature_controlled: bool


@dataclass(frozen=True)
class FacilityRuleFacts:
    rule_id: UUID
    rule_type: str
    rule_value: dict
    effective_start: datetime
    effective_end: datetime | None
    is_active: bool


@dataclass(frozen=True)
class DriverExceptionFacts:
    exception_id: UUID
    exception_type: str
    status: str
    description: str | None


@dataclass(frozen=True)
class FeasibilityContext:
    """Explicit operational facts supplied to the feasibility engine."""

    evaluated_at: datetime
    shipment: ShipmentFacts
    carrier: EntityStatusFacts | None
    driver: EntityStatusFacts | None
    vehicle: VehicleFacts | None
    facility: FacilityFacts | None
    appointment: AppointmentFacts | None
    slot: SlotFacts | None
    dock: DockFacts | None
    latest_eta: datetime | None
    active_exceptions: tuple[DriverExceptionFacts, ...]
    facility_rules: tuple[FacilityRuleFacts, ...]
    daily_appointment_count: int | None = None


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    rule_name: str
    category: RuleCategory
    passed: bool
    severity: RuleSeverity
    reason: str
    facts: dict[str, object] = field(default_factory=dict)
    evaluable: bool = True


@dataclass(frozen=True)
class FeasibilityEvaluation:
    outcome: FeasibilityOutcome
    feasible: bool
    evaluated_at: datetime
    shipment_id: UUID
    rule_results: tuple[RuleResult, ...]
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    operational_facts: dict[str, object]
