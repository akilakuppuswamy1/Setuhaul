"""Regression tests for Step 8 P1 delay, options, and confirmation-status routing."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationIntent
from app.models import Appointment
from app.models.enums import AppointmentStatus
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from tests.test_step8_conversation import _build_world, _service


class TestP1DelayRouting:
    def test_assignment_delay_with_traffic_records_eta(self, db_session: Session) -> None:
        world = _build_world(db_session, eta_delta=__import__("datetime").timedelta(hours=2))
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be two hours late because of traffic."),
        )
        assert result.intent == ConversationIntent.UPDATE_ETA.value
        assert any(call.name == "record_eta_update" and call.success for call in result.tool_calls)
        assert all(call.name != "create_driver_exception" for call in result.tool_calls)

    def test_delay_phrases_parse_duration(self) -> None:
        cases = [
            ("I'll be two hours late because of traffic.", 120),
            ("I'm two hours late.", 120),
            ("Traffic is bad, I'll be two hours late.", 120),
            ("I'm running two hours behind.", 120),
            ("I will arrive two hours late.", 120),
            ("I'll be 2 hours late because of traffic.", 120),
            ("I'm going to be 90 minutes late.", 90),
            ("I'll be 1.5 hours late.", 90),
            ("I'll be thirty minutes late.", 30),
        ]
        for message, minutes in cases:
            parsed = parse_understanding(message)
            assert parsed.intent in {ConversationIntent.UPDATE_ETA, ConversationIntent.REPORT_DELAY}, message
            assert parsed.delay_minutes == minutes, message
            assert parsed.intent != ConversationIntent.REPORT_EXCEPTION, message


class TestP1OptionsRouting:
    def test_cant_make_with_options_question(self, db_session: Session) -> None:
        world = _build_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I can't make my appointment. What options do I have?"),
        )
        assert result.intent == ConversationIntent.ASK_OPTIONS.value
        assert any(call.name == "get_available_options" and call.success for call in result.tool_calls)
        assert all(call.name != "create_proposal" for call in result.tool_calls)
        assert all(call.name != "accept_proposal" for call in result.tool_calls)
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

    def test_options_phrase_intents(self) -> None:
        messages = [
            "I can't make my appointment. What options do I have?",
            "I can't make my appointment. What options are available?",
            "I can't make it. Can I get another slot?",
            "I missed my appointment, what options do I have?",
            "What other slots are available?",
            "Can I come later?",
            "I missed my appointment, what can I do?",
            "Show me other appointment options.",
        ]
        for message in messages:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_OPTIONS, message

    def test_pure_cannot_make_remains_exception(self) -> None:
        parsed = parse_understanding("I can't make my appointment.")
        assert parsed.intent == ConversationIntent.REPORT_EXCEPTION


class TestP1ConfirmationStatus:
    def _thread_with_proposal(self, db_session: Session):
        world = _build_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Can you find another appointment?"),
        )
        chosen = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The second one works."),
        )
        assert chosen.proposal_id is not None
        return world, service, created, chosen

    def test_status_questions_do_not_accept(self, db_session: Session) -> None:
        _world, service, created, _chosen = self._thread_with_proposal(db_session)
        before_confirmed = (
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count()
        )
        before_requested = (
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.REQUESTED).count()
        )
        questions = [
            "Has it been confirmed?",
            "Is it confirmed?",
            "Did it get confirmed?",
            "Can you check if it's confirmed?",
            "Has my appointment been confirmed?",
            "Was that slot confirmed?",
            "Is my proposal confirmed?",
            "Just tell me whether it is confirmed.",
            "Check whether it's confirmed, don't change anything.",
            "Don't confirm it yet.",
        ]
        for message in questions:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_STATUS, message
            assert parsed.confirm is False, message
            result = service.handle_message(created.thread_id, ConversationMessageRequest(message=message))
            assert result.intent == ConversationIntent.ASK_STATUS.value, message
            assert all(call.name != "accept_proposal" for call in result.tool_calls), message
            assert any(call.name == "get_proposal" for call in result.tool_calls), message
        after_confirmed = (
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count()
        )
        after_requested = (
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.REQUESTED).count()
        )
        assert after_confirmed == before_confirmed == 0
        assert after_requested == before_requested == 1

    def test_explicit_confirm_still_allocates(self, db_session: Session) -> None:
        _world, service, created, _chosen = self._thread_with_proposal(db_session)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Confirm it."),
        )
        assert result.intent == ConversationIntent.ACCEPT_PROPOSAL.value
        assert any(call.name == "accept_proposal" and call.success for call in result.tool_calls)
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 1

    def test_explicit_confirm_phrases(self) -> None:
        for message in (
            "Confirm it.",
            "Please confirm it.",
            "Yes, confirm it.",
            "Go ahead and confirm.",
            "I want to confirm this.",
        ):
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ACCEPT_PROPOSAL, message
            assert parsed.confirm is True, message

    def test_mixed_status_then_confirm_is_not_substring_accept(self) -> None:
        parsed = parse_understanding("Has it been confirmed? If not, confirm it.")
        assert parsed.intent == ConversationIntent.ASK_STATUS
        assert parsed.confirm is False
