"""Allowlisted tool execution against existing deterministic services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.ai.conversation.clocks import (
    localize_clock_on,
    localize_operational_clock,
    slot_ends_on_or_before,
    slot_starts_on_or_after,
)
from app.ai.conversation.models import PresentedOption, ToolResult
from app.ai.conversation.tools import ALLOWED_TOOL_NAMES, ToolName, parse_tool_arguments
from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError
from app.models.enums import AppointmentStatus, ETASource, ExceptionType, ShipmentStatus
from app.schemas.driver_exception import DriverExceptionCreate
from app.schemas.eta_update import ETAUpdateCreate
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.schemas.proposal import ProposalCreateRequest
from app.services.appointment import AppointmentSlotService
from app.services.facility import FacilityService
from app.services.feasibility import FeasibilityService
from app.services.operations import DriverExceptionService, ETAUpdateService
from app.services.proposal import PROPOSAL_MARKER, ProposalService
from app.services.scheduling import SchedulingService
from app.services.shipment import ShipmentService

_EXCEPTION_TYPES = {item.value: item for item in ExceptionType}
_SAFE_ERROR_PREFIXES = ("Shipment", "Proposal", "Appointment", "Dock", "Driver")


class ToolExecutor:
    def __init__(
        self,
        *,
        shipment_service: ShipmentService,
        eta_service: ETAUpdateService,
        exception_service: DriverExceptionService,
        feasibility_service: FeasibilityService,
        slot_service: AppointmentSlotService,
        proposal_service: ProposalService,
        scheduling_service: SchedulingService | None = None,
        facility_service: FacilityService | None = None,
    ) -> None:
        self._shipment_service = shipment_service
        self._eta_service = eta_service
        self._exception_service = exception_service
        self._feasibility_service = feasibility_service
        self._slot_service = slot_service
        self._proposal_service = proposal_service
        self._scheduling_service = scheduling_service
        self._facility_service = facility_service
        self._actor_driver_id: UUID | None = None

    def bind_driver(self, driver_id: UUID | None) -> None:
        self._actor_driver_id = driver_id

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name not in ALLOWED_TOOL_NAMES:
            return ToolResult(name=name, success=False, error="Tool is not allowlisted.", error_code="forbidden")
        try:
            args = parse_tool_arguments(arguments)
        except Exception:
            return ToolResult(
                name=name,
                success=False,
                error="Tool arguments are invalid.",
                error_code="invalid_arguments",
            )
        try:
            data = self._dispatch(name, args.model_dump())
            return ToolResult(name=name, success=True, data=data)
        except NotFoundError as exc:
            return ToolResult(name=name, success=False, error=_safe_error(exc), error_code="not_found")
        except ConflictError as exc:
            message = _safe_error(exc)
            code = "stale" if "stale" in message.lower() else "conflict"
            return ToolResult(name=name, success=False, error=message, error_code=code, data={"status": code})
        except SetuHaulError as exc:
            return ToolResult(name=name, success=False, error=_safe_error(exc), error_code="bad_request")
        except Exception:
            return ToolResult(
                name=name,
                success=False,
                error="The operational service could not complete that request.",
                error_code="internal",
            )

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == ToolName.GET_SHIPMENT_STATUS.value:
            return self._get_shipment_status(_require_uuid(arguments.get("shipment_id"), "shipment_id"))
        if name == ToolName.GET_APPOINTMENT.value:
            return self._get_appointment(
                _require_uuid(arguments.get("shipment_id"), "shipment_id"),
                timezone_name=arguments.get("timezone_name") if isinstance(arguments.get("timezone_name"), str) else None,
            )
        if name == ToolName.RECORD_ETA_UPDATE.value:
            return self._record_eta(arguments)
        if name == ToolName.CREATE_DRIVER_EXCEPTION.value:
            return self._create_exception(arguments)
        if name == ToolName.EVALUATE_FEASIBILITY.value:
            return self._evaluate_feasibility(arguments)
        if name == ToolName.GET_AVAILABLE_OPTIONS.value:
            return self._get_available_options(
                _require_uuid(arguments.get("shipment_id"), "shipment_id"),
                earliest_start_local=arguments.get("earliest_start_local"),
                leave_by_local=arguments.get("leave_by_local"),
                timezone_name=arguments.get("timezone_name"),
            )
        if name == ToolName.CREATE_PROPOSAL.value:
            return self._create_proposal(arguments)
        if name == ToolName.GET_PROPOSAL.value:
            proposal = self._proposal_service.get(_require_uuid(arguments.get("proposal_id"), "proposal_id"))
            return proposal.model_dump(mode="json")
        if name == ToolName.ACCEPT_PROPOSAL.value:
            proposal = self._proposal_service.accept(_require_uuid(arguments.get("proposal_id"), "proposal_id"))
            return proposal.model_dump(mode="json")
        if name == ToolName.REJECT_PROPOSAL.value:
            proposal = self._proposal_service.reject(_require_uuid(arguments.get("proposal_id"), "proposal_id"))
            return proposal.model_dump(mode="json")
        if name == ToolName.REQUEST_HUMAN_ESCALATION.value:
            reason = arguments.get("escalation_reason") or "Human operations review requested."
            return {
                "escalated": True,
                "reason": reason,
                "human_acted": False,
                "message": (
                    f"{reason} I've marked this for human operations review. "
                    "A person has not acted on it yet."
                ),
            }
        if name == ToolName.EVALUATE_FACILITY_SCHEDULE.value:
            return self._evaluate_facility_schedule(arguments)
        raise SetuHaulError("Tool is not allowlisted.")

    def _get_shipment_status(self, shipment_id: UUID) -> dict[str, Any]:
        shipment = self._shipment_service.get(shipment_id)
        latest = self._eta_service.get_latest(shipment_id)
        return {
            "shipment_id": str(shipment.id),
            "shipment_number": shipment.shipment_number,
            "status": shipment.status.value if isinstance(shipment.status, ShipmentStatus) else str(shipment.status),
            "destination_location": shipment.destination_location,
            "latest_eta": latest.latest_eta.isoformat() if latest.latest_eta else None,
            "timezone_name": self._facility_timezone(shipment.destination_facility_id, None),
        }

    def _get_appointment(self, shipment_id: UUID, *, timezone_name: str | None = None) -> dict[str, Any]:
        shipment = self._shipment_service.get(shipment_id)
        listed = self._shipment_service.list_appointments(shipment_id, page=1, page_size=50)
        chosen = _canonical_appointment(listed.items) or _current_appointment(listed.items)
        if chosen is None:
            return {
                "found": False,
                "read_only": True,
                "shipment_id": str(shipment.id),
                "shipment_number": shipment.shipment_number,
                "timezone_name": timezone_name,
            }
        start_time = None
        end_time = None
        if chosen.appointment_slot_id is not None:
            slot = self._slot_service.get(chosen.appointment_slot_id)
            start_time = slot.start_time.isoformat() if slot.start_time else None
            end_time = slot.end_time.isoformat() if slot.end_time else None
        status = chosen.status.value if isinstance(chosen.status, AppointmentStatus) else str(chosen.status)
        return {
            "found": True,
            "read_only": True,
            "shipment_id": str(shipment.id),
            "shipment_number": shipment.shipment_number,
            "appointment_id": str(chosen.id),
            "status": status,
            "slot_id": str(chosen.appointment_slot_id) if chosen.appointment_slot_id else None,
            "start_time": start_time,
            "end_time": end_time,
            "timezone_name": timezone_name,
        }

    def _record_eta(self, arguments: dict[str, Any]) -> dict[str, Any]:
        shipment_id = _require_uuid(arguments.get("shipment_id"), "shipment_id")
        now = datetime.now(timezone.utc)
        new_eta = _parse_datetime(arguments.get("new_eta"))
        timezone_name = arguments.get("timezone_name") if isinstance(arguments.get("timezone_name"), str) else None
        eta_local = arguments.get("eta_local") if isinstance(arguments.get("eta_local"), str) else None
        eta_source = arguments.get("eta_source") if isinstance(arguments.get("eta_source"), str) else None
        shipment = self._shipment_service.get(shipment_id)
        timezone_name = self._facility_timezone(shipment.destination_facility_id, timezone_name)
        latest = self._eta_service.get_latest(shipment_id)
        scheduled = self._scheduled_arrival(shipment_id, timezone_name=timezone_name)
        delay_baseline = scheduled or self._original_eta(shipment_id) or now
        delay = arguments.get("delay_minutes") if isinstance(arguments.get("delay_minutes"), int) else None
        implied_eta = _as_utc(delay_baseline) + timedelta(minutes=delay) if delay is not None else None

        if new_eta is None and eta_local:
            localized = localize_operational_clock(delay_baseline, eta_local, timezone_name)
            if localized is None:
                localized = localize_clock_on(delay_baseline, eta_local, timezone_name)
            if localized is None:
                raise SetuHaulError("The stated arrival time could not be interpreted.")
            new_eta = localized
            eta_source = eta_source or "explicit"
        if new_eta is not None and implied_eta is not None:
            if scheduled is not None:
                explicit = _as_utc(new_eta)
                delta = abs((explicit - implied_eta).total_seconds())
                if delta > 30 * 60:
                    raise SetuHaulError(
                        "The stated arrival time and the stated delay do not match. "
                        "Which arrival time should I use?"
                    )
            new_eta = _as_utc(new_eta)
            eta_source = eta_source or "explicit"
        if new_eta is None:
            if delay is None:
                raise SetuHaulError("A new ETA or delay duration is required.")
            new_eta = implied_eta
            eta_source = eta_source or "relative"
        else:
            new_eta = _as_utc(new_eta)
            eta_source = eta_source or "explicit"

        if latest.latest_eta is not None and _as_utc(latest.latest_eta) == _as_utc(new_eta) and latest.eta_update is not None:
            payload = latest.eta_update.model_dump(mode="json")
            payload["timezone_name"] = timezone_name
            payload["eta_source"] = eta_source
            payload["idempotent"] = True
            return payload
        reason = arguments.get("reason")
        if isinstance(reason, str):
            reason = reason[:2000]
        created = self._eta_service.create(
            shipment_id,
            ETAUpdateCreate(
                new_eta=new_eta,
                update_timestamp=now,
                source=ETASource.DRIVER,
                reason=reason,
            ),
        )
        payload = created.model_dump(mode="json")
        payload["timezone_name"] = timezone_name
        payload["eta_source"] = eta_source
        payload["idempotent"] = False
        return payload

    def _create_exception(self, arguments: dict[str, Any]) -> dict[str, Any]:
        shipment_id = _require_uuid(arguments.get("shipment_id"), "shipment_id")
        raw_type = arguments.get("exception_type") or "delay"
        exception_type = _EXCEPTION_TYPES.get(str(raw_type), ExceptionType.DELAY)
        created = self._exception_service.create(
            shipment_id,
            DriverExceptionCreate(
                exception_type=exception_type,
                occurred_at=datetime.now(timezone.utc),
                driver_id=arguments.get("driver_id"),
                description=arguments.get("description") or arguments.get("reason"),
            ),
        )
        return created.model_dump(mode="json")

    def _evaluate_feasibility(self, arguments: dict[str, Any]) -> dict[str, Any]:
        shipment_id = _require_uuid(arguments.get("shipment_id"), "shipment_id")
        slot_id = arguments.get("appointment_slot_id")
        if slot_id is None:
            listed = self._shipment_service.list_appointments(shipment_id, page=1, page_size=50)
            chosen = _canonical_appointment(listed.items) or _current_appointment(listed.items)
            if chosen is not None and chosen.appointment_slot_id is not None:
                slot_id = chosen.appointment_slot_id
        result = self._feasibility_service.evaluate(
            shipment_id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=slot_id,
                dock_id=arguments.get("dock_id"),
            ),
        )
        payload = {
            "outcome": result.outcome.value,
            "feasible": result.feasible,
            "blocking_reasons": result.blocking_reasons,
            "warnings": result.warnings,
            "operational_facts": result.operational_facts,
        }
        eta_rule = next((rule for rule in result.rule_results if rule.rule_id == "ETA-001"), None)
        if eta_rule is not None:
            payload["arrival_relation"] = eta_rule.facts.get("arrival_relation")
            payload["latest_eta"] = eta_rule.facts.get("latest_eta")
            payload["slot_start"] = eta_rule.facts.get("slot_start")
            payload["slot_end"] = eta_rule.facts.get("slot_end")
            payload["eta_window_reason"] = eta_rule.reason
            if eta_rule.evaluable:
                payload["eta_window_passed"] = bool(eta_rule.passed)
        shipment = self._shipment_service.get(shipment_id)
        payload["timezone_name"] = self._facility_timezone(shipment.destination_facility_id, None)
        return payload

    def _get_available_options(
        self,
        shipment_id: UUID,
        *,
        earliest_start_local: str | None = None,
        leave_by_local: str | None = None,
        timezone_name: str | None = None,
    ) -> dict[str, Any]:
        shipment = self._shipment_service.get(shipment_id)
        if shipment.destination_facility_id is None:
            raise SetuHaulError("Shipment has no destination facility assigned")
        timezone_name = self._facility_timezone(shipment.destination_facility_id, timezone_name)
        slots = sorted(
            self._slot_service.list_open_for_facility(shipment.destination_facility_id),
            key=lambda item: (item.start_time, item.id),
        )
        options: list[PresentedOption] = []
        evaluations: list[dict[str, Any]] = []
        for slot in slots:
            evaluation = self._feasibility_service.evaluate(
                shipment_id,
                FeasibilityEvaluateRequest(
                    appointment_slot_id=slot.id,
                    ignore_delay_exceptions=True,
                ),
            )
            evaluations.append(
                {
                    "slot_id": str(slot.id),
                    "outcome": evaluation.outcome.value,
                    "feasible": evaluation.feasible,
                    "blocking_reasons": evaluation.blocking_reasons,
                }
            )
            if evaluation.feasible:
                options.append(
                    PresentedOption(
                        index=len(options) + 1,
                        slot_id=slot.id,
                        start_time=slot.start_time,
                        end_time=slot.end_time,
                        label=f"{slot.start_time.isoformat()} – {slot.end_time.isoformat()}",
                    )
                )
        unfiltered_count = len(options)
        filtered: list[PresentedOption] = []
        for option in options:
            starts_ok = slot_starts_on_or_after(option.start_time, earliest_start_local, timezone_name)
            ends_ok = slot_ends_on_or_before(option.end_time, leave_by_local, timezone_name)
            if starts_ok is False or ends_ok is False:
                continue
            if starts_ok is None or ends_ok is None:
                continue
            filtered.append(option)
        for index, option in enumerate(filtered, start=1):
            option.index = index
        note = None
        rejection_summary = _rejection_summary(evaluations)
        if not filtered and rejection_summary and unfiltered_count == 0:
            note = (
                "No open facility slot is feasible for the current ETA. "
                + rejection_summary
            )
        elif unfiltered_count and not filtered:
            if earliest_start_local and leave_by_local:
                note = (
                    "There are feasible slots, but none start at or after "
                    f"{earliest_start_local} and also end by {leave_by_local}."
                )
            elif earliest_start_local:
                note = (
                    "There are feasible slots, but none start at or after "
                    f"{earliest_start_local}."
                )
            elif leave_by_local:
                note = f"There are feasible slots, but none end by {leave_by_local}."
        return {
            "options": [option.model_dump(mode="json") for option in filtered],
            "evaluations": evaluations,
            "feasible_count": len(filtered),
            "unfiltered_feasible_count": unfiltered_count,
            "constraint_note": note,
            "rejection_summary": rejection_summary,
            "timezone_name": timezone_name,
        }

    def _create_proposal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        shipment_id = _require_uuid(arguments.get("shipment_id"), "shipment_id")
        slot_id = _require_uuid(arguments.get("appointment_slot_id"), "appointment_slot_id")
        created = self._proposal_service.create(
            shipment_id,
            ProposalCreateRequest(
                appointment_slot_id=slot_id,
                dock_id=arguments.get("dock_id"),
                notes="Created via conversational proposal tool",
            ),
        )
        return created.model_dump(mode="json")

    def _evaluate_facility_schedule(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._scheduling_service is None:
            raise SetuHaulError("Facility scheduling is not configured.")
        from app.schemas.scheduling import ScheduleEvaluateRequest

        shipment_id = arguments.get("shipment_id")
        facility_id = arguments.get("facility_id")
        if shipment_id is not None:
            shipment = self._shipment_service.get(_require_uuid(shipment_id, "shipment_id"))
            if (
                self._actor_driver_id is not None
                and shipment.driver_id is not None
                and shipment.driver_id != self._actor_driver_id
            ):
                raise SetuHaulError("Shipment is not assigned to this driver")
            if shipment.destination_facility_id is None:
                raise SetuHaulError("Shipment has no destination facility assigned")
            if facility_id is not None and _require_uuid(facility_id, "facility_id") != shipment.destination_facility_id:
                raise SetuHaulError("Facility does not match this shipment")
            facility_id = shipment.destination_facility_id
        elif facility_id is not None:
            if self._actor_driver_id is not None:
                raise SetuHaulError("Facility scheduling from a driver conversation requires a bound shipment")
            facility_id = _require_uuid(facility_id, "facility_id")
        else:
            raise SetuHaulError("A shipment or facility is required")
        result = self._scheduling_service.evaluate(facility_id, ScheduleEvaluateRequest())
        payload = result.model_dump(mode="json")
        payload["commits_capacity"] = False
        payload["read_only"] = True
        return payload

    def _scheduled_arrival(self, shipment_id: UUID, *, timezone_name: str | None) -> datetime | None:
        listed = self._shipment_service.list_appointments(shipment_id, page=1, page_size=50)
        original = _canonical_appointment(listed.items)
        if original is None or original.appointment_slot_id is None:
            return None
        slot = self._slot_service.get(original.appointment_slot_id)
        _ = timezone_name
        return slot.start_time

    def _original_eta(self, shipment_id: UUID) -> datetime | None:
        listed = self._eta_service.list(page=1, page_size=50, shipment_id=shipment_id)
        if not listed.items:
            return None
        return listed.items[0].new_eta

    def _facility_timezone(self, facility_id: UUID | None, explicit: str | None) -> str | None:
        if explicit:
            return explicit
        if facility_id is None or self._facility_service is None:
            return None
        try:
            return self._facility_service.get(facility_id).timezone
        except Exception:
            return None


_CURRENT_APPOINTMENT_RANK = {
    AppointmentStatus.CONFIRMED: 0,
    AppointmentStatus.HELD: 1,
    AppointmentStatus.REQUESTED: 2,
}


def _is_proposal_record(item: Any) -> bool:
    notes = getattr(item, "notes", None) or ""
    return PROPOSAL_MARKER in notes


def _canonical_appointment(items: list[Any]) -> Any | None:
    operational = [
        item
        for item in items
        if getattr(item, "status", None) in _CURRENT_APPOINTMENT_RANK and not _is_proposal_record(item)
    ]
    if not operational:
        return None
    operational.sort(key=lambda item: (item.created_at, str(item.id)))
    return operational[0]


def _current_appointment(items: list[Any]) -> Any | None:
    ranked = [
        item
        for item in items
        if getattr(item, "status", None) in _CURRENT_APPOINTMENT_RANK and not _is_proposal_record(item)
    ]
    if not ranked:
        ranked = [item for item in items if getattr(item, "status", None) in _CURRENT_APPOINTMENT_RANK]
    if not ranked:
        return None
    ranked.sort(
        key=lambda item: (
            _CURRENT_APPOINTMENT_RANK[item.status],
            item.created_at,
            str(item.id),
        )
    )
    return ranked[0]


def _rejection_summary(evaluations: list[dict[str, Any]]) -> str | None:
    counts: dict[str, int] = {}
    for item in evaluations:
        if item.get("feasible"):
            continue
        reasons = item.get("blocking_reasons") or []
        label = "; ".join(str(reason) for reason in reasons[:2]) or str(item.get("outcome") or "infeasible")
        counts[label] = counts.get(label, 0) + 1
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    top, count = ranked[0]
    suffix = f" ({count} open slot(s))" if count else ""
    return f"{top}{suffix}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _aware(value: datetime) -> datetime:
    return _as_utc(value)


def _require_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SetuHaulError(f"{field_name} is not a valid UUID") from exc


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if any(token in lowered for token in ("traceback", "sqlalchemy", "psycopg", "password", "api_key", "secret")):
        return "The operational service rejected this request."
    if text.startswith(_SAFE_ERROR_PREFIXES) or "proposal" in lowered or "feasible" in lowered or "stale" in lowered:
        return text
    return text if len(text) < 240 else "The operational service rejected this request."
