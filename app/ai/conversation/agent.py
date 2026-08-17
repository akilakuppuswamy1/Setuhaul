"""Conversation agent: language in, allowlisted tools out, deterministic services remain authoritative."""

from __future__ import annotations

import re

from app.ai.conversation.clocks import parse_hhmm, slot_ends_on_or_before
from app.ai.conversation.intents import _declines_confirm
from app.ai.conversation.context import match_presented_option, resolve_option, resolve_shipment
from app.ai.conversation.escalation import driver_escalation_message, should_escalate
from app.ai.conversation.formatter import format_feasibility_status, format_turn, public_metadata
from app.ai.conversation.models import (
    AgentTurn,
    ConversationContext,
    ConversationIntent,
    PresentedOption,
    ToolResult,
    Understanding,
)
from app.ai.conversation.semantics import is_informal_affirmative
from app.ai.conversation.tools import IRREVERSIBLE_TOOLS, ToolName

_SHIPMENT_REQUIRED = {
    ConversationIntent.REPORT_DELAY,
    ConversationIntent.UPDATE_ETA,
    ConversationIntent.REPORT_EXCEPTION,
    ConversationIntent.ASK_STATUS,
    ConversationIntent.ASK_APPOINTMENT,
    ConversationIntent.ASK_OPTIONS,
    ConversationIntent.ASK_FEASIBILITY_STATUS,
    ConversationIntent.ASK_FACILITY_SCHEDULE,
    ConversationIntent.PROPOSE_CHANGE,
    ConversationIntent.ACCEPT_PROPOSAL,
    ConversationIntent.REJECT_PROPOSAL,
    ConversationIntent.CANCEL_REQUEST,
    ConversationIntent.REQUEST_DRIVER_REASSIGNMENT,
}


