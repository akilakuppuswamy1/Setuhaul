"""Allowlisted tool execution against existing deterministic services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.ai.conversation.models import PresentedOption, ToolResult
from app.ai.conversation.tools import ALLOWED_TOOL_NAMES, ToolName, parse_tool_arguments
from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError
from app.models.enums import ETASource, ExceptionType, ShipmentStatus
from app.schemas.driver_exception import DriverExceptionCreate
from app.schemas.eta_update import ETAUpdateCreate
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.schemas.proposal import ProposalCreateRequest
from app.services.appointment import AppointmentSlotService
from app.services.feasibility import FeasibilityService
from app.services.operations import DriverExceptionService, ETAUpdateService
from app.services.proposal import ProposalService
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
    ) -> None:
        self._shipment_service = shipment_service
        self._eta_service = eta_service
        self._exception_service = exception_service
        self._feasibility_service = feasibility_service
        self._slot_service = slot_service
        self._proposal_service = proposal_service

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
        if name == ToolName.RECORD_ETA_UPDATE.value:
            return self._record_eta(arguments)
        if name == ToolName.CREATE_DRIVER_EXCEPTION.value:
            return self._create_exception(arguments)
        if name == ToolName.EVALUATE_FEASIBILITY.value:
            return self._evaluate_feasibility(arguments)
        if name == ToolName.GET_AVAILABLE_OPTIONS.value:
            return self._get_available_options(_require_uuid(arguments.get("shipment_id"), "shipment_id"))
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
        }

    def _record_eta(self, arguments: dict[str, Any]) -> dict[str, Any]:
        shipment_id = _require_uuid(arguments.get("shipment_id"), "shipment_id")
        now = datetime.now(timezone.utc)
        new_eta = _parse_datetime(arguments.get("new_eta"))
        if new_eta is None:
            delay = arguments.get("delay_minutes")
            if not isinstance(delay, int):
                raise SetuHaulError("A new ETA or delay duration is required.")
            latest = self._eta_service.get_latest(shipment_id)
            base = latest.latest_eta or now
            new_eta = _aware(base) + timedelta(minutes=delay)
        else:
            new_eta = _aware(new_eta)
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
        return created.model_dump(mode="json")

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
        result = self._feasibility_service.evaluate(
            shipment_id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=arguments.get("appointment_slot_id"),
                dock_id=arguments.get("dock_id"),
            ),
        )
        return {
            "outcome": result.outcome.value,
            "feasible": result.feasible,
            "blocking_reasons": result.blocking_reasons,
            "warnings": result.warnings,
        }

    def _get_available_options(self, shipment_id: UUID) -> dict[str, Any]:
        shipment = self._shipment_service.get(shipment_id)
        if shipment.destination_facility_id is None:
            raise SetuHaulError("Shipment has no destination facility assigned")
        slots = self._slot_service.list_open_for_facility(shipment.destination_facility_id)
        options: list[PresentedOption] = []
        evaluations: list[dict[str, Any]] = []
        for slot in slots:
            evaluation = self._feasibility_service.evaluate(
                shipment_id,
                FeasibilityEvaluateRequest(appointment_slot_id=slot.id),
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
        return {
            "options": [option.model_dump(mode="json") for option in options],
            "evaluations": evaluations,
            "feasible_count": len(options),
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


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
