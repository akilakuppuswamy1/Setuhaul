"""Conversation agent: language in, allowlisted tools out, deterministic services remain authoritative."""

from __future__ import annotations

from app.ai.conversation.context import resolve_option, resolve_shipment
from app.ai.conversation.escalation import driver_escalation_message, should_escalate
from app.ai.conversation.formatter import format_turn, public_metadata
from app.ai.conversation.models import (
    AgentTurn,
    ConversationContext,
    ConversationIntent,
    PresentedOption,
    ToolResult,
    Understanding,
)
from app.ai.conversation.provider import FakeLLMProvider, LLMProvider
from app.ai.conversation.tools import IRREVERSIBLE_TOOLS, ToolName

_SHIPMENT_REQUIRED = {
    ConversationIntent.REPORT_DELAY,
    ConversationIntent.UPDATE_ETA,
    ConversationIntent.REPORT_EXCEPTION,
    ConversationIntent.ASK_STATUS,
    ConversationIntent.ASK_OPTIONS,
    ConversationIntent.PROPOSE_CHANGE,
    ConversationIntent.ACCEPT_PROPOSAL,
    ConversationIntent.REJECT_PROPOSAL,
    ConversationIntent.CANCEL_REQUEST,
}


class ConversationAgent:
    def __init__(self, executor, provider: LLMProvider | None = None) -> None:
        self._executor = executor
        self._provider = provider or FakeLLMProvider()

    def handle(self, message: str, context: ConversationContext) -> AgentTurn:
        understanding = self._provider.understand(message, _context_summary(context))
        if understanding.wants_human:
            understanding.intent = ConversationIntent.HUMAN_ESCALATION
        understanding = _resume_pending(understanding, context)
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
        if plan.clarification:
            context.pending_clarification = plan.pending
            return _clarification_turn(intent, understanding.confidence, context, plan.clarification)

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
            context.escalation_reason = reason or context.escalation_reason
            response = driver_escalation_message(context.escalation_reason)
            return _completed_turn(
                ConversationIntent.HUMAN_ESCALATION,
                understanding.confidence,
                context,
                results,
                response,
                requires_human=True,
                status="escalated",
            )

        response = format_turn(results=results)
        status = "ok"
        if any(not item.success for item in results):
            status = results[-1].error_code or "error"
        return _completed_turn(intent, understanding.confidence, context, results, response, status=status)

    def _handle_option_intent(
        self,
        understanding: Understanding,
        context: ConversationContext,
    ) -> AgentTurn | None:
        if understanding.option_index is not None:
            option = resolve_option(context, understanding.option_index)
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
    if intent == ConversationIntent.CLARIFICATION_REQUIRED:
        return _Plan(clarification="Could you tell me what you need help with for this shipment?")
    if intent in {ConversationIntent.UPDATE_ETA, ConversationIntent.REPORT_DELAY}:
        if understanding.delay_minutes is None and understanding.new_eta is None:
            return _Plan(clarification="How late will you be, in minutes or hours?")
        return _Plan(
            calls=[
                {
                    "name": ToolName.RECORD_ETA_UPDATE.value,
                    "arguments": {
                        "shipment_id": shipment_id,
                        "delay_minutes": understanding.delay_minutes,
                        "reason": understanding.raw_message,
                    },
                }
            ]
        )
    if intent == ConversationIntent.REPORT_EXCEPTION:
        return _Plan(
            calls=[
                {
                    "name": ToolName.CREATE_DRIVER_EXCEPTION.value,
                    "arguments": {
                        "shipment_id": shipment_id,
                        "driver_id": str(context.driver_id) if context.driver_id else None,
                        "exception_type": understanding.exception_type or "delay",
                        "description": understanding.raw_message,
                    },
                }
            ]
        )
    if intent == ConversationIntent.ASK_STATUS:
        return _Plan(calls=[{"name": ToolName.GET_SHIPMENT_STATUS.value, "arguments": {"shipment_id": shipment_id}}])
    if intent == ConversationIntent.ASK_OPTIONS:
        return _Plan(calls=[{"name": ToolName.GET_AVAILABLE_OPTIONS.value, "arguments": {"shipment_id": shipment_id}}])
    if intent == ConversationIntent.PROPOSE_CHANGE:
        option = _selected_option(context)
        if option is None:
            return _Plan(
                clarification=(
                    "I don't currently have a list of appointment options in this conversation. "
                    "Would you like me to find available options?"
                ),
                pending="options",
            )
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


def _plan_accept(context: ConversationContext, shipment_id: str | None, confirm: bool) -> "_Plan":
    calls: list[dict] = []
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
    for result in results:
        if result.name == ToolName.GET_AVAILABLE_OPTIONS.value and result.success:
            if int(result.data.get("feasible_count") or 0) == 0:
                no_safe_option = True
        if result.error_code in {"conflict", "stale"} and understanding.intent == ConversationIntent.ASK_OPTIONS:
            operational_conflict = True
    outside_authority = any(
        phrase in understanding.raw_message.lower()
        for phrase in ("legal", "contract penalty", "insurance claim", "safety override")
    )
    return should_escalate(
        wants_human=understanding.wants_human or understanding.intent == ConversationIntent.HUMAN_ESCALATION,
        no_safe_option=no_safe_option,
        unresolved_ambiguity=False,
        operational_conflict=operational_conflict,
        outside_authority=outside_authority,
    )


def _resume_pending(understanding: Understanding, context: ConversationContext) -> Understanding:
    lowered = understanding.raw_message.lower().strip()
    affirmative = lowered in {"yes", "yeah", "yep", "ok", "okay", "please", "please do"}
    if context.pending_clarification == "options" and (
        affirmative or understanding.intent == ConversationIntent.ASK_OPTIONS
    ):
        understanding.intent = ConversationIntent.ASK_OPTIONS
        context.pending_clarification = None
        context.pending_intent = None
        return understanding
    if context.pending_intent is None:
        return understanding
    subject_change = {
        ConversationIntent.ASK_STATUS,
        ConversationIntent.ASK_OPTIONS,
        ConversationIntent.ACCEPT_PROPOSAL,
        ConversationIntent.REJECT_PROPOSAL,
        ConversationIntent.HUMAN_ESCALATION,
        ConversationIntent.UPDATE_ETA,
        ConversationIntent.REPORT_DELAY,
        ConversationIntent.REPORT_EXCEPTION,
        ConversationIntent.PROPOSE_CHANGE,
        ConversationIntent.CANCEL_REQUEST,
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


def _clarification_turn(
    intent: ConversationIntent,
    confidence: float,
    context: ConversationContext,
    question: str,
    pending: str | None = None,
) -> AgentTurn:
    context.pending_clarification = pending or context.pending_clarification or "general"
    if context.pending_intent is None:
        context.pending_intent = intent
    return AgentTurn(
        intent=ConversationIntent.CLARIFICATION_REQUIRED,
        confidence=confidence,
        response=question,
        status="clarification",
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


def _context_summary(context: ConversationContext) -> str:
    return (
        f"thread_id={context.thread_id} shipment_id={context.shipment_id} "
        f"proposal_id={context.proposal_id} options={len(context.presented_options)}"
    )
