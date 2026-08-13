"""Pure facility-schedule ranker. No database access and no LLM."""

from app.engines.scheduling.evaluator import (
    option_sort_key,
    shipment_sort_key,
    to_assignment,
    unassigned_for,
)
from app.engines.scheduling.models import (
    AssignmentKind,
    FeasibleOption,
    ProposedAssignment,
    SchedulingContext,
    SchedulingResult,
)
from app.engines.scheduling.rules import RANKING_POLICY


class SchedulingEngine:
    def evaluate(self, context: SchedulingContext) -> SchedulingResult:
        slots = {item.slot_id: item for item in context.slots}
        docks = {item.dock_id: item for item in context.docks}
        remaining = {item.slot_id: item.remaining_capacity for item in context.slots}
        shipments = {item.shipment_id: item for item in context.shipments}
        options_by_shipment: dict = {}
        for option in context.options:
            options_by_shipment.setdefault(option.shipment_id, []).append(option)

        assignments: list[ProposedAssignment] = []
        assigned_ids: set = set()
        warnings: list[str] = []

        protected = sorted(
            [item for item in context.shipments if item.protected_slot_id is not None],
            key=lambda item: (item.shipment_number, str(item.shipment_id)),
        )
        rank = 1
        for shipment in protected:
            slot = slots.get(shipment.protected_slot_id) if shipment.protected_slot_id else None
            dock = docks.get(shipment.protected_dock_id) if shipment.protected_dock_id else None
            assignments.append(
                to_assignment(
                    rank=rank,
                    shipment=shipment,
                    option=None,
                    slot=slot,
                    dock=dock,
                    kind=AssignmentKind.PROTECTED,
                )
            )
            assigned_ids.add(shipment.shipment_id)
            rank += 1

        competing = [item for item in context.shipments if item.shipment_id not in assigned_ids]
        competing.sort(key=lambda item: shipment_sort_key(item, _best_feasible(options_by_shipment.get(item.shipment_id, []), slots, docks)))

        for shipment in competing:
            chosen = _choose_option(
                options_by_shipment.get(shipment.shipment_id, []),
                remaining,
                slots,
                docks,
            )
            if chosen is None:
                continue
            remaining[chosen.slot_id] = remaining.get(chosen.slot_id, 0) - 1
            slot = slots[chosen.slot_id]
            dock = docks.get(chosen.dock_id) if chosen.dock_id else None
            assignments.append(
                to_assignment(
                    rank=rank,
                    shipment=shipment,
                    option=chosen,
                    slot=slot,
                    dock=dock,
                    kind=AssignmentKind.PROPOSED,
                )
            )
            assigned_ids.add(shipment.shipment_id)
            rank += 1

        unassigned = tuple(
            unassigned_for(item, tuple(options_by_shipment.get(item.shipment_id, [])))
            for item in context.shipments
            if item.shipment_id not in assigned_ids
        )
        if not context.slots:
            warnings.append("No appointment slots were in the scheduling horizon.")
        if not context.shipments:
            warnings.append("No eligible shipments were found for this facility.")
        if any(item.remaining_capacity <= 0 for item in context.slots) and competing:
            warnings.append("One or more slots had no remaining capacity after protected appointments.")

        assignments.sort(key=lambda item: (item.rank, str(item.shipment_id)))
        return SchedulingResult(
            facility_id=context.facility_id,
            evaluated_at=context.evaluated_at,
            assignments=tuple(assignments),
            unassigned=unassigned,
            warnings=tuple(warnings),
            ranking_policy=RANKING_POLICY,
        )


def _best_feasible(
    options: list[FeasibleOption],
    slots: dict,
    docks: dict,
) -> FeasibleOption | None:
    feasible = [item for item in options if item.feasible and item.slot_id in slots]
    if not feasible:
        return None
    feasible.sort(key=lambda item: option_sort_key(item, slots[item.slot_id], _dock_name(docks, item.dock_id)))
    return feasible[0]


def _choose_option(
    options: list[FeasibleOption],
    remaining: dict,
    slots: dict,
    docks: dict,
) -> FeasibleOption | None:
    feasible = [
        item
        for item in options
        if item.feasible and item.slot_id in remaining and remaining[item.slot_id] > 0 and item.slot_id in slots
    ]
    if not feasible:
        return None
    feasible.sort(key=lambda item: option_sort_key(item, slots[item.slot_id], _dock_name(docks, item.dock_id)))
    return feasible[0]


def _dock_name(docks: dict, dock_id) -> str:
    dock = docks.get(dock_id) if dock_id else None
    return dock.name if dock is not None else ""
