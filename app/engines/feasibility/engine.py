"""Feasibility engine orchestration and result aggregation."""

from app.engines.feasibility.evaluator import RULE_EVALUATORS
from app.engines.feasibility.models import (
    FeasibilityContext,
    FeasibilityEvaluation,
    FeasibilityOutcome,
    RuleResult,
    RuleSeverity,
)


class FeasibilityEngine:
    """Pure deterministic feasibility evaluator — no database access."""

    def evaluate(self, context: FeasibilityContext) -> FeasibilityEvaluation:
        rule_results = self._run_rules(context)
        blocking_reasons = tuple(
            result.reason
            for result in rule_results
            if not result.passed
            and result.severity == RuleSeverity.BLOCKING
            and result.evaluable
        )
        warnings = tuple(
            result.reason
            for result in rule_results
            if not result.passed
            and result.severity == RuleSeverity.WARNING
            and result.evaluable
        )

        has_unevaluable = any(not result.evaluable and not result.passed for result in rule_results)
        if blocking_reasons:
            outcome = FeasibilityOutcome.NOT_FEASIBLE
            feasible = False
        elif has_unevaluable:
            outcome = FeasibilityOutcome.NOT_EVALUABLE
            feasible = False
        else:
            outcome = FeasibilityOutcome.FEASIBLE
            feasible = True

        return FeasibilityEvaluation(
            outcome=outcome,
            feasible=feasible,
            evaluated_at=context.evaluated_at,
            shipment_id=context.shipment.shipment_id,
            rule_results=tuple(rule_results),
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            operational_facts=self._build_operational_facts(context),
        )

    def _run_rules(self, context: FeasibilityContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for rule_id, evaluator in RULE_EVALUATORS:
            output = evaluator(context)
            if isinstance(output, list):
                results.extend(output)
            else:
                results.append(output)
            # Preserve declared order even if an evaluator returns multiple rows.
            _ = rule_id
        return results

    def _build_operational_facts(self, context: FeasibilityContext) -> dict[str, object]:
        return {
            "shipment_id": str(context.shipment.shipment_id),
            "shipment_number": context.shipment.shipment_number,
            "shipment_status": context.shipment.status,
            "destination_facility_id": (
                str(context.shipment.destination_facility_id)
                if context.shipment.destination_facility_id
                else None
            ),
            "appointment_id": (
                str(context.appointment.appointment_id) if context.appointment else None
            ),
            "appointment_slot_id": str(context.slot.slot_id) if context.slot else None,
            "dock_id": str(context.dock.dock_id) if context.dock else None,
            "latest_eta": context.latest_eta.isoformat() if context.latest_eta else None,
            "active_exception_count": len(context.active_exceptions),
            "facility_rule_count": len(context.facility_rules),
            "daily_appointment_count": context.daily_appointment_count,
        }