class ConversationAgent:
    def __init__(self, executor, provider: LLMProvider | None = None) -> None:
        self._executor = executor
        self._provider = provider or FakeLLMProvider()

    def handle(self, message: str, context: ConversationContext) -> AgentTurn:
        understanding = self._provider.understand(message, _context_summary(context))
        if understanding.wants_human:
            understanding.intent = ConversationIntent.HUMAN_ESCALATION
        understanding = _bind_bare_option_index(understanding, context)
        understanding = _resume_pending(understanding, context)
        understanding = _bind_presented_selection(understanding, context)
        return self.handle_understanding(understanding, context)

    def handle_understanding(
        self,
        understanding: Understanding,
        context: ConversationContext,
    ) -> AgentTurn:
        intent = understanding.intent
        shipment_id, shipment_question = resolve_shipment(
            context,
            understanding.shipment_hint,
            understanding.shipment_id,
        )
        if shipment_id is not None:
            context.shipment_id = shipment_id
        _store_driver_constraints(understanding, context)

        if intent in _SHIPMENT_REQUIRED and shipment_id is None:
            question = shipment_question or "Which shipment are you referring to?"
            context.pending_clarification = "shipment"
            context.pending_intent = intent
            context.pending_delay_minutes = understanding.delay_minutes
            return _clarification_turn(intent, understanding.confidence, context, question)

        if intent in {ConversationIntent.PROPOSE_CHANGE, ConversationIntent.ACCEPT_PROPOSAL}:
            option_turn = self._handle_option_intent(understanding, context)
            if option_turn is not None:
                return option_turn

        plan = _plan_tools(understanding, context)
        results: list[ToolResult] = []
        for call in plan.calls:
            if understanding.injection_attempt and call["name"] in IRREVERSIBLE_TOOLS:
                continue
            arguments = dict(call["arguments"])
            if call["name"] == ToolName.ACCEPT_PROPOSAL.value and not arguments.get("proposal_id"):
                if context.proposal_id is None:
                    continue
                arguments["proposal_id"] = str(context.proposal_id)
            result = self._executor.execute(call["name"], arguments)
            results.append(result)
            _apply_tool_result(context, result)

        if plan.clarification:
            context.pending_clarification = plan.pending
            prefix = format_turn(results=results) if results else ""
            question = f"{prefix} {plan.clarification}".strip() if prefix else plan.clarification
            return _clarification_turn(
                intent,
                understanding.confidence,
                context,
                question,
                results=results,
            )

        already_escalated = any(
            item.name == ToolName.REQUEST_HUMAN_ESCALATION.value and item.success for item in results
        )
        if understanding.injection_attempt and not results:
            return _completed_turn(
                ConversationIntent.CLARIFICATION_REQUIRED,
                understanding.confidence,
                context,
                results,
                "I can't change operational rules or permissions from that message.",
                status="rejected",
            )
        escalate, reason = _maybe_escalate(understanding, context, results)
        if escalate and not already_escalated:
            esc = self._executor.execute(
                ToolName.REQUEST_HUMAN_ESCALATION.value,
                {"escalation_reason": reason},
            )
            results.append(esc)
            already_escalated = True
        if already_escalated or escalate:
            context.requires_human = True
            for item in results:
                if item.name == ToolName.REQUEST_HUMAN_ESCALATION.value and item.success:
                    tool_reason = item.data.get("reason")
                    if isinstance(tool_reason, str) and tool_reason.strip():
                        context.escalation_reason = tool_reason
            context.escalation_reason = context.escalation_reason or reason
            response = driver_escalation_message(context.escalation_reason)
            final_intent = (
                ConversationIntent.REQUEST_DRIVER_REASSIGNMENT
                if intent == ConversationIntent.REQUEST_DRIVER_REASSIGNMENT
                else ConversationIntent.HUMAN_ESCALATION
            )
            return _completed_turn(
                final_intent,
                understanding.confidence,
                context,
                results,
                response,
                requires_human=True,
                status="escalated",
            )

        response = format_turn(results=results)
        if intent == ConversationIntent.ASK_FEASIBILITY_STATUS:
            response = format_feasibility_status(
                results,
                completion_by_local=understanding.completion_by_local,
            ) or response
        if intent == ConversationIntent.ASK_STATUS and _declines_confirm(understanding.raw_message.lower()):
            response = "The appointment has not been confirmed."
        offered_options = False
        if (
            understanding.intent in {
                ConversationIntent.UPDATE_ETA,
                ConversationIntent.REPORT_DELAY,
                ConversationIntent.REPORT_EXCEPTION,
            }
            and not understanding.asks_options
            and not understanding.cannot_make_appointment
            and context.original_appointment_feasible is False
            and all(item.name != ToolName.GET_AVAILABLE_OPTIONS.value for item in results)
        ):
            response = f"{response} I can check later available slots.".strip()
            offered_options = True
        status = "ok"
        if any(not item.success for item in results):
            status = results[-1].error_code or "error"
        turn = _completed_turn(intent, understanding.confidence, context, results, response, status=status)
        if offered_options:
            turn.context.pending_clarification = "options"
            turn.context.pending_intent = ConversationIntent.ASK_OPTIONS
        return turn

    def _handle_option_intent(
        self,
        understanding: Understanding,
        context: ConversationContext,
    ) -> AgentTurn | None:
        if understanding.option_index is not None or understanding.option_preference or understanding.option_clock_local:
            option, question = match_presented_option(
                context,
                option_index=understanding.option_index,
                preference=understanding.option_preference,
                clock_hhmm=understanding.option_clock_local,
            )
            if question:
                return _clarification_turn(
                    understanding.intent,
                    understanding.confidence,
                    context,
                    question,
                )
            if option is None:
                if not context.presented_options:
                    return _clarification_turn(
                        understanding.intent,
                        understanding.confidence,
                        context,
                        "I don't currently have a list of appointment options in this conversation. "
                        "Would you like me to find available options?",
                        pending="options",
                    )
                return _clarification_turn(
                    understanding.intent,
                    understanding.confidence,
                    context,
                    "I couldn't match that to a presented option. Which numbered option do you mean?",
                )
            context.selected_option_index = option.index
        if understanding.leave_by_local or context.leave_by_local:
            leave_by = understanding.leave_by_local or context.leave_by_local
            option = _selected_option(context)
            if option is not None:
                fits = slot_ends_on_or_before(
                    option.end_time,
                    leave_by,
                    context.facility_timezone,
                )
                if fits is None:
                    return _clarification_turn(
                        understanding.intent,
                        understanding.confidence,
                        context,
                        (
                            "I don't have a slot end time to check against your leave-by time, "
                            "so I cannot propose that option without guessing. "
                            "Which numbered option should I use?"
                        ),
                    )
                if fits is False:
                    return _leave_by_rejected_turn(understanding, context, option, leave_by)
        return None


