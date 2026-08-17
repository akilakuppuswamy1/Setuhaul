"""Conversational paraphrase matrix: compositional semantics plus deterministic tools."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationIntent
from app.models import Appointment
from app.models.enums import AppointmentStatus
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from tests.test_step8_conversation import _service
from tests.test_step8_phase1_semantics import _eta_count, _latest_eta, _local_hour_minute, _thread, _tool_names
from tests.test_step8_reschedule_flow import _build_reschedule_world

_WRITE = {"create_proposal", "accept_proposal", "reject_proposal"}

OPTIONS = [
    "Any slot available?",
    "Is there anything open?",
    "Do you have anything later?",
    "Can I get a slot?",
    "What options do I have?",
    "What's the next available?",
    "Anything after 7?",
    "Can you fit me in tonight?",
    "Is there room for me?",
    "Do you have an opening?",
    "Is there a slot?",
    "Find me a slot.",
    "Show me available slots.",
    "When can I get in?",
    "Any chance of a slot?",
    "Can I get in tonight?",
    "What's the earliest available?",
    "Anything open later?",
    "Do you have anything around then?",
    "Check availability.",
    "Could you look for an opening?",
    "What can I get?",
]

FEASIBILITY = [
    "Will it be completed by 9pm?",
    "Will it be completed by 9pm? or should i have to wait?",
    "Will I make it by 9?",
    "Will I be done by 9?",
    "Will this work by 9?",
    "Can I make the appointment by 9?",
    "Will I have to wait?",
    "Should I wait?",
    "Can I arrive before 9?",
    "Will they take me when I arrive?",
    "Do I need to wait for my slot?",
    "Can I get unloaded by 9?",
    "Will this appointment still work?",
    "Will I make my appointment by 9?",
    "Does that work?",
    "Will that work?",
    "Can I make it?",
]

STATUS = [
    "Has it been confirmed?",
    "Is it confirmed?",
    "Is my appointment booked?",
    "What's the status?",
    "What is my status?",
    "Did you book it?",
    "Have you booked it?",
    "Is my appointment confirmed?",
    "Where do I stand?",
    "Check if it's confirmed.",
    "Has my slot been booked?",
]

CONFIRMATION = [
    "Confirm it.",
    "Please confirm.",
    "Yes, confirm.",
    "Go ahead and confirm.",
    "Lock it in.",
    "Book it.",
    "Confirm that proposal.",
    "I want to confirm.",
    "Book the second option.",
    "Yes confirm the 8:30 slot.",
]

AFFIRMATIONS = [
    "yes",
    "yeah",
    "yep",
    "yes please",
    "okay",
    "okay check",
    "ok check",
    "sure",
    "please do",
    "go ahead",
    "yes, find them",
    "yeah show me",
    "please check",
    "do that",
    "that would be great",
]

SELECTION = [
    "the second one",
    "The second one works",
    "second works",
    "I'll take number two",
    "I'll take the second one.",
    "let's go with the second",
    "The later one works.",
    "The 8:30 slot works.",
    "Give me the earliest one.",
    "The first option.",
    "Let's take 8:30.",
    "That later slot works.",
    "Can I take the second one?",
    "Can I get the 8:30?",
    "yes, the later one",
    "that one works",
]

ETA = [
    "I'll be there at 8:30",
    "I should reach around 8:30",
    "Expect me around 8:30",
    "I'll arrive at 8:30",
    "I can reach by 8:30",
    "I'll reach around 8:30.",
    "I should be there by 8:30.",
    "Expect me at 8:30.",
    "I'll arrive at about 8:30 tonight.",
    "My ETA is 8:30 PM.",
    "Should be there by 8:30.",
    "I'll get there around 8:30.",
    "I can get there around 20:30.",
    "Expect me around 20:30.",
    "I'll arrive at 8.30.",
    "I'll be there at 8 30 PM.",
]

RELATIVE_DELAY = [
    "I'm two hours late",
    "I'll be about 2 hours late",
    "Running two hours behind",
    "I'll arrive 2 hours late",
    "I'll be 5 hours late.",
    "I will be late by 2 hours.",
    "Running 90 minutes behind",
    "I'm delayed by two hours",
    "I'll be two hrs late",
    "Traffic will make me 2 hours late.",
]

REPAIR = [
    "The repair will take 90 minutes.",
    "It'll take 90 minutes to repair",
    "I need 90 minutes for the tyre",
    "The repair will take an hour",
    "Tyre puncture. Repair will take 90 minutes.",
    "Got a flat. Fixing it will take 90 minutes.",
    "I need 90 minutes for repairs.",
    "Repair needs about ninety minutes.",
    "Fixing the tyre will take 90 minutes.",
    "The puncture repair will take 60 minutes.",
]

COMPOUND = [
    "I'll be two hours late, can you find me another slot?",
    "I can't make 6:30, anything later?",
    "I'll reach around 8:30, do you have anything around then?",
    "I won't make the appointment, can you find another time?",
    "Tyre problem. Show me what else is available.",
    "I'm delayed. Do you have anything later?",
    "I can't make the 6:30. Give me some options.",
    "I'll leave by 2 AM. Any slot available?",
    "Running two hours behind, I should get there around 8:30.",
    "My truck broke down. What can I do?",
]

NEGATION = [
    "Don't confirm it yet.",
    "Do not confirm.",
    "Dont confirm it.",
    "Don't book it.",
    "Do not book that.",
    "Has it been confirmed?",
    "Is it confirmed?",
    "Will it be completed by 9?",
    "Should I wait?",
    "Can I make it?",
    "Does that work?",
    "Will that work?",
]

AMBIGUOUS = [
    "8:30 slot",
    "The 8:30 slot works.",
    "8:30 slot works.",
    "the 8.30 slot works",
    "second one",
    "What's the earliest available?",
    "Do you have anything later?",
    "Can I get the 8:30?",
    "that one works",
    "repair will take 90 minutes",
]

LOCAL_TIME = [
    "8:30",
    "8.30",
    "8 30",
    "8:30 PM",
    "around 8:30",
    "about 8:30",
    "after 8",
    "before 9",
    "by 9",
    "tonight",
    "later tonight",
    "tomorrow morning",
]


def _assert_read_only(result, *, allow_eta: bool = False, allow_exception: bool = False) -> None:
    names = set(_tool_names(result))
    assert names.isdisjoint(_WRITE)
    if not allow_eta:
        assert "record_eta_update" not in names
    if not allow_exception:
        assert "create_driver_exception" not in names


class TestCategoryAOptions:
    def test_options_variants_classify(self) -> None:
        assert len(OPTIONS) >= 20
        for message in OPTIONS:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_OPTIONS, message
            assert parsed.asks_options is True, message
            assert parsed.confirm is False, message
            assert parsed.intent != ConversationIntent.CLARIFICATION_REQUIRED, message

    def test_options_invoke_get_available_options(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        for message in OPTIONS[:8]:
            thread = service.create_thread(
                ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
            )
            result = service.handle_message(thread.thread_id, ConversationMessageRequest(message=message))
            assert "get_available_options" in _tool_names(result), message
            _assert_read_only(result)
            assert "Could you tell me what you need help with" not in result.response


class TestCategoryBFeasibility:
    def test_feasibility_variants_classify(self) -> None:
        assert len(FEASIBILITY) >= 15
        for message in FEASIBILITY:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_FEASIBILITY_STATUS, message
            assert parsed.confirm is False, message
            assert parsed.intent != ConversationIntent.CLARIFICATION_REQUIRED, message
            assert parsed.intent != ConversationIntent.ACCEPT_PROPOSAL, message
            assert parsed.intent != ConversationIntent.ASK_OPTIONS, message

    def test_screenshot_case_uses_feasibility_tools(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        message = "Will it be completed by 9pm? or should i have to wait?"
        result = service.handle_message(created.thread_id, ConversationMessageRequest(message=message))
        names = _tool_names(result)
        assert "evaluate_feasibility" in names
        assert "get_appointment" in names
        _assert_read_only(result)
        assert "Could you tell me what you need help with" not in result.response
        assert "6:30 PM" in result.response or "7:00 PM" in result.response
        assert "UTC" not in result.response
        assert result.intent == ConversationIntent.ASK_FEASIBILITY_STATUS.value

    @pytest.mark.parametrize("message", FEASIBILITY[:6])
    def test_feasibility_is_read_only_downstream(self, db_session: Session, message: str) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        before = _eta_count(db_session, world["shipment"].id)
        result = service.handle_message(created.thread_id, ConversationMessageRequest(message=message))
        assert "evaluate_feasibility" in _tool_names(result), message
        _assert_read_only(result)
        assert _eta_count(db_session, world["shipment"].id) == before
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0


class TestCategoryCStatus:
    def test_status_variants_classify(self) -> None:
        assert len(STATUS) >= 10
        for message in STATUS:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_STATUS, message
            assert parsed.confirm is False, message

    def test_status_is_read_only(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="Has it been confirmed?")
        )
        names = set(_tool_names(result))
        assert "get_shipment_status" in names or "get_proposal" in names
        _assert_read_only(result)


class TestCategoryDConfirmation:
    def test_confirmation_variants_classify(self) -> None:
        assert len(CONFIRMATION) >= 10
        for message in CONFIRMATION:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ACCEPT_PROPOSAL, message
            assert parsed.confirm is True, message

    def test_confirm_without_proposal_does_not_book(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(created.thread_id, ConversationMessageRequest(message="Confirm it."))
        assert "accept_proposal" not in _tool_names(result)
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0


class TestCategoryEAffirmations:
    def test_affirmations_resume_options(self, db_session: Session) -> None:
        assert len(AFFIRMATIONS) >= 10
        world = _build_reschedule_world(db_session)
        service = _service(db_session)
        for message in AFFIRMATIONS:
            thread = service.create_thread(
                ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
            )
            first = service.handle_message(
                thread.thread_id, ConversationMessageRequest(message="I need to leave by 2 AM.")
            )
            assert first.requires_clarification is True
            result = service.handle_message(thread.thread_id, ConversationMessageRequest(message=message))
            assert "get_available_options" in _tool_names(result), message
            assert "Would you like me to find appointment options?" not in result.response, message
            assert "accept_proposal" not in _tool_names(result), message


class TestCategoryFSelection:
    def test_selection_is_not_confirmation(self) -> None:
        assert len(SELECTION) >= 15
        for message in SELECTION:
            parsed = parse_understanding(message)
            assert parsed.confirm is False or "confirm" in message.lower(), message
            if "book" not in message.lower() and "confirm" not in message.lower():
                assert parsed.intent != ConversationIntent.ACCEPT_PROPOSAL, message

    def test_second_one_creates_proposal_only(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        service.handle_message(created.thread_id, ConversationMessageRequest(message="What slots do you have?"))
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="The second one works")
        )
        assert "create_proposal" in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

    def test_earliest_available_after_options_is_not_selection(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        service.handle_message(created.thread_id, ConversationMessageRequest(message="What slots do you have?"))
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="What's the earliest available?")
        )
        assert result.intent == ConversationIntent.ASK_OPTIONS.value
        assert "get_available_options" in _tool_names(result)
        assert "create_proposal" not in _tool_names(result)


class TestCategoryGEta:
    def test_eta_variants_classify(self) -> None:
        assert len(ETA) >= 15
        for message in ETA:
            parsed = parse_understanding(message)
            assert parsed.eta_local in {"20:30", "20:00"} or parsed.intent == ConversationIntent.UPDATE_ETA, message
            if "8:30" in message or "8.30" in message or "8 30" in message or "20:30" in message:
                assert parsed.eta_local == "20:30", message
            assert parsed.intent == ConversationIntent.UPDATE_ETA, message
            assert parsed.repair_duration_minutes is None, message

    def test_explicit_eta_records_local_clock(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="I'll reach around 8:30.")
        )
        assert "record_eta_update" in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)
        latest = _latest_eta(db_session, world["shipment"].id)
        assert _local_hour_minute(latest) == (20, 30)


class TestCategoryHRelativeDelay:
    def test_relative_delay_variants(self) -> None:
        assert len(RELATIVE_DELAY) >= 10
        for message in RELATIVE_DELAY:
            parsed = parse_understanding(message)
            assert parsed.delay_minutes is not None, message
            assert parsed.intent in {ConversationIntent.UPDATE_ETA, ConversationIntent.REPORT_DELAY}, message
            assert parsed.eta_local is None or parsed.delay_minutes is not None, message

    def test_two_hours_late_records_relative_eta(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="I'll be two hours late")
        )
        assert "record_eta_update" in _tool_names(result)
        assert parse_understanding("I'll be two hours late").delay_minutes == 120


class TestCategoryIRepair:
    def test_repair_is_not_eta(self) -> None:
        assert len(REPAIR) >= 10
        for message in REPAIR:
            parsed = parse_understanding(message)
            assert parsed.repair_duration_minutes is not None, message
            assert parsed.eta_local is None, message
            assert parsed.delay_minutes is None, message
            assert parsed.intent == ConversationIntent.REPORT_EXCEPTION, message

    def test_repair_does_not_write_eta(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        before = _eta_count(db_session, world["shipment"].id)
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="The repair will take 90 minutes.")
        )
        assert "record_eta_update" not in _tool_names(result)
        assert _eta_count(db_session, world["shipment"].id) == before
        assert "create_driver_exception" in _tool_names(result)


class TestCategoryJCompound:
    def test_compound_classifications(self) -> None:
        assert len(COMPOUND) >= 10
        late_options = parse_understanding("I'll be two hours late, can you find me another slot?")
        assert late_options.delay_minutes == 120
        assert late_options.asks_options is True
        assert late_options.intent == ConversationIntent.ASK_OPTIONS
        missed = parse_understanding("I can't make 6:30, anything later?")
        assert missed.cannot_make_appointment is True
        assert missed.asks_options is True
        eta_options = parse_understanding("I'll reach around 8:30, do you have anything around then?")
        assert eta_options.eta_local == "20:30"
        assert eta_options.asks_options is True

    def test_late_and_options_continue(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be two hours late, can you find me another slot?"),
        )
        names = _tool_names(result)
        assert "record_eta_update" in names
        assert "get_available_options" in names
        assert "accept_proposal" not in names

    def test_cannot_make_and_later(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="I can't make 6:30, anything later?")
        )
        names = _tool_names(result)
        assert "get_available_options" in names
        assert "create_driver_exception" in names
        assert "accept_proposal" not in names


class TestCategoryKNegation:
    def test_negation_never_confirms(self) -> None:
        assert len(NEGATION) >= 10
        for message in NEGATION:
            parsed = parse_understanding(message)
            assert parsed.confirm is False, message
            assert parsed.intent != ConversationIntent.ACCEPT_PROPOSAL, message

    def test_dont_confirm_after_proposal(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        service.handle_message(created.thread_id, ConversationMessageRequest(message="What slots do you have?"))
        service.handle_message(created.thread_id, ConversationMessageRequest(message="The second one works"))
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="Don't confirm it yet.")
        )
        assert "accept_proposal" not in _tool_names(result)
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0


class TestCategoryLAmbiguous:
    def test_clock_slot_is_not_option_index_thirty(self) -> None:
        assert len(AMBIGUOUS) >= 10
        for message in ("8:30 slot", "The 8:30 slot works.", "8:30 slot works.", "the 8.30 slot works"):
            parsed = parse_understanding(message)
            assert parsed.option_index != 30, message
            assert parsed.eta_local is None, message

    def test_repair_take_is_not_selection(self) -> None:
        parsed = parse_understanding("repair will take 90 minutes")
        assert parsed.repair_duration_minutes == 90
        assert parsed.option_index is None
        assert parsed.intent == ConversationIntent.REPORT_EXCEPTION

    def test_duplicate_clock_asks_numbered_option(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        service.handle_message(created.thread_id, ConversationMessageRequest(message="What slots do you have?"))
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="The 8:30 slot works.")
        )
        assert result.requires_clarification is True
        assert "create_proposal" not in _tool_names(result)
        assert "which numbered option" in result.response.lower()


class TestCategoryMLocalTime:
    def test_clock_shapes_and_local_display(self) -> None:
        assert len(LOCAL_TIME) >= 10
        assert parse_understanding("I'll arrive at 8.30.").eta_local == "20:30"
        assert parse_understanding("I'll be there at 8 30 PM.").eta_local == "20:30"
        assert parse_understanding("Anything after 8?").earliest_start_local == "20:00"
        assert parse_understanding("Will I be done by 9?").completion_by_local == "21:00"
        assert parse_understanding("Can I arrive before 9?").completion_by_local == "21:00"
        tonight = parse_understanding("Can you fit me in tonight?")
        assert tonight.intent == ConversationIntent.ASK_OPTIONS

    def test_driver_facing_times_are_chicago_local(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="When is my appointment?")
        )
        assert "6:30 PM" in result.response
        assert "00:30 UTC" not in result.response
        options = service.handle_message(
            created.thread_id, ConversationMessageRequest(message="Any slot available?")
        )
        assert "UTC" not in options.response
        assert "8:30 PM" in options.response


class TestAcceptanceScreenshotAndControls:
    def test_questions_do_not_confirm_pending_proposal(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        service.handle_message(created.thread_id, ConversationMessageRequest(message="What slots do you have?"))
        service.handle_message(created.thread_id, ConversationMessageRequest(message="The first option."))
        for message in (
            "Will it be completed by 9?",
            "Is it confirmed?",
            "Should I wait?",
            "Can I make it?",
            "Does that work?",
            "Will that work?",
        ):
            result = service.handle_message(created.thread_id, ConversationMessageRequest(message=message))
            assert "accept_proposal" not in _tool_names(result), message
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0
