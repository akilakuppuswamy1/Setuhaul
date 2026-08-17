"""Regression tests for appointment option persistence and numeric selection."""

from __future__ import annotations

from datetime import timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.ai.conversation.context import context_from_thread, snapshot_context
from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationContext, ConversationIntent
from app.models import ETAUpdate
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from app.services.conversations import ChatMessageService
from tests.test_step8_chat_constraints import _build_evening_world
from tests.test_step8_conversation import _build_world, _service


def _tool_names(result) -> list[str]:
    return [call.name for call in result.tool_calls]


class TestContextPendingStateMerge:
    def test_completed_turn_clears_stale_pending_intent(self) -> None:
        thread_id = uuid4()
        context = ConversationContext(thread_id=thread_id)
        context.pending_clarification = "options"
        context.pending_intent = ConversationIntent.PROPOSE_CHANGE
        cleared = snapshot_context(context)
        cleared["pending_clarification"] = None
        cleared["pending_intent"] = None
        cleared["presented_options"] = [
            {
                "index": 1,
                "slot_id": str(uuid4()),
                "dock_id": None,
                "start_time": "2026-08-14T01:00:00+00:00",
                "end_time": "2026-08-14T02:00:00+00:00",
                "label": "8:00 PM – 9:00 PM",
            }
        ]
        rebuilt = context_from_thread(
            thread_id=thread_id,
            driver_id=None,
            shipment_id=None,
            exception_id=None,
            message_metadata=[cleared],
        )
        assert rebuilt.pending_clarification is None
        assert rebuilt.pending_intent is None
        assert len(rebuilt.presented_options) == 1


class TestOptionListPersistenceAndSelection:
    def test_yes_then_bare_two_selects_persisted_option(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The second one works, but I need to leave by 9:30 PM."),
        )
        options_turn = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="yes"),
        )
        assert "get_available_options" in _tool_names(options_turn)
        assert options_turn.metadata is not None
        assert len(options_turn.metadata.get("presented_options") or []) >= 2

        selected = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="2"),
        )
        assert "I don't currently have a list of appointment options" not in selected.response
        assert any(call.name == "create_proposal" and call.success for call in selected.tool_calls)
        assert selected.proposal_id is not None

    def test_bare_two_without_option_list_asks_for_clarification(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="2"),
        )
        assert result.requires_clarification is True
        assert "create_proposal" not in _tool_names(result)

    def test_context_rebuild_keeps_presented_options_for_selection(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        options_turn = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Anything after 7?"),
        )
        assert "get_available_options" in _tool_names(options_turn)
        assert len(options_turn.metadata.get("presented_options") or []) >= 2

        history = ChatMessageService(db_session).list_recent(created.thread_id, limit=40)
        rebuilt = context_from_thread(
            thread_id=created.thread_id,
            driver_id=world["driver"].id,
            shipment_id=world["shipment"].id,
            exception_id=None,
            message_metadata=[item.metadata for item in history],
        )
        assert len(rebuilt.presented_options) >= 2
        assert rebuilt.pending_intent is None
        assert rebuilt.pending_clarification is None

        selected = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="2"),
        )
        assert "I don't currently have a list of appointment options" not in selected.response
        assert any(call.name == "create_proposal" and call.success for call in selected.tool_calls)


class TestEtaDelaySemantics:
    def test_supposed_six_thirty_to_eight_thirty_records_two_hour_delay(self, db_session: Session) -> None:
        world = _build_world(db_session, eta_delta=timedelta(hours=2))
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        parsed = parse_understanding(
            "I'm going to be 2 hours late. I was supposed to reach by 6:30 PM, "
            "but I'll reach around 8:30 PM because of traffic."
        )
        assert parsed.delay_minutes == 120
        assert parsed.eta_local == "20:30"
        assert parsed.original_appointment_local == "18:30"

        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message=(
                    "I'm going to be 2 hours late. I was supposed to reach by 6:30 PM, "
                    "but I'll reach around 8:30 PM because of traffic."
                )
            ),
        )
        assert result.intent == ConversationIntent.UPDATE_ETA.value
        assert any(call.name == "record_eta_update" and call.success for call in result.tool_calls)
        assert "do not match" not in result.response

        latest = (
            db_session.query(ETAUpdate)
            .filter(ETAUpdate.shipment_id == world["shipment"].id)
            .order_by(ETAUpdate.update_timestamp.desc())
            .first()
        )
        assert latest is not None
        new_eta = latest.new_eta
        if new_eta.tzinfo is None:
            new_eta = new_eta.replace(tzinfo=timezone.utc)
        assert new_eta.hour == 20
        assert new_eta.minute == 30

    def test_feasible_original_appointment_does_not_force_options(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        delay_turn = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message=(
                    "I'll be two hours late. I was supposed to reach by 6:30 PM, "
                    "but I'll reach around 8:30 PM."
                )
            ),
        )
        assert delay_turn.intent == ConversationIntent.UPDATE_ETA.value
        assert "get_available_options" not in _tool_names(delay_turn)