def _plan_tools(understanding: Understanding, context: ConversationContext) -> "_Plan":
    intent = understanding.intent
    shipment_id = str(context.shipment_id) if context.shipment_id else None
    if intent == ConversationIntent.HUMAN_ESCALATION:
        return _Plan(
            calls=[
                {
                    "name": ToolName.REQUEST_HUMAN_ESCALATION.value,
                    "arguments": {"escalation_reason": "The driver requested a human operator."},
                }
            ]
        )
    if intent == ConversationIntent.REQUEST_DRIVER_REASSIGNMENT:
        return _Plan(
            calls=[
                {
                    "name": ToolName.REQUEST_HUMAN_ESCALATION.value,
                    "arguments": {
                        "escalation_reason": (
                            "Driver requested reassignment to another driver for this shipment."
                        ),
                    },
                }
            ]
        )
    if intent == ConversationIntent.CLARIFICATION_REQUIRED:
        if context.leave_by_local:
            return _Plan(
                clarification=(
                    f"I'll keep your leave-by time of {_display_hhmm(context.leave_by_local)} in mind. "
                    "Would you like me to find appointment options that finish by then?"
                ),
                pending="options",
            )
        return _Plan(clarification="Could you tell me what you need help with for this shipment?")
    if intent == ConversationIntent.ASK_STATUS:
        if context.proposal_id is not None:
            return _Plan(
                calls=[
                    {
                        "name": ToolName.GET_PROPOSAL.value,
                        "arguments": {"proposal_id": str(context.proposal_id)},
                    }
                ]
            )
        return _Plan(calls=[{"name": ToolName.GET_SHIPMENT_STATUS.value, "arguments": {"shipment_id": shipment_id}}])
    if intent == ConversationIntent.ASK_FEASIBILITY_STATUS:
        arguments = {"shipment_id": shipment_id}
        if context.facility_timezone:
            arguments["timezone_name"] = context.facility_timezone
        return _Plan(
            calls=[
                {"name": ToolName.EVALUATE_FEASIBILITY.value, "arguments": {"shipment_id": shipment_id}},
                {"name": ToolName.GET_APPOINTMENT.value, "arguments": arguments},
            ]
        )
    if intent == ConversationIntent.ASK_APPOINTMENT:
        arguments = {"shipment_id": shipment_id}
        if context.facility_timezone:
            arguments["timezone_name"] = context.facility_timezone
        return _Plan(calls=[{"name": ToolName.GET_APPOINTMENT.value, "arguments": arguments}])
    if intent == ConversationIntent.ASK_FACILITY_SCHEDULE:
        return _Plan(
            calls=[
                {
                    "name": ToolName.EVALUATE_FACILITY_SCHEDULE.value,
                    "arguments": {"shipment_id": shipment_id},
                }
            ]
        )
    if intent == ConversationIntent.PROPOSE_CHANGE:
        option = _selected_option(context)
        if option is None:
            if not context.presented_options:
                return _Plan(
                    clarification=(
                        "I don't currently have a list of appointment options in this conversation. "
                        "Would you like me to find available options?"
                    ),
                    pending="options",
                )
            return _Plan(clarification="Which numbered option should I request?")
        if (
            context.proposal_id is not None
            and context.proposal_slot_id is not None
            and context.proposal_slot_id == option.slot_id
        ):
            return _Plan(
                calls=[
                    {
                        "name": ToolName.GET_PROPOSAL.value,
                        "arguments": {"proposal_id": str(context.proposal_id)},
                    }
                ]
            )
        return _Plan(
            calls=[
                {
                    "name": ToolName.CREATE_PROPOSAL.value,
                    "arguments": {
                        "shipment_id": shipment_id,
                        "appointment_slot_id": str(option.slot_id),
                        "dock_id": str(option.dock_id) if option.dock_id else None,
                    },
                }
            ]
        )
    if intent == ConversationIntent.ACCEPT_PROPOSAL:
        return _plan_accept(context, shipment_id, understanding.confirm)
    if intent in {
        ConversationIntent.UPDATE_ETA,
        ConversationIntent.REPORT_DELAY,
        ConversationIntent.REPORT_EXCEPTION,
        ConversationIntent.ASK_OPTIONS,
    } or understanding.asks_options:
        return _plan_operational(understanding, context, shipment_id)
    if intent in {ConversationIntent.REJECT_PROPOSAL, ConversationIntent.CANCEL_REQUEST}:
        if context.proposal_id is None:
            return _Plan(clarification="I don't have an active proposal to reject in this conversation.")
        return _Plan(
            calls=[
                {
                    "name": ToolName.REJECT_PROPOSAL.value,
                    "arguments": {"proposal_id": str(context.proposal_id)},
                }
            ]
        )
    return _Plan(clarification="Could you tell me what you need help with for this shipment?")


