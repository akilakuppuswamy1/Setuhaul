"""Individual deterministic rule evaluators."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.engines.feasibility.models import (
    FeasibilityContext,
    RuleCategory,
    RuleResult,
    RuleSeverity,
)
from app.engines.feasibility.rules import (
    ACTIVE_EXCEPTION_STATUSES,
    REEFER_VEHICLE_TYPE_MARKERS,
    RULE_DEFINITION_BY_ID,
    TERMINAL_SHIPMENT_STATUSES,
)


def _definition(rule_id: str):
    return RULE_DEFINITION_BY_ID[rule_id]


def _result(
    rule_id: str,
    *,
    passed: bool,
    reason: str,
    facts: dict[str, object] | None = None,
    evaluable: bool = True,
    severity: RuleSeverity | None = None,
) -> RuleResult:
    definition = _definition(rule_id)
    return RuleResult(
        rule_id=definition.rule_id,
        rule_name=definition.name,
        category=definition.category,
        passed=passed,
        severity=severity or definition.severity,
        reason=reason,
        facts=facts or {},
        evaluable=evaluable,
    )


def _is_reefer_vehicle(vehicle_type: str) -> bool:
    normalized = vehicle_type.lower()
    return any(marker in normalized for marker in REEFER_VEHICLE_TYPE_MARKERS)


def _to_local(dt: datetime, timezone_name: str) -> datetime | None:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    return dt.astimezone(tz)


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("UTC"))


def _parse_hhmm(value: object) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        hour_str, minute_str = value.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return time(hour, minute)
    except (ValueError, AttributeError):
        return None


def _safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def evaluate_ship_001(ctx: FeasibilityContext) -> RuleResult:
    passed = ctx.shipment.is_active
    return _result(
        "SHIP-001",
        passed=passed,
        reason="Shipment is active" if passed else "Shipment is not active",
        facts={"is_active": ctx.shipment.is_active},
    )


def evaluate_ship_002(ctx: FeasibilityContext) -> RuleResult:
    status = ctx.shipment.status
    passed = status not in TERMINAL_SHIPMENT_STATUSES
    return _result(
        "SHIP-002",
        passed=passed,
        reason=(
            f"Shipment status '{status}' is operational"
            if passed
            else f"Shipment status '{status}' is terminal"
        ),
        facts={"status": status},
    )


def evaluate_ship_003(ctx: FeasibilityContext) -> RuleResult:
    facility_id = ctx.shipment.destination_facility_id
    passed = facility_id is not None
    return _result(
        "SHIP-003",
        passed=passed,
        reason=(
            "Destination facility is assigned"
            if passed
            else "Destination facility is not assigned"
        ),
        facts={"destination_facility_id": str(facility_id) if facility_id else None},
    )


def evaluate_carr_001(ctx: FeasibilityContext) -> RuleResult:
    if ctx.carrier is None:
        return _result(
            "CARR-001",
            passed=False,
            reason="Carrier record is missing",
            facts={},
        )
    passed = ctx.carrier.status == "active"
    return _result(
        "CARR-001",
        passed=passed,
        reason=(
            f"Carrier '{ctx.carrier.name}' is active"
            if passed
            else f"Carrier '{ctx.carrier.name}' is inactive"
        ),
        facts={"carrier_id": str(ctx.carrier.entity_id), "status": ctx.carrier.status},
    )


def evaluate_driv_001(ctx: FeasibilityContext) -> RuleResult:
    if ctx.shipment.driver_id is None:
        return _result(
            "DRIV-001",
            passed=True,
            reason="No driver assigned; driver check not required",
            facts={"driver_id": None},
        )
    if ctx.driver is None:
        return _result(
            "DRIV-001",
            passed=False,
            reason="Assigned driver record is missing",
            facts={"driver_id": str(ctx.shipment.driver_id)},
        )
    passed = ctx.driver.status == "active"
    return _result(
        "DRIV-001",
        passed=passed,
        reason=(
            f"Driver '{ctx.driver.name}' is active"
            if passed
            else f"Driver '{ctx.driver.name}' is inactive"
        ),
        facts={"driver_id": str(ctx.driver.entity_id), "status": ctx.driver.status},
    )


def evaluate_vehi_001(ctx: FeasibilityContext) -> RuleResult:
    if ctx.shipment.vehicle_id is None:
        return _result(
            "VEHI-001",
            passed=True,
            reason="No vehicle assigned; vehicle check not required",
            facts={"vehicle_id": None},
        )
    if ctx.vehicle is None:
        return _result(
            "VEHI-001",
            passed=False,
            reason="Assigned vehicle record is missing",
            facts={"vehicle_id": str(ctx.shipment.vehicle_id)},
        )
    passed = ctx.vehicle.status == "active"
    return _result(
        "VEHI-001",
        passed=passed,
        reason=(
            f"Vehicle type '{ctx.vehicle.vehicle_type}' is active"
            if passed
            else f"Vehicle type '{ctx.vehicle.vehicle_type}' is inactive"
        ),
        facts={"vehicle_id": str(ctx.vehicle.vehicle_id), "status": ctx.vehicle.status},
    )


def evaluate_faci_001(ctx: FeasibilityContext) -> RuleResult:
    if ctx.facility is None:
        return _result(
            "FACI-001",
            passed=False,
            reason="Destination facility record is missing",
            facts={},
        )
    passed = ctx.facility.status == "active"
    return _result(
        "FACI-001",
        passed=passed,
        reason=(
            f"Facility '{ctx.facility.code}' is active"
            if passed
            else f"Facility '{ctx.facility.code}' is inactive"
        ),
        facts={"facility_id": str(ctx.facility.facility_id), "status": ctx.facility.status},
    )


def evaluate_appt_001(ctx: FeasibilityContext) -> RuleResult:
    has_context = ctx.appointment is not None or ctx.slot is not None
    return _result(
        "APPT-001",
        passed=has_context,
        reason=(
            "Appointment or slot context is available"
            if has_context
            else "No appointment or slot context available for evaluation"
        ),
        facts={
            "appointment_id": str(ctx.appointment.appointment_id) if ctx.appointment else None,
            "slot_id": str(ctx.slot.slot_id) if ctx.slot else None,
        },
    )


def evaluate_appt_002(ctx: FeasibilityContext) -> RuleResult:
    if ctx.appointment is None or ctx.facility is None:
        return _result(
            "APPT-002",
            passed=True,
            reason="No appointment to validate against facility",
            facts={},
            evaluable=ctx.appointment is not None,
        )
    passed = ctx.appointment.facility_id == ctx.facility.facility_id
    return _result(
        "APPT-002",
        passed=passed,
        reason=(
            "Appointment facility matches destination facility"
            if passed
            else "Appointment facility does not match destination facility"
        ),
        facts={
            "appointment_facility_id": str(ctx.appointment.facility_id),
            "destination_facility_id": str(ctx.facility.facility_id),
        },
    )


def evaluate_slot_001(ctx: FeasibilityContext) -> RuleResult:
    if ctx.slot is None:
        return _result(
            "SLOT-001",
            passed=False,
            reason="No appointment slot available for evaluation",
            facts={},
            evaluable=False,
        )
    return _result(
        "SLOT-001",
        passed=True,
        reason="Appointment slot is present",
        facts={"slot_id": str(ctx.slot.slot_id)},
    )


def evaluate_slot_002(ctx: FeasibilityContext) -> RuleResult:
    if ctx.slot is None or ctx.facility is None:
        return _result(
            "SLOT-002",
            passed=True,
            reason="No slot to validate against facility",
            facts={},
            evaluable=ctx.slot is not None,
        )
    passed = ctx.slot.facility_id == ctx.facility.facility_id
    return _result(
        "SLOT-002",
        passed=passed,
        reason=(
            "Slot belongs to destination facility"
            if passed
            else "Slot does not belong to destination facility"
        ),
        facts={
            "slot_facility_id": str(ctx.slot.facility_id),
            "destination_facility_id": str(ctx.facility.facility_id),
        },
    )


def evaluate_slot_003(ctx: FeasibilityContext) -> RuleResult:
    if ctx.slot is None:
        return _result(
            "SLOT-003",
            passed=True,
            reason="No slot to validate status",
            facts={},
            evaluable=False,
        )
    passed = ctx.slot.status == "open"
    return _result(
        "SLOT-003",
        passed=passed,
        reason=(
            "Slot status is open"
            if passed
            else f"Slot status is '{ctx.slot.status}', expected 'open'"
        ),
        facts={"slot_status": ctx.slot.status},
    )


def evaluate_slot_004(ctx: FeasibilityContext) -> RuleResult:
    if ctx.slot is None:
        return _result(
            "SLOT-004",
            passed=True,
            reason="No slot to validate capacity",
            facts={},
            evaluable=False,
        )
    if ctx.slot.includes_current_shipment:
        passed = ctx.slot.booked_count <= ctx.slot.capacity
        comparison = "<="
    else:
        passed = ctx.slot.booked_count < ctx.slot.capacity
        comparison = "<"
    return _result(
        "SLOT-004",
        passed=passed,
        reason=(
            f"Slot has capacity ({ctx.slot.booked_count}/{ctx.slot.capacity} booked)"
            if passed
            else f"Slot is at capacity ({ctx.slot.booked_count}/{ctx.slot.capacity} booked)"
        ),
        facts={
            "booked_count": ctx.slot.booked_count,
            "capacity": ctx.slot.capacity,
            "includes_current_shipment": ctx.slot.includes_current_shipment,
            "comparison": comparison,
        },
    )


def evaluate_dock_001(ctx: FeasibilityContext) -> RuleResult:
    dock_required = (
        ctx.appointment is not None and ctx.appointment.dock_id is not None
    ) or ctx.dock is not None
    if not dock_required:
        return _result(
            "DOCK-001",
            passed=True,
            reason="No dock assignment to validate",
            facts={"dock_id": None},
        )
    if ctx.dock is None:
        dock_id = ctx.appointment.dock_id if ctx.appointment else None
        return _result(
            "DOCK-001",
            passed=False,
            reason="Referenced dock record is missing",
            facts={"dock_id": str(dock_id) if dock_id else None},
        )
    return _result(
        "DOCK-001",
        passed=True,
        reason="Dock record is present",
        facts={"dock_id": str(ctx.dock.dock_id)},
    )


def evaluate_dock_002(ctx: FeasibilityContext) -> RuleResult:
    if ctx.dock is None or ctx.facility is None:
        return _result(
            "DOCK-002",
            passed=True,
            reason="No dock to validate against facility",
            facts={},
            evaluable=ctx.dock is not None,
        )
    passed = ctx.dock.facility_id == ctx.facility.facility_id
    return _result(
        "DOCK-002",
        passed=passed,
        reason=(
            "Dock belongs to destination facility"
            if passed
            else "Dock does not belong to destination facility"
        ),
        facts={
            "dock_facility_id": str(ctx.dock.facility_id),
            "destination_facility_id": str(ctx.facility.facility_id),
        },
    )


def evaluate_dock_003(ctx: FeasibilityContext) -> RuleResult:
    if ctx.dock is None:
        return _result(
            "DOCK-003",
            passed=True,
            reason="No dock to validate availability",
            facts={},
            evaluable=False,
        )
    passed = ctx.dock.status == "available"
    return _result(
        "DOCK-003",
        passed=passed,
        reason=(
            f"Dock '{ctx.dock.name}' is available"
            if passed
            else f"Dock '{ctx.dock.name}' status is '{ctx.dock.status}'"
        ),
        facts={"dock_status": ctx.dock.status},
    )


def evaluate_dock_004(ctx: FeasibilityContext) -> RuleResult:
    if ctx.dock is None:
        return _result(
            "DOCK-004",
            passed=True,
            reason="No dock to validate weight capacity",
            facts={},
            evaluable=False,
        )
    if ctx.shipment.weight_kg is None or ctx.dock.max_weight_kg is None:
        return _result(
            "DOCK-004",
            passed=True,
            reason="Insufficient data to evaluate dock weight capacity",
            facts={
                "shipment_weight_kg": (
                    str(ctx.shipment.weight_kg) if ctx.shipment.weight_kg is not None else None
                ),
                "dock_max_weight_kg": (
                    str(ctx.dock.max_weight_kg) if ctx.dock.max_weight_kg is not None else None
                ),
            },
            evaluable=False,
        )
    passed = ctx.shipment.weight_kg <= ctx.dock.max_weight_kg
    return _result(
        "DOCK-004",
        passed=passed,
        reason=(
            "Shipment weight is within dock capacity"
            if passed
            else "Shipment weight exceeds dock capacity"
        ),
        facts={
            "shipment_weight_kg": str(ctx.shipment.weight_kg),
            "dock_max_weight_kg": str(ctx.dock.max_weight_kg),
        },
    )


def evaluate_dock_005(ctx: FeasibilityContext) -> RuleResult:
    if ctx.dock is None or ctx.vehicle is None:
        return _result(
            "DOCK-005",
            passed=True,
            reason="No dock/vehicle pair to validate reefer compatibility",
            facts={},
            evaluable=ctx.dock is not None and ctx.vehicle is not None,
        )
    if not _is_reefer_vehicle(ctx.vehicle.vehicle_type):
        return _result(
            "DOCK-005",
            passed=True,
            reason="Vehicle is not temperature-controlled; reefer dock not required",
            facts={"vehicle_type": ctx.vehicle.vehicle_type},
        )
    passed = ctx.dock.temperature_controlled
    return _result(
        "DOCK-005",
        passed=passed,
        reason=(
            "Reefer vehicle assigned to temperature-controlled dock"
            if passed
            else "Reefer vehicle requires a temperature-controlled dock"
        ),
        facts={
            "vehicle_type": ctx.vehicle.vehicle_type,
            "dock_temperature_controlled": ctx.dock.temperature_controlled,
        },
    )


def evaluate_vehi_002(ctx: FeasibilityContext) -> RuleResult:
    if ctx.vehicle is None:
        return _result(
            "VEHI-002",
            passed=True,
            reason="No vehicle to validate weight capacity",
            facts={},
            evaluable=False,
        )
    if ctx.shipment.weight_kg is None or ctx.vehicle.max_weight_kg is None:
        return _result(
            "VEHI-002",
            passed=True,
            reason="Insufficient data to evaluate vehicle weight capacity",
            facts={},
            evaluable=False,
        )
    passed = ctx.shipment.weight_kg <= ctx.vehicle.max_weight_kg
    return _result(
        "VEHI-002",
        passed=passed,
        reason=(
            "Shipment weight is within vehicle capacity"
            if passed
            else "Shipment weight exceeds vehicle capacity"
        ),
        facts={
            "shipment_weight_kg": str(ctx.shipment.weight_kg),
            "vehicle_max_weight_kg": str(ctx.vehicle.max_weight_kg),
        },
    )


def evaluate_vehi_003(ctx: FeasibilityContext) -> RuleResult:
    if ctx.vehicle is None:
        return _result(
            "VEHI-003",
            passed=True,
            reason="No vehicle to validate volume capacity",
            facts={},
            evaluable=False,
        )
    if ctx.shipment.volume_cbm is None or ctx.vehicle.max_volume_cbm is None:
        return _result(
            "VEHI-003",
            passed=True,
            reason="Insufficient data to evaluate vehicle volume capacity",
            facts={},
            evaluable=False,
        )
    passed = ctx.shipment.volume_cbm <= ctx.vehicle.max_volume_cbm
    return _result(
        "VEHI-003",
        passed=passed,
        reason=(
            "Shipment volume is within vehicle capacity"
            if passed
            else "Shipment volume exceeds vehicle capacity"
        ),
        facts={
            "shipment_volume_cbm": str(ctx.shipment.volume_cbm),
            "vehicle_max_volume_cbm": str(ctx.vehicle.max_volume_cbm),
        },
    )


def evaluate_rule_001(ctx: FeasibilityContext) -> list[RuleResult]:
    results: list[RuleResult] = []
    for index, rule in enumerate(ctx.facility_rules):
        if rule.rule_type != "max_daily_appointments":
            continue
        limit_value = rule.rule_value.get("limit")
        if limit_value is None:
            results.append(
                _result(
                    "RULE-001",
                    passed=False,
                    reason="max_daily_appointments rule is missing 'limit' value",
                    facts={"rule_id": str(rule.rule_id), "rule_value": rule.rule_value},
                )
            )
            continue
        limit = _safe_int(limit_value)
        if limit is None:
            results.append(
                _result(
                    "RULE-001",
                    passed=False,
                    reason="max_daily_appointments rule has invalid 'limit' value",
                    facts={"rule_id": str(rule.rule_id), "rule_value": rule.rule_value},
                )
            )
            continue
        if ctx.daily_appointment_count is None:
            results.append(
                _result(
                    "RULE-001",
                    passed=False,
                    reason="Daily appointment count unavailable for evaluation",
                    facts={"rule_id": str(rule.rule_id)},
                    evaluable=False,
                )
            )
            continue
        passed = ctx.daily_appointment_count < limit
        results.append(
            _result(
                "RULE-001",
                passed=passed,
                reason=(
                    f"Daily appointments ({ctx.daily_appointment_count}) below limit ({limit})"
                    if passed
                    else f"Daily appointments ({ctx.daily_appointment_count}) at or above limit ({limit})"
                ),
                facts={
                    "rule_id": str(rule.rule_id),
                    "rule_index": index,
                    "daily_appointment_count": ctx.daily_appointment_count,
                    "limit": limit,
                },
            )
        )
    if not results:
        return [
            _result(
                "RULE-001",
                passed=True,
                reason="No max_daily_appointments rule configured",
                facts={},
                evaluable=False,
            )
        ]
    return results


def evaluate_rule_002(ctx: FeasibilityContext) -> list[RuleResult]:
    results: list[RuleResult] = []
    reference_time = _reference_time_for_hours(ctx)
    if reference_time is None:
        return [
            _result(
                "RULE-002",
                passed=True,
                reason="No slot or ETA available to evaluate operating hours",
                facts={},
                evaluable=False,
            )
        ]
    if ctx.facility is None:
        return [
            _result(
                "RULE-002",
                passed=False,
                reason="Facility required to evaluate operating hours",
                facts={},
            )
        ]

    for index, rule in enumerate(ctx.facility_rules):
        if rule.rule_type != "operating_hours":
            continue
        open_value = rule.rule_value.get("open")
        close_value = rule.rule_value.get("close")
        if not open_value or not close_value:
            results.append(
                _result(
                    "RULE-002",
                    passed=False,
                    reason="operating_hours rule is missing open/close values",
                    facts={"rule_id": str(rule.rule_id), "rule_value": rule.rule_value},
                )
            )
            continue
        local_dt = _to_local(reference_time, ctx.facility.timezone)
        if local_dt is None:
            results.append(
                _result(
                    "RULE-002",
                    passed=False,
                    reason=f"Facility timezone '{ctx.facility.timezone}' is invalid",
                    facts={"rule_id": str(rule.rule_id), "timezone": ctx.facility.timezone},
                )
            )
            continue
        open_time = _parse_hhmm(open_value)
        close_time = _parse_hhmm(close_value)
        if open_time is None or close_time is None:
            results.append(
                _result(
                    "RULE-002",
                    passed=False,
                    reason="operating_hours rule has invalid open/close time format",
                    facts={"rule_id": str(rule.rule_id), "open": open_value, "close": close_value},
                )
            )
            continue
        local_time = local_dt.timetz().replace(tzinfo=None)
        passed = open_time <= local_time < close_time
        results.append(
            _result(
                "RULE-002",
                passed=passed,
                reason=(
                    f"Reference time {local_dt.isoformat()} is within operating hours "
                    f"({open_value}-{close_value} {ctx.facility.timezone})"
                    if passed
                    else f"Reference time {local_dt.isoformat()} is outside operating hours "
                    f"({open_value}-{close_value} {ctx.facility.timezone})"
                ),
                facts={
                    "rule_id": str(rule.rule_id),
                    "rule_index": index,
                    "reference_time_utc": reference_time.isoformat(),
                    "local_time": local_dt.isoformat(),
                    "open": open_value,
                    "close": close_value,
                    "timezone": ctx.facility.timezone,
                },
            )
        )
    if not results:
        return [
            _result(
                "RULE-002",
                passed=True,
                reason="No operating_hours rule configured",
                facts={},
                evaluable=False,
            )
        ]
    return results


def evaluate_rule_003(ctx: FeasibilityContext) -> list[RuleResult]:
    results: list[RuleResult] = []
    if ctx.vehicle is None:
        return [
            _result(
                "RULE-003",
                passed=True,
                reason="No vehicle to evaluate dock compatibility rule",
                facts={},
                evaluable=False,
            )
        ]

    for index, rule in enumerate(ctx.facility_rules):
        if rule.rule_type != "dock_compatibility":
            continue
        allowed_types = rule.rule_value.get("allowed_vehicle_types")
        max_pallets = rule.rule_value.get("max_pallets")
        type_ok = True
        pallet_ok = True
        reasons: list[str] = []
        if allowed_types is not None:
            if not isinstance(allowed_types, list):
                type_ok = False
                reasons.append("allowed_vehicle_types must be a list")
            else:
                type_ok = ctx.vehicle.vehicle_type in allowed_types
                if not type_ok:
                    reasons.append(
                        f"Vehicle type '{ctx.vehicle.vehicle_type}' not in allowed types"
                    )
        if max_pallets is not None and ctx.shipment.pallet_count is not None:
            parsed_max = _safe_int(max_pallets)
            if parsed_max is None:
                pallet_ok = False
                reasons.append("max_pallets has invalid numeric value")
            else:
                pallet_ok = ctx.shipment.pallet_count <= parsed_max
                if not pallet_ok:
                    reasons.append(
                        f"Pallet count {ctx.shipment.pallet_count} exceeds max {parsed_max}"
                    )
        passed = type_ok and pallet_ok
        results.append(
            _result(
                "RULE-003",
                passed=passed,
                reason="; ".join(reasons) if reasons else "Dock compatibility rule satisfied",
                facts={
                    "rule_id": str(rule.rule_id),
                    "rule_index": index,
                    "vehicle_type": ctx.vehicle.vehicle_type,
                    "allowed_vehicle_types": allowed_types,
                    "pallet_count": ctx.shipment.pallet_count,
                    "max_pallets": max_pallets,
                },
            )
        )
    if not results:
        return [
            _result(
                "RULE-003",
                passed=True,
                reason="No dock_compatibility rule configured",
                facts={},
                evaluable=False,
            )
        ]
    return results


def _reference_time_for_hours(ctx: FeasibilityContext) -> datetime | None:
    if ctx.slot is not None:
        return ctx.slot.start_time
    if ctx.latest_eta is not None:
        return ctx.latest_eta
    return None


def evaluate_eta_001(ctx: FeasibilityContext) -> RuleResult:
    if ctx.slot is None:
        return _result(
            "ETA-001",
            passed=True,
            reason="No slot to compare ETA against",
            facts={},
            evaluable=False,
        )
    if ctx.latest_eta is None:
        return _result(
            "ETA-001",
            passed=False,
            reason="Latest ETA is not available; cannot verify slot window alignment",
            facts={"slot_start": ctx.slot.start_time.isoformat(), "slot_end": ctx.slot.end_time.isoformat()},
            evaluable=False,
        )
    eta = _utc(ctx.latest_eta)
    start = _utc(ctx.slot.start_time)
    end = _utc(ctx.slot.end_time)
    # Waiting policy (no unload duration in schema): early arrival may wait;
    # arrival during the window is feasible; arrival after slot end is not.
    if eta < start:
        relation = "before_window"
        passed = True
        reason = "Latest ETA is before the slot start; driver may wait"
    elif eta <= end:
        relation = "during_window"
        passed = True
        reason = "Latest ETA falls within appointment slot window"
    else:
        relation = "after_window"
        passed = False
        reason = "Latest ETA is after the appointment slot window"
    return _result(
        "ETA-001",
        passed=passed,
        reason=reason,
        facts={
            "latest_eta": ctx.latest_eta.isoformat(),
            "slot_start": ctx.slot.start_time.isoformat(),
            "slot_end": ctx.slot.end_time.isoformat(),
            "arrival_relation": relation,
        },
    )


def evaluate_eta_002(ctx: FeasibilityContext) -> RuleResult:
    if ctx.latest_eta is None:
        return _result(
            "ETA-002",
            passed=True,
            reason="No ETA available for operating hours warning",
            facts={},
            evaluable=False,
            severity=RuleSeverity.WARNING,
        )
    operating_rules = [rule for rule in ctx.facility_rules if rule.rule_type == "operating_hours"]
    if not operating_rules or ctx.facility is None:
        return _result(
            "ETA-002",
            passed=True,
            reason="No operating hours rule for ETA warning",
            facts={},
            evaluable=False,
            severity=RuleSeverity.WARNING,
        )
    rule = operating_rules[0]
    open_value = rule.rule_value.get("open")
    close_value = rule.rule_value.get("close")
    if not open_value or not close_value:
        return _result(
            "ETA-002",
            passed=True,
            reason="Operating hours rule incomplete; ETA warning skipped",
            facts={},
            evaluable=False,
            severity=RuleSeverity.WARNING,
        )
    local_dt = _to_local(ctx.latest_eta, ctx.facility.timezone)
    if local_dt is None:
        return _result(
            "ETA-002",
            passed=True,
            reason="Facility timezone invalid; ETA warning skipped",
            facts={"timezone": ctx.facility.timezone},
            evaluable=False,
            severity=RuleSeverity.WARNING,
        )
    open_time = _parse_hhmm(open_value)
    close_time = _parse_hhmm(close_value)
    if open_time is None or close_time is None:
        return _result(
            "ETA-002",
            passed=True,
            reason="Operating hours rule incomplete; ETA warning skipped",
            facts={},
            evaluable=False,
            severity=RuleSeverity.WARNING,
        )
    local_time = local_dt.timetz().replace(tzinfo=None)
    passed = open_time <= local_time < close_time
    return _result(
        "ETA-002",
        passed=passed,
        reason=(
            "Latest ETA is within operating hours"
            if passed
            else "Latest ETA is outside operating hours (warning)"
        ),
        facts={
            "latest_eta": ctx.latest_eta.isoformat(),
            "local_time": local_dt.isoformat(),
            "open": open_value,
            "close": close_value,
        },
        severity=RuleSeverity.WARNING,
    )


def evaluate_excp_001(ctx: FeasibilityContext) -> RuleResult:
    active = [
        exc
        for exc in ctx.active_exceptions
        if exc.status in ACTIVE_EXCEPTION_STATUSES
    ]
    passed = len(active) == 0
    return _result(
        "EXCP-001",
        passed=passed,
        reason=(
            "No active driver exceptions"
            if passed
            else f"{len(active)} active driver exception(s) present"
        ),
        facts={
            "active_exception_count": len(active),
            "active_exception_ids": [str(exc.exception_id) for exc in active],
        },
    )


RULE_EVALUATORS: tuple[tuple[str, object], ...] = (
    ("SHIP-001", evaluate_ship_001),
    ("SHIP-002", evaluate_ship_002),
    ("SHIP-003", evaluate_ship_003),
    ("CARR-001", evaluate_carr_001),
    ("DRIV-001", evaluate_driv_001),
    ("VEHI-001", evaluate_vehi_001),
    ("FACI-001", evaluate_faci_001),
    ("APPT-001", evaluate_appt_001),
    ("APPT-002", evaluate_appt_002),
    ("SLOT-001", evaluate_slot_001),
    ("SLOT-002", evaluate_slot_002),
    ("SLOT-003", evaluate_slot_003),
    ("SLOT-004", evaluate_slot_004),
    ("DOCK-001", evaluate_dock_001),
    ("DOCK-002", evaluate_dock_002),
    ("DOCK-003", evaluate_dock_003),
    ("DOCK-004", evaluate_dock_004),
    ("DOCK-005", evaluate_dock_005),
    ("VEHI-002", evaluate_vehi_002),
    ("VEHI-003", evaluate_vehi_003),
    ("RULE-001", evaluate_rule_001),
    ("RULE-002", evaluate_rule_002),
    ("RULE-003", evaluate_rule_003),
    ("ETA-001", evaluate_eta_001),
    ("ETA-002", evaluate_eta_002),
    ("EXCP-001", evaluate_excp_001),
)
