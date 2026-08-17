"""Structured conversation types. These are language/orchestration contracts, not operational truth."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationIntent(str, Enum):
    REPORT_DELAY = "REPORT_DELAY"
    UPDATE_ETA = "UPDATE_ETA"
    REPORT_EXCEPTION = "REPORT_EXCEPTION"
    ASK_STATUS = "ASK_STATUS"
    ASK_APPOINTMENT = "ASK_APPOINTMENT"
    ASK_OPTIONS = "ASK_OPTIONS"
    ASK_FEASIBILITY_STATUS = "ASK_FEASIBILITY_STATUS"
    ASK_FACILITY_SCHEDULE = "ASK_FACILITY_SCHEDULE"
    PROPOSE_CHANGE = "PROPOSE_CHANGE"
    ACCEPT_PROPOSAL = "ACCEPT_PROPOSAL"
    REJECT_PROPOSAL = "REJECT_PROPOSAL"
    CANCEL_REQUEST = "CANCEL_REQUEST"
    REQUEST_DRIVER_REASSIGNMENT = "REQUEST_DRIVER_REASSIGNMENT"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"


class PresentedOption(BaseModel):
    index: int
    slot_id: UUID
    dock_id: UUID | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    label: str | None = None


class CandidateShipment(BaseModel):
    shipment_id: UUID
    shipment_number: str
    destination_location: str
    origin_location: str
    status: str


class ConversationContext(BaseModel):
    thread_id: UUID
    driver_id: UUID | None = None
    shipment_id: UUID | None = None
    latest_eta: datetime | str | None = None
    exception_id: UUID | None = None
    presented_options: list[PresentedOption] = Field(default_factory=list)
    selected_option_index: int | None = None
    proposal_id: UUID | None = None
    proposal_slot_id: UUID | None = None
    pending_proposal_count: int = 0
    last_tool_result: dict[str, Any] | None = None
    pending_clarification: str | None = None
    pending_intent: ConversationIntent | None = None
    pending_delay_minutes: int | None = None
    facility_timezone: str | None = None
    earliest_start_local: str | None = None
    leave_by_local: str | None = None
    repair_duration_minutes: int | None = None
    reported_delay_minutes: int | None = None
    explicit_eta_local: str | None = None
    eta_authority: str | None = None
    exception_type: str | None = None
    original_appointment_feasible: bool | None = None
    last_clarification_key: str | None = None
    requires_human: bool = False
    escalation_reason: str | None = None
    candidate_shipments: list[CandidateShipment] = Field(default_factory=list)


class Understanding(BaseModel):
    intent: ConversationIntent
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    shipment_id: UUID | None = None
    shipment_hint: str | None = None
    delay_minutes: int | None = None
    repair_duration_minutes: int | None = None
    new_eta: datetime | None = None
    eta_local: str | None = None
    original_appointment_local: str | None = None
    earliest_start_local: str | None = None
    leave_by_local: str | None = None
    asks_options: bool = False
    cannot_make_appointment: bool = False
    leave_by_ambiguous: bool = False
    option_preference: str | None = None
    option_clock_local: str | None = None
    completion_by_local: str | None = None
    option_index: int | None = None
    confirm: bool = False
    reject: bool = False
    wants_human: bool = False
    exception_type: str | None = None
    injection_attempt: bool = False
    raw_message: str = ""


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    name: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None


class AgentTurn(BaseModel):
    intent: ConversationIntent
    confidence: float = 0.0
    response: str
    status: str
    tool_calls: list[ToolResult] = Field(default_factory=list)
    requires_clarification: bool = False
    requires_human: bool = False
    context: ConversationContext
    metadata: dict[str, Any] = Field(default_factory=dict)