def _plan_operational(
    understanding: Understanding,
    context: ConversationContext,
    shipment_id: str | None,
) -> "_Plan":
    asks_options = understanding.intent == ConversationIntent.ASK_OPTIONS or understanding.asks_options
    repair_without_eta = (
        understanding.repair_duration_minutes is not None
        and understanding.eta_local is None
        and understanding.delay_minutes is None
        and understanding.new_eta is None
    )
    if repair_without_eta and not asks_options:
        minutes = understanding.repair_duration_minutes
        calls = [_exception_call(understanding, context, shipment_id)]
        return _Plan(
            calls=calls,
            clarification=(
                f"I understand the repair may take about {minutes} minutes. "
                "What time do you expect to reach the facility?"
            ),
            pending="eta",
        )

    impossible = _impossible_eta_and_leave_by(understanding, context)
    if impossible:
        if context.last_clarification_key == "impossible_constraints":
            return _Plan(
                calls=[
                    {
                        "name": ToolName.REQUEST_HUMAN_ESCALATION.value,
                        "arguments": {
                            "escalation_reason": (
                                "Arrival time and leave-by constraint cannot both be true."
                            )
                        },
                    }
                ]
            )
        context.last_clarification_key = "impossible_constraints"
        return _Plan(
            clarification=(
                "Those times cannot both be right: the arrival would be after the leave-by time. "
                "Which time should I use, or should I escalate this to operations?"
            ),
            pending="constraints",
        )

    if (
        context.eta_authority == "explicit"
        and understanding.eta_local is None
        and understanding.delay_minutes is not None
        and context.reported_delay_minutes is not None
        and understanding.delay_minutes != context.reported_delay_minutes
    ):
        when = _display_hhmm(context.explicit_eta_local) if context.explicit_eta_local else "the arrival time you gave"
        context.last_clarification_key = "eta_conflict"
        return _Plan(
            clarification=(
                f"You previously said you would arrive at {when}. "
                "Is this new delay instead of that arrival time?"
            ),
            pending="eta",
        )

    skip_relative_after_explicit = (
        context.eta_authority == "explicit"
        and understanding.eta_local is None
        and understanding.delay_minutes is not None
    )

    calls: list[dict] = []
    needs_exception = _should_record_exception(understanding, asks_options)
    if needs_exception:
        calls.append(_exception_call(understanding, context, shipment_id))

    has_eta_fact = (
        understanding.eta_local is not None
        or understanding.delay_minutes is not None
        or understanding.new_eta is not None
    )
    if (
        understanding.intent in {ConversationIntent.UPDATE_ETA, ConversationIntent.REPORT_DELAY}
        and not has_eta_fact
        and not asks_options
    ):
        return _Plan(clarification="How late will you be, in minutes or hours?")

    if has_eta_fact and not skip_relative_after_explicit:
        arguments: dict = {
            "shipment_id": shipment_id,
            "reason": understanding.raw_message,
        }
        if context.facility_timezone:
            arguments["timezone_name"] = context.facility_timezone
        if understanding.eta_local:
            arguments["eta_local"] = understanding.eta_local
            arguments["eta_source"] = "explicit"
        if understanding.original_appointment_local:
            arguments["original_eta_local"] = understanding.original_appointment_local
        if understanding.delay_minutes is not None and not understanding.eta_local:
            arguments["delay_minutes"] = understanding.delay_minutes
            arguments["eta_source"] = "relative"
        elif understanding.delay_minutes is not None and understanding.eta_local:
            arguments["delay_minutes"] = understanding.delay_minutes
        calls.append({"name": ToolName.RECORD_ETA_UPDATE.value, "arguments": arguments})

    evaluate_original = has_eta_fact or needs_exception or skip_relative_after_explicit
    if evaluate_original:
        calls.append(
            {
                "name": ToolName.EVALUATE_FEASIBILITY.value,
                "arguments": {"shipment_id": shipment_id},
            }
        )

    fetch_options = asks_options or understanding.cannot_make_appointment
    if fetch_options:
        calls.append(_options_call(context, shipment_id))
    elif not calls:
        calls.append(_options_call(context, shipment_id))
    return _Plan(calls=calls)


