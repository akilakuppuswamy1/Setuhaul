"""Deterministic ranking helpers. Operate only on structured snapshots."""

from datetime import datetime, timezone
from uuid import UUID

from app.engines.scheduling.models import (
    AssignmentKind,
    DockSnapshot,
    FeasibleOption,
    ProposedAssignment,
    ShipmentSnapshot,
    SlotSnapshot,
    UnassignedReason,
    UnassignedShipment,
)
from app.engines.scheduling.rules import MISSING_METRIC_SENTINEL

_NIL = UUID(int=0)


def option_sort_key(
    option: FeasibleOption,
    slot: SlotSnapshot,
    dock_name: str,
) -> tuple:
    return (
        0 if option.lateness_seconds is not None else 1,
        option.lateness_seconds if option.lateness_seconds is not None else MISSING_METRIC_SENTINEL,
        0 if option.early_wait_seconds is not None else 1,
        option.early_wait_seconds if option.early_wait_seconds is not None else MISSING_METRIC_SENTINEL,
        0 if option.alignment_seconds is not None else 1,
        option.alignment_seconds if option.alignment_seconds is not None else MISSING_METRIC_SENTINEL,
        slot.start_time,
        dock_name,
        str(option.shipment_id),
        str(option.slot_id),
        str(option.dock_id) if option.dock_id is not None else str(_NIL),
    )


def shipment_sort_key(shipment: ShipmentSnapshot, best: FeasibleOption | None) -> tuple:
    arrived = 0 if shipment.gate_in_at is not None else 1
    arrival = shipment.gate_in_at or datetime(9999, 12, 31, tzinfo=timezone.utc)
    if best is None:
        lateness = MISSING_METRIC_SENTINEL
        alignment = MISSING_METRIC_SENTINEL
        eta_known = 1
    else:
        eta_known = 0 if best.lateness_seconds is not None else 1
        lateness = best.lateness_seconds if best.lateness_seconds is not None else MISSING_METRIC_SENTINEL
        alignment = best.alignment_seconds if best.alignment_seconds is not None else MISSING_METRIC_SENTINEL
    return (
        arrived,
        arrival,
        eta_known,
        lateness,
        alignment,
        shipment.shipment_number,
        str(shipment.shipment_id),
    )


def assignment_score(option: FeasibleOption) -> int | None:
    """Explainable 0-100 score from evaluable ETA metrics only. None if ETA is missing."""
    if option.lateness_seconds is None or option.early_wait_seconds is None or option.alignment_seconds is None:
        return None
    lateness_penalty = min(40, option.lateness_seconds // 60)
    wait_penalty = min(30, option.early_wait_seconds // 60)
    alignment_penalty = min(20, option.alignment_seconds // 60)
    return max(0, 100 - lateness_penalty - wait_penalty - alignment_penalty)


def build_reasons(
    *,
    shipment: ShipmentSnapshot,
    option: FeasibleOption | None,
    slot: SlotSnapshot | None,
    kind: AssignmentKind,
    dock: DockSnapshot | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if kind == AssignmentKind.PROTECTED:
        reasons.append("Existing confirmed or held appointment is protected and was not moved.")
        return tuple(reasons)
    if option is None or slot is None:
        return ("No feasible option was selected.",)
    if option.lateness_seconds is None:
        reasons.append("ETA alignment is not evaluable because latest ETA is missing.")
    elif option.lateness_seconds == 0:
        reasons.append("ETA is not after the slot end (no computed lateness).")
    else:
        reasons.append(f"Expected lateness versus slot end is {option.lateness_seconds} seconds.")
    if option.early_wait_seconds is None:
        reasons.append("Early-wait is not evaluable because latest ETA is missing.")
    elif option.early_wait_seconds == 0:
        reasons.append("ETA is not before the slot start (no computed early wait).")
    else:
        reasons.append(f"Expected wait if arriving before the slot start is {option.early_wait_seconds} seconds.")
    if option.alignment_seconds is not None:
        reasons.append(f"ETA-to-slot-start alignment is {option.alignment_seconds} seconds.")
    if option.yard_wait_seconds:
        reasons.append(f"Facility check-in evidence shows {option.yard_wait_seconds} seconds already waiting.")
    if dock is not None:
        reasons.append(f"Compatible dock {dock.name} passed Step 5 feasibility.")
    elif option.dock_id is None:
        reasons.append("No dock was required for this feasible slot evaluation.")
    reasons.append(f"Slot window {slot.start_time.isoformat()} – {slot.end_time.isoformat()}.")
    reasons.append("Shipment priority is not evaluable with the frozen schema.")
    reasons.append("Unloading duration is not evaluable with the frozen schema.")
    return tuple(reasons)


def unassigned_for(shipment: ShipmentSnapshot, options: tuple[FeasibleOption, ...]) -> UnassignedShipment:
    if shipment.has_active_exception:
        return UnassignedShipment(
            shipment_id=shipment.shipment_id,
            shipment_number=shipment.shipment_number,
            reason=UnassignedReason.BLOCKING_EXCEPTION,
            detail="Active driver exception blocked Step 5 feasibility.",
        )
    if shipment.missing_eta:
        return UnassignedShipment(
            shipment_id=shipment.shipment_id,
            shipment_number=shipment.shipment_number,
            reason=UnassignedReason.MISSING_ETA,
            detail="Latest ETA is missing, so slot-window alignment is not evaluable.",
        )
    feasible = [item for item in options if item.shipment_id == shipment.shipment_id and item.feasible]
    if not feasible:
        unevaluable = [
            item
            for item in options
            if item.shipment_id == shipment.shipment_id and item.outcome == "not_evaluable"
        ]
        if unevaluable:
            return UnassignedShipment(
                shipment_id=shipment.shipment_id,
                shipment_number=shipment.shipment_number,
                reason=UnassignedReason.NOT_EVALUABLE,
                detail="Step 5 could not fully evaluate any candidate slot.",
            )
        return UnassignedShipment(
            shipment_id=shipment.shipment_id,
            shipment_number=shipment.shipment_number,
            reason=UnassignedReason.NO_FEASIBLE_SLOT,
            detail="Step 5 found no feasible slot/dock combination.",
        )
    return UnassignedShipment(
        shipment_id=shipment.shipment_id,
        shipment_number=shipment.shipment_number,
        reason=UnassignedReason.CAPACITY_EXHAUSTED,
        detail="Feasible slots existed but remaining slot capacity was assigned to higher-ranked shipments.",
    )


def to_assignment(
    *,
    rank: int,
    shipment: ShipmentSnapshot,
    option: FeasibleOption | None,
    slot: SlotSnapshot | None,
    dock: DockSnapshot | None,
    kind: AssignmentKind,
) -> ProposedAssignment:
    score = assignment_score(option) if option is not None else None
    return ProposedAssignment(
        shipment_id=shipment.shipment_id,
        shipment_number=shipment.shipment_number,
        slot_id=option.slot_id if option is not None else (shipment.protected_slot_id if kind == AssignmentKind.PROTECTED else None),
        dock_id=option.dock_id if option is not None else (shipment.protected_dock_id if kind == AssignmentKind.PROTECTED else None),
        rank=rank,
        score=score,
        kind=kind,
        lateness_seconds=option.lateness_seconds if option else None,
        early_wait_seconds=option.early_wait_seconds if option else None,
        alignment_seconds=option.alignment_seconds if option else None,
        yard_wait_seconds=option.yard_wait_seconds if option else None,
        reasons=build_reasons(shipment=shipment, option=option, slot=slot, kind=kind, dock=dock),
    )
