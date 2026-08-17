"""Allowlisted conversational tools. Names only — execution is elsewhere."""

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ToolName(str, Enum):
    GET_SHIPMENT_STATUS = "get_shipment_status"
    GET_APPOINTMENT = "get_appointment"
    RECORD_ETA_UPDATE = "record_eta_update"
    CREATE_DRIVER_EXCEPTION = "create_driver_exception"
    EVALUATE_FEASIBILITY = "evaluate_feasibility"
    GET_AVAILABLE_OPTIONS = "get_available_options"
    CREATE_PROPOSAL = "create_proposal"
    GET_PROPOSAL = "get_proposal"
    ACCEPT_PROPOSAL = "accept_proposal"
    REJECT_PROPOSAL = "reject_proposal"
    REQUEST_HUMAN_ESCALATION = "request_human_escalation"
    EVALUATE_FACILITY_SCHEDULE = "evaluate_facility_schedule"


ALLOWED_TOOL_NAMES = frozenset(item.value for item in ToolName)

IRREVERSIBLE_TOOLS = frozenset(
    {
        ToolName.CREATE_PROPOSAL.value,
        ToolName.ACCEPT_PROPOSAL.value,
        ToolName.REJECT_PROPOSAL.value,
        ToolName.RECORD_ETA_UPDATE.value,
        ToolName.CREATE_DRIVER_EXCEPTION.value,
    }
)


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_id: UUID | None = None
    proposal_id: UUID | None = None
    appointment_slot_id: UUID | None = None
    dock_id: UUID | None = None
    new_eta: str | None = None
    delay_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    reason: str | None = None
    exception_type: str | None = None
    description: str | None = None
    driver_id: UUID | None = None
    escalation_reason: str | None = None
    facility_id: UUID | None = None
    scheduling_start: str | None = None
    scheduling_end: str | None = None
    earliest_start_local: str | None = None
    leave_by_local: str | None = None
    eta_local: str | None = None
    timezone_name: str | None = None
    eta_source: str | None = None


def validate_tool_name(name: str) -> str:
    if name not in ALLOWED_TOOL_NAMES:
        raise ValueError("unknown_tool")
    return name


def parse_tool_arguments(payload: dict[str, Any]) -> ToolArguments:
    return ToolArguments.model_validate(payload)