def _should_record_exception(understanding: Understanding, asks_options: bool) -> bool:
    if understanding.exception_type in {"breakdown", "repair", "other"}:
        return True
    if understanding.cannot_make_appointment:
        return True
    if understanding.intent == ConversationIntent.REPORT_EXCEPTION:
        return True
    if asks_options and understanding.cannot_make_appointment:
        return True
    return False


def _impossible_eta_and_leave_by(understanding: Understanding, context: ConversationContext) -> bool:
    eta_local = understanding.eta_local or context.explicit_eta_local
    leave_by = understanding.leave_by_local or context.leave_by_local
    if not eta_local or not leave_by:
        return False
    eta = parse_hhmm(eta_local)
    leave = parse_hhmm(leave_by)
    if eta is None or leave is None:
        return False
    eta_min = eta[0] * 60 + eta[1]
    leave_min = leave[0] * 60 + leave[1]
    if eta[0] >= 12 and leave[0] < 12:
        leave_min += 24 * 60
    return eta_min > leave_min


def _plan_accept(context: ConversationContext, shipment_id: str | None, confirm: bool) -> "_Plan":
    calls: list[dict] = []
    if context.pending_proposal_count > 1:
        return _Plan(clarification="There is more than one pending proposal. Which numbered option should I confirm?")
    if context.proposal_id is None:
        option = _selected_option(context)
        if option is None:
            if not context.presented_options:
                return _Plan(
                    clarification=(
                        "I don't currently have a list of appointment options in this conversation. "
                        "Would you like me to find available options?"
                    ),
                    pending="options",
                )
            return _Plan(clarification="Which numbered option should I confirm?")
        calls.append(
            {
                "name": ToolName.CREATE_PROPOSAL.value,
                "arguments": {
                    "shipment_id": shipment_id,
                    "appointment_slot_id": str(option.slot_id),
                    "dock_id": str(option.dock_id) if option.dock_id else None,
                },
            }
        )
        if not confirm:
            return _Plan(calls=calls)
    calls.append(
        {
            "name": ToolName.ACCEPT_PROPOSAL.value,
            "arguments": {
                "proposal_id": str(context.proposal_id) if context.proposal_id else None,
            },
        }
    )
    return _Plan(calls=calls)


class _Plan:
    def __init__(
        self,
        *,
        calls: list[dict] | None = None,
        clarification: str | None = None,
        pending: str | None = None,
    ) -> None:
        self.calls = calls or []
        self.clarification = clarification
        self.pending = pending


def _options_call(context: ConversationContext, shipment_id: str | None) -> dict:
    arguments = {"shipment_id": shipment_id}
    if context.earliest_start_local:
        arguments["earliest_start_local"] = context.earliest_start_local
    if context.leave_by_local:
        arguments["leave_by_local"] = context.leave_by_local
    if context.facility_timezone:
        arguments["timezone_name"] = context.facility_timezone
    return {"name": ToolName.GET_AVAILABLE_OPTIONS.value, "arguments": arguments}


