"""Stable rule identifiers and metadata for the feasibility engine."""

from dataclasses import dataclass

from app.engines.feasibility.models import RuleCategory, RuleSeverity


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    name: str
    category: RuleCategory
    severity: RuleSeverity
    order: int


# Deterministic evaluation order — lower order runs first.
RULE_DEFINITIONS: tuple[RuleDefinition, ...] = (
    RuleDefinition("SHIP-001", "Shipment active", RuleCategory.SHIPMENT, RuleSeverity.BLOCKING, 10),
    RuleDefinition(
        "SHIP-002",
        "Shipment operational status",
        RuleCategory.SHIPMENT,
        RuleSeverity.BLOCKING,
        20,
    ),
    RuleDefinition(
        "SHIP-003",
        "Destination facility assigned",
        RuleCategory.SHIPMENT,
        RuleSeverity.BLOCKING,
        30,
    ),
    RuleDefinition("CARR-001", "Carrier active", RuleCategory.CARRIER, RuleSeverity.BLOCKING, 40),
    RuleDefinition("DRIV-001", "Driver active", RuleCategory.DRIVER, RuleSeverity.BLOCKING, 50),
    RuleDefinition("VEHI-001", "Vehicle active", RuleCategory.VEHICLE, RuleSeverity.BLOCKING, 60),
    RuleDefinition(
        "FACI-001",
        "Destination facility active",
        RuleCategory.FACILITY,
        RuleSeverity.BLOCKING,
        70,
    ),
    RuleDefinition(
        "APPT-001",
        "Appointment or slot context",
        RuleCategory.APPOINTMENT,
        RuleSeverity.BLOCKING,
        80,
    ),
    RuleDefinition(
        "APPT-002",
        "Appointment facility alignment",
        RuleCategory.APPOINTMENT,
        RuleSeverity.BLOCKING,
        90,
    ),
    RuleDefinition("SLOT-001", "Slot exists", RuleCategory.SLOT, RuleSeverity.BLOCKING, 100),
    RuleDefinition(
        "SLOT-002",
        "Slot facility alignment",
        RuleCategory.SLOT,
        RuleSeverity.BLOCKING,
        110,
    ),
    RuleDefinition("SLOT-003", "Slot status open", RuleCategory.SLOT, RuleSeverity.BLOCKING, 120),
    RuleDefinition("SLOT-004", "Slot capacity", RuleCategory.SLOT, RuleSeverity.BLOCKING, 130),
    RuleDefinition("DOCK-001", "Dock exists", RuleCategory.DOCK, RuleSeverity.BLOCKING, 140),
    RuleDefinition(
        "DOCK-002",
        "Dock facility alignment",
        RuleCategory.DOCK,
        RuleSeverity.BLOCKING,
        150,
    ),
    RuleDefinition(
        "DOCK-003",
        "Dock availability",
        RuleCategory.DOCK,
        RuleSeverity.BLOCKING,
        160,
    ),
    RuleDefinition(
        "DOCK-004",
        "Dock weight capacity",
        RuleCategory.DOCK,
        RuleSeverity.BLOCKING,
        170,
    ),
    RuleDefinition(
        "DOCK-005",
        "Reefer dock compatibility",
        RuleCategory.DOCK,
        RuleSeverity.BLOCKING,
        180,
    ),
    RuleDefinition(
        "VEHI-002",
        "Vehicle weight capacity",
        RuleCategory.VEHICLE,
        RuleSeverity.BLOCKING,
        190,
    ),
    RuleDefinition(
        "VEHI-003",
        "Vehicle volume capacity",
        RuleCategory.VEHICLE,
        RuleSeverity.BLOCKING,
        200,
    ),
    RuleDefinition(
        "RULE-001",
        "Max daily appointments",
        RuleCategory.FACILITY_RULE,
        RuleSeverity.BLOCKING,
        210,
    ),
    RuleDefinition(
        "RULE-002",
        "Operating hours",
        RuleCategory.FACILITY_RULE,
        RuleSeverity.BLOCKING,
        220,
    ),
    RuleDefinition(
        "RULE-003",
        "Dock compatibility rule",
        RuleCategory.FACILITY_RULE,
        RuleSeverity.BLOCKING,
        230,
    ),
    RuleDefinition(
        "ETA-001",
        "ETA within slot window",
        RuleCategory.ETA,
        RuleSeverity.BLOCKING,
        240,
    ),
    RuleDefinition(
        "ETA-002",
        "ETA within operating hours",
        RuleCategory.ETA,
        RuleSeverity.WARNING,
        250,
    ),
    RuleDefinition(
        "EXCP-001",
        "No active driver exceptions",
        RuleCategory.EXCEPTION,
        RuleSeverity.BLOCKING,
        260,
    ),
)

RULE_DEFINITION_BY_ID: dict[str, RuleDefinition] = {
    definition.rule_id: definition for definition in RULE_DEFINITIONS
}

# Appointment statuses that consume slot capacity and daily appointment limits.
CAPACITY_CONSUMING_APPOINTMENT_STATUSES: frozenset[str] = frozenset(
    {"confirmed", "held"}
)

# Driver exception statuses treated as active operational blockers.
ACTIVE_EXCEPTION_STATUSES: frozenset[str] = frozenset({"open", "acknowledged"})

# Terminal shipment statuses that cannot proceed.
TERMINAL_SHIPMENT_STATUSES: frozenset[str] = frozenset({"cancelled", "delivered"})

# Vehicle types indicating temperature-controlled transport (convention).
REEFER_VEHICLE_TYPE_MARKERS: frozenset[str] = frozenset({"reefer"})
