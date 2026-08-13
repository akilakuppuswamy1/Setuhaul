"""Structured facts and results for facility-level schedule ranking. No database access."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class AssignmentKind(str, Enum):
    PROTECTED = "protected"
    PROPOSED = "proposed"


class UnassignedReason(str, Enum):
    NO_FEASIBLE_SLOT = "no_feasible_slot"
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    BLOCKING_EXCEPTION = "blocking_exception"
    MISSING_ETA = "missing_eta"
    NOT_EVALUABLE = "not_evaluable"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True)
class SlotSnapshot:
    slot_id: UUID
    start_time: datetime
    end_time: datetime
    capacity: int
    remaining_capacity: int
    status: str


@dataclass(frozen=True)
class DockSnapshot:
    dock_id: UUID
    name: str
    status: str


@dataclass(frozen=True)
class ShipmentSnapshot:
    shipment_id: UUID
    shipment_number: str
    status: str
    latest_eta: datetime | None
    gate_in_at: datetime | None
    has_active_exception: bool
    missing_eta: bool
    protected_slot_id: UUID | None
    protected_dock_id: UUID | None
    protected_status: str | None


@dataclass(frozen=True)
class FeasibleOption:
    shipment_id: UUID
    slot_id: UUID
    dock_id: UUID | None
    feasible: bool
    outcome: str
    lateness_seconds: int | None
    early_wait_seconds: int | None
    alignment_seconds: int | None
    yard_wait_seconds: int | None
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SchedulingContext:
    facility_id: UUID
    evaluated_at: datetime
    scheduling_start: datetime | None
    scheduling_end: datetime | None
    shipments: tuple[ShipmentSnapshot, ...]
    slots: tuple[SlotSnapshot, ...]
    docks: tuple[DockSnapshot, ...]
    options: tuple[FeasibleOption, ...]


@dataclass(frozen=True)
class ProposedAssignment:
    shipment_id: UUID
    shipment_number: str
    slot_id: UUID | None
    dock_id: UUID | None
    rank: int
    score: int | None
    kind: AssignmentKind
    lateness_seconds: int | None
    early_wait_seconds: int | None
    alignment_seconds: int | None
    yard_wait_seconds: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class UnassignedShipment:
    shipment_id: UUID
    shipment_number: str
    reason: UnassignedReason
    detail: str


@dataclass(frozen=True)
class SchedulingResult:
    facility_id: UUID
    evaluated_at: datetime
    assignments: tuple[ProposedAssignment, ...]
    unassigned: tuple[UnassignedShipment, ...]
    warnings: tuple[str, ...]
    ranking_policy: str