def _exception_call(understanding: Understanding, context: ConversationContext, shipment_id: str | None) -> dict:
    return {
        "name": ToolName.CREATE_DRIVER_EXCEPTION.value,
        "arguments": {
            "shipment_id": shipment_id,
            "driver_id": str(context.driver_id) if context.driver_id else None,
            "exception_type": understanding.exception_type or "delay",
            "description": understanding.raw_message,
        },
    }


def _selected_option(context: ConversationContext) -> PresentedOption | None:
    return resolve_option(context, context.selected_option_index)


def _apply_tool_result(context: ConversationContext, result: ToolResult) -> None:
    context.last_tool_result = {"name": result.name, "success": result.success, "data": result.data}
    data = result.data
    if result.name == ToolName.GET_AVAILABLE_OPTIONS.value and result.success:
        context.presented_options = [PresentedOption.model_validate(item) for item in data.get("options", [])]
        context.selected_option_index = None
    if result.name == ToolName.CREATE_PROPOSAL.value and result.success:
        proposal_id = data.get("proposal_id")
        if proposal_id:
            from uuid import UUID

            context.proposal_id = UUID(str(proposal_id))
            slot_id = data.get("slot_id")
            if slot_id:
                context.proposal_slot_id = UUID(str(slot_id))
    if result.name == ToolName.RECORD_ETA_UPDATE.value and result.success:
        raw_eta = data.get("new_eta")
        if raw_eta:
            context.latest_eta = raw_eta
        source = data.get("eta_source")
        if source:
            context.eta_authority = str(source)
    if result.name == ToolName.EVALUATE_FEASIBILITY.value and result.success:
        if "eta_window_passed" in data:
            context.original_appointment_feasible = bool(data.get("eta_window_passed"))
    if result.name == ToolName.CREATE_DRIVER_EXCEPTION.value and result.success:
        from uuid import UUID

        exception_id = data.get("id")
        if exception_id:
            context.exception_id = UUID(str(exception_id))
    if result.name == ToolName.ACCEPT_PROPOSAL.value and result.success and data.get("proposal_id"):
        from uuid import UUID

        context.proposal_id = UUID(str(data["proposal_id"]))


def _maybe_escalate(
    understanding: Understanding,
    context: ConversationContext,
    results: list[ToolResult],
) -> tuple[bool, str | None]:
    no_safe_option = False
    operational_conflict = False
    option_detail: str | None = None
    for result in results:
        if result.name == ToolName.GET_AVAILABLE_OPTIONS.value and result.success:
            feasible = int(result.data.get("feasible_count") or 0)
            unfiltered = int(result.data.get("unfiltered_feasible_count") or 0)
            if unfiltered == 0 and feasible == 0:
                no_safe_option = True
                option_detail = result.data.get("rejection_summary") or result.data.get("constraint_note")
        if result.error_code in {"conflict", "stale"} and understanding.intent == ConversationIntent.ASK_OPTIONS:
            operational_conflict = True
    outside_authority = any(
        phrase in understanding.raw_message.lower()
        for phrase in ("legal", "contract penalty", "insurance claim", "safety override")
    )
    escalate, reason = should_escalate(
        wants_human=understanding.wants_human or understanding.intent == ConversationIntent.HUMAN_ESCALATION,
        no_safe_option=no_safe_option,
        unresolved_ambiguity=False,
        operational_conflict=operational_conflict,
        outside_authority=outside_authority,
    )
    if escalate and no_safe_option and option_detail:
        reason = f"{reason} {option_detail}".strip()
    return escalate, reason


def _bind_bare_option_index(understanding: Understanding, context: ConversationContext) -> Understanding:
    """Map a bare reply like '2' onto a previously presented numbered option list."""
    if understanding.option_index is not None or not context.presented_options:
        return understanding
    stripped = understanding.raw_message.strip()
    if not re.fullmatch(r"\d{1,2}", stripped):
        return understanding
    index = int(stripped)
    if any(item.index == index for item in context.presented_options):
        understanding.option_index = index
    return understanding


