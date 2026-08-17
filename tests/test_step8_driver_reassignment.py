"""Driver reassignment intent and ETA baseline regression tests."""

from __future__ import annotations

from datetime import timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationIntent
from app.models import ETAUpdate
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from tests.test_step8_conversation import _build_world, _service


DRIVER_REASSIGNMENT_PHRASES = [
    "I am not feeling well.. i need another driver?",
    "I need another driver",
    "I'm sick and cannot drive",
    "Can you change my driver?",
    "I need a different driver",
    "Driver unavailable — need a replacement",
]


class TestDriverReassignmentIntent:
    @pytest.mark.parametrize("message", DRIVER_REASSIGNMENT_PHRASES)
    def test_classifies_driver_reassignment(self, message: str) -> None:
        parsed = parse_understanding(message)
        assert parsed.intent == ConversationIntent.REQUEST_DRIVER_REASSIGNMENT, message

    def test_driver_reassignment_escalates_without_generic_clarification(self, db_session: Session) -> None:
        world = _build_world(db_session, eta_delta=timedelta(hours=2))
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I am not feeling well.. i need another driver?"),
        )
        assert result.intent == ConversationIntent.REQUEST_DRIVER_REASSIGNMENT.value
        assert "Could you tell me what you need help with" not in result.response
        assert result.requires_human is True
        assert any(call.name == "request_human_escalation" and call.success for call in result.tool_calls)


class TestRelativeDelayBaseline:
    def test_two_hours_late_anchors_to_planned_arrival_not_appointment_slot(self, db_session: Session) -> None:
        world = _build_world(db_session, eta_delta=timedelta(hours=2))
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        dispatch = (
            db_session.query(ETAUpdate)
            .filter(ETAUpdate.shipment_id == world["shipment"].id)
            .order_by(ETAUpdate.update_timestamp.asc(), ETAUpdate.id.asc())
            .first()
        )
        assert dispatch is not None
        planned = dispatch.new_eta
        if planned.tzinfo is None:
            planned = planned.replace(tzinfo=timezone.utc)

        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I will be 2 hours late"),
        )
        assert result.intent == ConversationIntent.UPDATE_ETA.value
        assert any(call.name == "record_eta_update" and call.success for call in result.tool_calls)

        latest = (
            db_session.query(ETAUpdate)
            .filter(ETAUpdate.shipment_id == world["shipment"].id)
            .order_by(ETAUpdate.update_timestamp.desc(), ETAUpdate.id.desc())
            .first()
        )
        assert latest is not None
        new_eta = latest.new_eta
        if new_eta.tzinfo is None:
            new_eta = new_eta.replace(tzinfo=timezone.utc)
        assert latest.previous_eta is not None
        assert new_eta == planned + timedelta(hours=2)
