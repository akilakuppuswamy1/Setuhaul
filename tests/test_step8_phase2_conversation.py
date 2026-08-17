"""Phase 2 conversational assignment gaps: options, resume, selection, status, times."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.ai.conversation.formatter import format_options, format_turn
from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationIntent, PresentedOption, ToolResult
from app.models import Appointment
from app.models.enums import AppointmentStatus, AppointmentSlotStatus
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from tests.test_step8_conversation import _service
from tests.test_step8_phase1_semantics import _latest_eta, _local_hour_minute, _thread, _tool_names
from tests.test_step8_reschedule_flow import _build_closed_world, _build_reschedule_world


_NATURAL_OPTIONS = [
    "Any slot available?",
    "Is there any slot?",
    "Do you have a slot?",
    "Any appointment available?",
    "Can you find me a slot?",
    "Show me the available slots.",
    "What slots do you have?",
    "When can I come?",
    "What's the next available appointment?",
    "Can you check availability?",
    "Anything after 7?",
    "Do you have anything later?",
    "What can you offer me?",
    "Give me some options.",
    "Could you look for an opening?",
]


class TestNaturalOptionsRequests:
    def test_unlisted_and_listed_paraphrases_are_ask_options(self) -> None:
        for message in _NATURAL_OPTIONS:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_OPTIONS, message
            assert parsed.intent != ConversationIntent.CLARIFICATION_REQUIRED, message

    def test_any_slot_available_does_not_ask_whether_they_want_options(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Any slot available?"),
        )
        assert result.intent == ConversationIntent.ASK_OPTIONS.value
        assert "get_available_options" in _tool_names(result)
        assert "Would you like me to find appointment options?" not in result.response
        assert "create_proposal" not in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)


class TestInformalPendingResume:
    def test_informal_yes_resumes_pending_options(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        first = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I need to leave by 2 AM."),
        )
        assert first.requires_clarification is True
        assert "options" in first.response.lower()
        affirmatives = [
            "yes please",
            "okay check",
            "ok check",
            "sure",
            "please do",
            "go ahead",
            "yes, find them",
            "show me",
            "check availability",
            "that works",
            "fine",
        ]
        parsed_yes = parse_understanding("yes please")
        _ = parsed_yes
        for message in affirmatives:
            thread = service.create_thread(
                ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
            )
            service.handle_message(
                thread.thread_id,
                ConversationMessageRequest(message="I need to leave by 2 AM."),
            )
            result = service.handle_message(
                thread.thread_id,
                ConversationMessageRequest(message=message),
            )
            assert "get_available_options" in _tool_names(result), message
            assert "Would you like me to find appointment options?" not in result.response, message
            assert "accept_proposal" not in _tool_names(result), message


class TestLeaveByDoesNotSuppressOptions:
    def test_leave_by_then_options_in_same_message(self, db_session: Session) -> None:
        parsed = parse_understanding("I'll leave by 2 AM. Any slot available?")
        assert parsed.leave_by_local == "02:00"
        assert parsed.intent == ConversationIntent.ASK_OPTIONS
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll leave by 2 AM. Any slot available?"),
        )
        assert result.intent == ConversationIntent.ASK_OPTIONS.value
        assert "get_available_options" in _tool_names(result)
        assert "Would you like me to find appointment options?" not in result.response
        assert result.metadata is not None
        assert result.metadata.get("leave_by_local") == "02:00"
        assert "create_proposal" not in _tool_names(result)


class TestOriginalAppointmentCommunication:
    def test_missed_original_explains_local_times(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll reach around 8:30 PM."),
        )
        assert "6:30 PM" in result.response
        assert "8:30 PM" in result.response
        assert "no longer feasible" in result.response.lower()
        assert "T" not in result.response.split("ETA")[-1] if "ETA" in result.response else True
        assert "2026-08" not in result.response
        assert "create_proposal" not in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)

    def test_original_still_feasible(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be 15 minutes late."),
        )
        assert "still works" in result.response.lower()

    def test_early_arrival_waiting(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll reach around 5:45 PM."),
        )
        assert "still works" in result.response.lower()
        assert "wait" in result.response.lower()
        latest = _latest_eta(db_session, world["shipment"].id)
        assert _local_hour_minute(latest) == (17, 45)

    def test_no_feasible_options_escalates_without_booking(self, db_session: Session) -> None:
        world = _build_closed_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Any slot available?"),
        )
        assert "get_available_options" in _tool_names(result)
        assert "create_proposal" not in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)
        assert result.requires_human is True
        assert "confirmed" not in result.response.lower()


class TestEtaAndOptionsAreLocal:
    def test_recorded_eta_is_facility_local(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Expect me around 8:30 PM."),
        )
        assert "I've recorded your updated ETA as 8:30 PM." in result.response
        assert "2026-08-14T" not in result.response
        assert "Z" not in result.response

    def test_option_windows_use_facility_timezone(self) -> None:
        start = datetime(2026, 8, 14, 0, 30, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, 1, 30, tzinfo=timezone.utc)
        text = format_options(
            [PresentedOption(index=1, slot_id=uuid4(), start_time=start, end_time=end)],
            timezone_name="America/Chicago",
        )
        assert "7:30 PM" in text
        assert "8:30 PM" in text
        assert "00:30" not in text
        assert "UTC" not in text


class TestDelayEtaRepairParaphrases:
    def test_explicit_eta_wins_paraphrase(self, db_session: Session) -> None:
        parsed = parse_understanding("Running two hours behind, I should get there around 8:30.")
        assert parsed.delay_minutes == 120
        assert parsed.eta_local == "20:30"
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Running two hours behind, I should get there around 8:30."),
        )
        latest = _latest_eta(db_session, world["shipment"].id)
        assert _local_hour_minute(latest) == (20, 30)

    def test_repair_need_minutes_is_not_eta(self, db_session: Session) -> None:
        parsed = parse_understanding("I need 90 minutes for repairs.")
        assert parsed.repair_duration_minutes == 90
        assert parsed.delay_minutes is None
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        before = _latest_eta(db_session, world["shipment"].id)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I need 90 minutes for repairs."),
        )
        assert "record_eta_update" not in _tool_names(result)
        assert _latest_eta(db_session, world["shipment"].id) == before
        assert result.requires_clarification is True


class TestCannotMakeGiveOptions:
    def test_compound_records_and_searches(self, db_session: Session) -> None:
        parsed = parse_understanding("I can't make the 6:30. Give me some options.")
        assert parsed.cannot_make_appointment is True
        assert parsed.intent == ConversationIntent.ASK_OPTIONS
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I can't make the 6:30. Give me some options."),
        )
        names = _tool_names(result)
        assert "create_driver_exception" in names
        assert "get_available_options" in names
        assert "Would you like me to find appointment options?" not in result.response
        assert "create_proposal" not in names
        assert "accept_proposal" not in names


class TestNaturalOptionSelection:
    def _options_thread(self, db_session: Session):
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="What slots do you have?"),
        )
        return world, service, created

    def test_selection_paraphrases_are_not_confirmation(self) -> None:
        messages = [
            "I'll take the second one.",
            "The later one works.",
            "The 8:30 slot works.",
            "Give me the earliest one.",
            "The first option.",
            "Let's take 8:30.",
            "That later slot works.",
        ]
        for message in messages:
            parsed = parse_understanding(message)
            assert parsed.intent != ConversationIntent.ACCEPT_PROPOSAL, message
            assert parsed.confirm is False, message

    def test_later_and_clock_selection_create_proposal_only(self, db_session: Session) -> None:
        world, service, created = self._options_thread(db_session)
        later = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The later one works."),
        )
        assert "create_proposal" in _tool_names(later)
        assert "accept_proposal" not in _tool_names(later)
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

    def test_clock_selection_matches_presented_option(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        world["slot_b"].status = AppointmentSlotStatus.CLOSED
        db_session.commit()
        service, created = _thread(db_session, world)
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="What slots do you have?"),
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The 8:30 slot works."),
        )
        assert result.intent == ConversationIntent.PROPOSE_CHANGE.value
        assert "create_proposal" in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)

    def test_ambiguous_clock_asks_clarification(self, db_session: Session) -> None:
        _world, service, created = self._options_thread(db_session)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The 8:30 slot works."),
        )
        assert result.requires_clarification is True
        assert "create_proposal" not in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)
        assert "which numbered option" in result.response.lower()

    def test_shortest_wait_and_earliest_question_select(self, db_session: Session) -> None:
        _world, service, created = self._options_thread(db_session)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Which one has the shortest wait?"),
        )
        assert result.intent == ConversationIntent.PROPOSE_CHANGE.value
        assert "create_proposal" in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)


class TestStatusAndConfirmation:
    def test_status_paraphrases_are_read_only(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        service.handle_message(created.thread_id, ConversationMessageRequest(message="What slots do you have?"))
        service.handle_message(created.thread_id, ConversationMessageRequest(message="The first option."))
        for message in (
            "Has it been confirmed?",
            "Is my appointment booked?",
            "What's the status?",
            "Did you book it?",
            "Don't confirm it yet.",
            "Is my appointment confirmed?",
        ):
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_STATUS, message
            assert parsed.confirm is False, message
            result = service.handle_message(created.thread_id, ConversationMessageRequest(message=message))
            assert "accept_proposal" not in _tool_names(result), message
            assert "allocate" not in " ".join(_tool_names(result)), message
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

    def test_explicit_confirm_phrases(self) -> None:
        for message in (
            "Confirm it.",
            "Confirm",
            "Yes, confirm the 8:30 slot.",
            "Book the second option.",
            "Go ahead and confirm that proposal.",
        ):
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ACCEPT_PROPOSAL, message
            assert parsed.confirm is True, message


    def test_confirm_turn_does_not_repeat_proposal_prompt(self) -> None:
        text = format_turn(
            results=[
                ToolResult(
                    name="create_proposal",
                    success=True,
                    data={"status": "proposed", "proposal_id": str(uuid4())},
                ),
                ToolResult(
                    name="accept_proposal",
                    success=True,
                    data={"status": "confirmed", "proposal_id": str(uuid4())},
                ),
            ]
        )
        assert text == "The appointment is confirmed."
        assert "Say confirm if you want me to book it." not in text

    def test_appointment_time_is_read_only(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="When is my appointment?"),
        )
        assert result.intent == ConversationIntent.ASK_APPOINTMENT.value
        assert "get_appointment" in _tool_names(result)
        assert "6:30 PM" in result.response
        assert "accept_proposal" not in _tool_names(result)
        original = db_session.get(Appointment, world["original_appointment"].id)
        assert original.status == AppointmentStatus.REQUESTED


class TestStaleConfirmationCopy:
    def test_concurrent_confirmation_is_not_success(self) -> None:
        text = format_turn(
            results=[
                ToolResult(
                    name="accept_proposal",
                    success=False,
                    error="Proposal is stale: concurrent_confirmation",
                    error_code="stale",
                )
            ]
        )
        assert text == "Proposal is stale: concurrent_confirmation"
        assert "confirmed" not in text.lower() or "not" in text.lower()
        assert "The appointment is confirmed." not in text