def _resume_pending(understanding: Understanding, context: ConversationContext) -> Understanding:
    lowered = understanding.raw_message.lower().strip()
    affirmative = is_informal_affirmative(understanding.raw_message)
    if context.pending_clarification == "options" and (
        affirmative
        or understanding.intent == ConversationIntent.ASK_OPTIONS
        or understanding.asks_options
    ):
        if understanding.intent != ConversationIntent.ACCEPT_PROPOSAL or affirmative:
            if not (understanding.confirm and "confirm" in lowered):
                understanding.intent = ConversationIntent.ASK_OPTIONS
                understanding.asks_options = True
                context.pending_clarification = None
                context.pending_intent = None
                return understanding
    if context.pending_intent is None:
        return understanding
    subject_change = {
        ConversationIntent.ASK_STATUS,
        ConversationIntent.ASK_APPOINTMENT,
        ConversationIntent.ASK_OPTIONS,
        ConversationIntent.ASK_FEASIBILITY_STATUS,
        ConversationIntent.ASK_FACILITY_SCHEDULE,
        ConversationIntent.ACCEPT_PROPOSAL,
        ConversationIntent.REJECT_PROPOSAL,
        ConversationIntent.HUMAN_ESCALATION,
        ConversationIntent.UPDATE_ETA,
        ConversationIntent.REPORT_DELAY,
        ConversationIntent.REPORT_EXCEPTION,
        ConversationIntent.PROPOSE_CHANGE,
        ConversationIntent.CANCEL_REQUEST,
        ConversationIntent.REQUEST_DRIVER_REASSIGNMENT,
    }
    if understanding.intent in subject_change and understanding.intent != context.pending_intent:
        context.pending_clarification = None
        context.pending_intent = None
        context.pending_delay_minutes = None
        return understanding
    if understanding.intent == ConversationIntent.CLARIFICATION_REQUIRED or understanding.shipment_hint:
        understanding.intent = context.pending_intent
        if understanding.delay_minutes is None:
            understanding.delay_minutes = context.pending_delay_minutes
    return understanding


def _is_fresh_availability_query(message: str) -> bool:
    lowered = message.lower()
    return bool(
        re.search(
            r"\b(?:available|availability|next slot|next available|what slots|"
            r"find (?:me )?(?:a |another )?slot|check availability|"
            r"when can i (?:get in|come)|anything (?:later|after|open)|"
            r"earliest available|do you have anything)\b",
            lowered,
        )
    )


def _bind_presented_selection(understanding: Understanding, context: ConversationContext) -> Understanding:
    if not context.presented_options:
        return understanding
    if understanding.intent in {
        ConversationIntent.ASK_STATUS,
        ConversationIntent.ASK_APPOINTMENT,
        ConversationIntent.ASK_FACILITY_SCHEDULE,
        ConversationIntent.ASK_FEASIBILITY_STATUS,
        ConversationIntent.HUMAN_ESCALATION,
        ConversationIntent.REQUEST_DRIVER_REASSIGNMENT,
        ConversationIntent.UPDATE_ETA,
        ConversationIntent.REPORT_DELAY,
        ConversationIntent.REPORT_EXCEPTION,
        ConversationIntent.REJECT_PROPOSAL,
        ConversationIntent.CANCEL_REQUEST,
    }:
        return understanding
    if understanding.earliest_start_local and understanding.intent == ConversationIntent.ASK_OPTIONS:
        return understanding
    if understanding.intent == ConversationIntent.ASK_OPTIONS and _is_fresh_availability_query(
        understanding.raw_message
    ):
        return understanding
    has_selection = bool(
        understanding.option_index
        or understanding.option_preference
        or understanding.option_clock_local
    )
    if not has_selection:
        return understanding
    if understanding.intent not in {
        ConversationIntent.ASK_STATUS,
        ConversationIntent.ASK_APPOINTMENT,
        ConversationIntent.ASK_FACILITY_SCHEDULE,
        ConversationIntent.ASK_FEASIBILITY_STATUS,
        ConversationIntent.HUMAN_ESCALATION,
        ConversationIntent.UPDATE_ETA,
        ConversationIntent.REPORT_DELAY,
        ConversationIntent.REPORT_EXCEPTION,
        ConversationIntent.REJECT_PROPOSAL,
        ConversationIntent.CANCEL_REQUEST,
    }:
        understanding.intent = (
            ConversationIntent.ACCEPT_PROPOSAL if understanding.confirm else ConversationIntent.PROPOSE_CHANGE
        )
        understanding.asks_options = False
    option, _question = match_presented_option(
        context,
        option_index=understanding.option_index,
        preference=understanding.option_preference,
        clock_hhmm=understanding.option_clock_local,
    )
    if option is not None:
        understanding.option_index = option.index
    return understanding


def _clarification_turn(
    intent: ConversationIntent,
    confidence: float,
    context: ConversationContext,
    question: str,
    pending: str | None = None,
    results: list[ToolResult] | None = None,
) -> AgentTurn:
    context.pending_clarification = pending or context.pending_clarification or "general"
    if context.pending_intent is None:
        context.pending_intent = intent
    return AgentTurn(
        intent=ConversationIntent.CLARIFICATION_REQUIRED,
        confidence=confidence,
        response=question,
        status="clarification",
        tool_calls=results or [],
        requires_clarification=True,
        context=context,
        metadata=public_metadata({"requested_intent": intent.value}),
    )


def _completed_turn(
    intent: ConversationIntent,
    confidence: float,
    context: ConversationContext,
    results: list[ToolResult],
    response: str,
    *,
    requires_human: bool = False,
    status: str = "ok",
) -> AgentTurn:
    context.pending_clarification = None
    context.pending_intent = None
    context.pending_delay_minutes = None
    return AgentTurn(
        intent=intent,
        confidence=confidence,
        response=response,
        status=status,
        tool_calls=results,
        requires_human=requires_human,
        context=context,
        metadata=public_metadata({"confidence": confidence}),
    )


def _store_driver_constraints(understanding: Understanding, context: ConversationContext) -> None:
    if understanding.earliest_start_local:
        context.earliest_start_local = understanding.earliest_start_local
    if understanding.leave_by_local:
        context.leave_by_local = understanding.leave_by_local
    if understanding.repair_duration_minutes is not None:
        context.repair_duration_minutes = understanding.repair_duration_minutes
    if understanding.exception_type:
        context.exception_type = understanding.exception_type
    if understanding.eta_local:
        context.explicit_eta_local = understanding.eta_local
    if understanding.delay_minutes is not None:
        context.reported_delay_minutes = understanding.delay_minutes


def _leave_by_rejected_turn(
    understanding: Understanding,
    context: ConversationContext,
    option: PresentedOption,
    leave_by: str,
) -> AgentTurn:
    compatible = [
        item
        for item in context.presented_options
        if slot_ends_on_or_before(item.end_time, leave_by, context.facility_timezone) is True
    ]
    leave_label = _display_hhmm(leave_by)
    option_label = option.label or f"option {option.index}"
    if compatible:
        numbered = ", ".join(str(item.index) for item in compatible)
        question = (
            f"Option {option.index} ({option_label}) ends after {leave_label}, "
            "so I cannot propose it with your leave-by time. "
            f"Options that end by {leave_label}: {numbered}. "
            "Which numbered option should I use?"
        )
    else:
        question = (
            f"Option {option.index} ({option_label}) ends after {leave_label}, "
            "so I cannot propose it with your leave-by time. "
            "None of the currently shown options finish by then. "
            "Would you like me to look for other appointment options?"
        )
        context.pending_clarification = "options"
        context.pending_intent = ConversationIntent.ASK_OPTIONS
    return AgentTurn(
        intent=ConversationIntent.PROPOSE_CHANGE,
        confidence=understanding.confidence,
        response=question,
        status="constraint",
        requires_clarification=True,
        context=context,
        metadata=public_metadata(
            {
                "leave_by_local": leave_by,
                "rejected_option_index": option.index,
            }
        ),
    )


def _display_hhmm(value: str) -> str:
    hour_s, _, minute_s = value.partition(":")
    try:
        hour = int(hour_s)
        minute = int(minute_s or "0")
    except ValueError:
        return value
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}"


def _context_summary(context: ConversationContext) -> str:
    return (
        f"thread_id={context.thread_id} shipment_id={context.shipment_id} "
        f"proposal_id={context.proposal_id} options={len(context.presented_options)}"
    )
