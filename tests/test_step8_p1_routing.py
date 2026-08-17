"""Regression tests for Step 8 P1 delay, options, and confirmation-status routing."""

from __future__ import annotations

from datetime import timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationIntent
from app.models import Appointment, AppointmentSlot, Dock, DriverException, ETAUpdate
from app.models.enums import AppointmentStatus, DockStatus
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from app.services.operations import ETAUpdateService
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

    def test_traffic_will_make_me_late_records_eta_not_exception(self, db_session: Session) -> None:
        world = _build_world(db_session, eta_delta=timedelta(hours=1))
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Traffic will make me 2 hours late."),
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
            ("I will be late by 2 hours.", 120),
            ("I'll be late by two hours.", 120),
            ("I am late by 90 minutes.", 90),
            ("I'll be about 2 hours late.", 120),
            ("I'll arrive 2 hours late.", 120),
            ("I'll arrive two hours late.", 120),
            ("I'm running 2 hours late.", 120),
            ("I'm 2 hours behind.", 120),
            ("Traffic will make me 2 hours late.", 120),
        ]
        for message, minutes in cases:
            parsed = parse_understanding(message)
            assert parsed.intent in {ConversationIntent.UPDATE_ETA, ConversationIntent.REPORT_DELAY}, message
            assert parsed.delay_minutes == minutes, message
            assert parsed.intent != ConversationIntent.REPORT_EXCEPTION, message


class TestDelayParserHardening:
    def test_late_by_numeric_hours(self) -> None:
        parsed = parse_understanding("I will be late by 2 hours.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.delay_minutes == 120
        assert parsed.eta_local is None

    def test_late_by_word_hours(self) -> None:
        parsed = parse_understanding("I'll be late by two hours.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.delay_minutes == 120
        assert parsed.eta_local is None

    def test_late_by_minutes(self) -> None:
        parsed = parse_understanding("I am late by 90 minutes.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.delay_minutes == 90

    def test_about_hours_late(self) -> None:
        parsed = parse_understanding("I'll be about 2 hours late.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.delay_minutes == 120

    def test_arrive_numeric_hours_late_is_not_clock(self) -> None:
        parsed = parse_understanding("I'll arrive 2 hours late.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.delay_minutes == 120
        assert parsed.eta_local is None

    def test_arrive_word_hours_late_is_not_clock(self) -> None:
        parsed = parse_understanding("I'll arrive two hours late.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.delay_minutes == 120
        assert parsed.eta_local is None

    def test_running_hours_late(self) -> None:
        parsed = parse_understanding("I'm running 2 hours late.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.delay_minutes == 120

    def test_hours_behind(self) -> None:
        parsed = parse_understanding("I'm 2 hours behind.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.delay_minutes == 120

    def test_traffic_delay_is_eta_not_exception(self) -> None:
        parsed = parse_understanding("Traffic will make me 2 hours late.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.delay_minutes == 120
        assert parsed.intent != ConversationIntent.REPORT_EXCEPTION

    def test_absolute_eta_phrase_still_parses_clock(self) -> None:
        parsed = parse_understanding("My ETA is 8:30 PM.")
        assert parsed.eta_local == "20:30"
        assert parsed.delay_minutes is None

    def test_late_by_records_eta_via_http(self, db_session: Session, client: TestClient) -> None:
        world = _build_world(db_session, eta_delta=timedelta(hours=1))
        created = client.post(
            "/conversations",
            json={"driver_id": str(world["driver"].id), "shipment_id": str(world["shipment"].id)},
        )
        assert created.status_code == 201
        thread_id = created.json()["thread_id"]
        response = client.post(
            f"/conversations/{thread_id}/messages",
            json={"message": "I will be late by 2 hours."},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["intent"] == ConversationIntent.UPDATE_ETA.value
        names = [call["name"] for call in body["tool_calls"]]
        assert names.count("record_eta_update") == 1
        assert all(call["success"] for call in body["tool_calls"] if call["name"] == "record_eta_update")
        assert "create_proposal" not in names
        assert "accept_proposal" not in names
        assert "allocate_appointment" not in names
        assert "create_driver_exception" not in names
        latest = ETAUpdateService(db_session).get_latest(world["shipment"].id)
        actual = latest.latest_eta
        assert actual is not None
        if actual.tzinfo is None:
            actual = actual.replace(tzinfo=timezone.utc)
        assert actual == world["now"] + timedelta(hours=3)

    def test_arrive_hours_late_records_relative_eta_via_http(self, db_session: Session, client: TestClient) -> None:
        world = _build_world(db_session, eta_delta=timedelta(hours=1))
        created = client.post(
            "/conversations",
            json={"driver_id": str(world["driver"].id), "shipment_id": str(world["shipment"].id)},
        )
        assert created.status_code == 201
        thread_id = created.json()["thread_id"]
        response = client.post(
            f"/conversations/{thread_id}/messages",
            json={"message": "I'll arrive 2 hours late."},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["intent"] == ConversationIntent.UPDATE_ETA.value
        names = [call["name"] for call in body["tool_calls"]]
        assert names.count("record_eta_update") == 1
        assert all(call["success"] for call in body["tool_calls"] if call["name"] == "record_eta_update")
        assert "create_proposal" not in names
        assert "accept_proposal" not in names
        assert "allocate_appointment" not in names
        latest = ETAUpdateService(db_session).get_latest(world["shipment"].id)
        actual = latest.latest_eta
        assert actual is not None
        if actual.tzinfo is None:
            actual = actual.replace(tzinfo=timezone.utc)
        # Relative delay from latest ETA (11:00), not clock-hour 14:00 from "arrive 2".
        assert actual == world["now"] + timedelta(hours=3)
        assert not (actual.hour == 14 and actual.minute == 0)


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


_NEXT_SLOT_AVAILABILITY_MESSAGES = [
    "When is the next slot?",
    "When can I get the next slot?",
    "What is the next available appointment?",
    "When is the next available appointment?",
    "What slots are available?",
    "Can you find me another slot?",
    "When can I get in?",
    "What is the earliest available slot?",
    "So when i will get the next slot",
]


class TestP1NextSlotAvailability:
    def test_next_slot_phrases_parse_as_read_only_options(self) -> None:
        for message in _NEXT_SLOT_AVAILABILITY_MESSAGES:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_OPTIONS, message
            assert parsed.confirm is False, message
            assert parsed.option_index is None, message
            assert parsed.intent != ConversationIntent.ASK_APPOINTMENT, message
            assert parsed.intent != ConversationIntent.ASK_STATUS, message
            assert parsed.intent != ConversationIntent.ACCEPT_PROPOSAL, message
            assert parsed.intent != ConversationIntent.PROPOSE_CHANGE, message
            assert parsed.intent != ConversationIntent.CLARIFICATION_REQUIRED, message

    def test_when_is_my_slot_stays_appointment_lookup(self) -> None:
        parsed = parse_understanding("When is my slot?")
        assert parsed.intent == ConversationIntent.ASK_APPOINTMENT
        assert parsed.intent != ConversationIntent.ASK_OPTIONS

    def test_has_it_been_confirmed_stays_status(self) -> None:
        parsed = parse_understanding("Has it been confirmed?")
        assert parsed.intent == ConversationIntent.ASK_STATUS
        assert parsed.confirm is False

    def test_give_me_the_second_option_stays_proposal_selection(self) -> None:
        parsed = parse_understanding("Give me the second option")
        assert parsed.intent == ConversationIntent.PROPOSE_CHANGE
        assert parsed.option_index == 2

    def test_so_when_i_will_get_the_next_slot_is_read_only(self, db_session: Session) -> None:
        world = _build_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        before = _safety_snapshot(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="So when i will get the next slot"),
        )
        assert result.intent == ConversationIntent.ASK_OPTIONS.value
        assert result.status != "clarification"
        assert "Could you tell me what you need help with" not in result.response
        names = [call.name for call in result.tool_calls]
        assert "get_available_options" in names
        assert all(call.success for call in result.tool_calls if call.name == "get_available_options")
        assert "create_proposal" not in names
        assert "accept_proposal" not in names
        assert "allocate_appointment" not in names
        assert "record_eta_update" not in names
        assert "create_driver_exception" not in names
        assert _safety_snapshot(db_session, world) == before

    def test_next_slot_phrases_are_read_only_via_service(self, db_session: Session) -> None:
        world = _build_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        before = _safety_snapshot(db_session, world)
        for message in _NEXT_SLOT_AVAILABILITY_MESSAGES:
            result = service.handle_message(
                created.thread_id,
                ConversationMessageRequest(message=message),
            )
            assert result.intent == ConversationIntent.ASK_OPTIONS.value, message
            names = [call.name for call in result.tool_calls]
            assert "get_available_options" in names, message
            assert "create_proposal" not in names, message
            assert "accept_proposal" not in names, message
            assert "record_eta_update" not in names, message
            assert "create_driver_exception" not in names, message
            assert "feasible" in result.response.lower() or "could not find a feasible" in result.response.lower()
        assert _safety_snapshot(db_session, world) == before


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


_APPOINTMENT_INFO_MESSAGES = [
    "What is my appointment time?",
    "When is my appointment?",
    "What time am I scheduled for?",
    "What time is my appointment?",
    "When am I scheduled?",
    "What's my scheduled appointment?",
    "What is my original appointment?",
    "What time should I arrive?",
    "When should I arrive at the facility?",
]


def _seed_original_appointment(db_session: Session, world: dict, *, timezone_name: str = "UTC") -> Appointment:
    world["facility"].timezone = timezone_name
    appointment = Appointment(
        shipment_id=world["shipment"].id,
        facility_id=world["facility"].id,
        appointment_slot_id=world["slot_a"].id,
        dock_id=world["dock"].id,
        status=AppointmentStatus.CONFIRMED,
        notes="original appointment",
    )
    db_session.add_all([world["facility"], appointment])
    db_session.commit()
    db_session.refresh(appointment)
    db_session.refresh(world["slot_a"])
    db_session.refresh(world["dock"])
    return appointment


def _safety_snapshot(db_session: Session, world: dict) -> dict[str, object]:
    slot = db_session.get(AppointmentSlot, world["slot_a"].id)
    dock = db_session.get(Dock, world["dock"].id)
    assert slot is not None
    assert dock is not None
    return {
        "appointments": db_session.query(Appointment).count(),
        "confirmed": db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count(),
        "slot_capacity": slot.capacity,
        "dock_status": dock.status,
        "etas": db_session.query(ETAUpdate).count(),
        "exceptions": db_session.query(DriverException).count(),
    }


class TestP1AppointmentInformation:
    def test_appointment_time_phrases_parse_read_only(self) -> None:
        for message in _APPOINTMENT_INFO_MESSAGES:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_APPOINTMENT, message
            assert parsed.confirm is False, message
            assert parsed.intent != ConversationIntent.ASK_STATUS, message
            assert parsed.intent != ConversationIntent.ACCEPT_PROPOSAL, message
            assert parsed.intent != ConversationIntent.ASK_OPTIONS, message

    def test_what_is_my_appointment_time_returns_window(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _seed_original_appointment(db_session, world, timezone_name="America/Chicago")
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        before = _safety_snapshot(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="What is my appointment time?"),
        )
        assert result.intent == ConversationIntent.ASK_APPOINTMENT.value
        assert any(call.name == "get_appointment" and call.success for call in result.tool_calls)
        assert all(
            call.name not in {"accept_proposal", "create_proposal", "record_eta_update", "create_driver_exception"}
            for call in result.tool_calls
        )
        assert "8:00 AM" in result.response
        assert "9:30 AM" in result.response
        assert "America/Chicago" in result.response
        assert "13:00 UTC" not in result.response
        assert _safety_snapshot(db_session, world) == before

    def test_when_is_my_appointment_is_read_only(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _seed_original_appointment(db_session, world)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        before = _safety_snapshot(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="When is my appointment?"),
        )
        assert result.intent == ConversationIntent.ASK_APPOINTMENT.value
        assert any(call.name == "get_appointment" and call.success for call in result.tool_calls)
        assert "1:00 PM" in result.response
        assert "2:30 PM" in result.response
        assert _safety_snapshot(db_session, world) == before

    def test_what_time_am_i_scheduled_for_is_read_only(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _seed_original_appointment(db_session, world)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        before = _safety_snapshot(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="What time am I scheduled for?"),
        )
        assert result.intent == ConversationIntent.ASK_APPOINTMENT.value
        assert any(call.name == "get_appointment" and call.success for call in result.tool_calls)
        assert all(call.name != "accept_proposal" for call in result.tool_calls)
        assert _safety_snapshot(db_session, world) == before

    def test_has_it_been_confirmed_stays_get_proposal(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _seed_original_appointment(db_session, world)
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
        before = _safety_snapshot(db_session, world)
        parsed = parse_understanding("Has it been confirmed?")
        assert parsed.intent == ConversationIntent.ASK_STATUS
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Has it been confirmed?"),
        )
        assert result.intent == ConversationIntent.ASK_STATUS.value
        names = [call.name for call in result.tool_calls]
        assert names == ["get_proposal"]
        assert "accept_proposal" not in names
        after = _safety_snapshot(db_session, world)
        assert after["confirmed"] == before["confirmed"]
        assert after["etas"] == before["etas"]
        assert after["exceptions"] == before["exceptions"]
        assert after["slot_capacity"] == before["slot_capacity"]
        assert after["dock_status"] == before["dock_status"] == DockStatus.AVAILABLE

    def test_dont_confirm_it_yet_remains_read_only(self, db_session: Session) -> None:
        world = _build_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Can you find another appointment?"),
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The second one works."),
        )
        parsed = parse_understanding("Don't confirm it yet.")
        assert parsed.intent == ConversationIntent.ASK_STATUS
        assert parsed.confirm is False
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Don't confirm it yet."),
        )
        assert result.intent == ConversationIntent.ASK_STATUS.value
        assert all(call.name != "accept_proposal" for call in result.tool_calls)
        assert any(call.name == "get_proposal" for call in result.tool_calls)
        assert result.response == "The appointment has not been confirmed."
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

    def test_confirm_it_still_uses_explicit_confirmation_path(self, db_session: Session) -> None:
        world = _build_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Can you find another appointment?"),
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The second one works."),
        )
        parsed = parse_understanding("Confirm it.")
        assert parsed.intent == ConversationIntent.ACCEPT_PROPOSAL
        assert parsed.confirm is True
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Confirm it."),
        )
        assert result.intent == ConversationIntent.ACCEPT_PROPOSAL.value
        assert any(call.name == "accept_proposal" and call.success for call in result.tool_calls)
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 1

    def test_appointment_time_does_not_use_proposal_when_one_exists(self, db_session: Session) -> None:
        world = _build_world(db_session)
        _seed_original_appointment(db_session, world, timezone_name="America/Chicago")
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
        before = _safety_snapshot(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="What is my original appointment?"),
        )
        assert result.intent == ConversationIntent.ASK_APPOINTMENT.value
        names = [call.name for call in result.tool_calls]
        assert "get_appointment" in names
        assert "get_proposal" not in names
        assert "accept_proposal" not in names
        assert "8:00 AM" in result.response
        assert _safety_snapshot(db_session, world) == before

    def test_is_my_appointment_confirmed_stays_ask_status(self) -> None:
        parsed = parse_understanding("Is my appointment confirmed?")
        assert parsed.intent == ConversationIntent.ASK_STATUS
        assert parsed.confirm is False


class TestPostgreSQLAppointmentInformation:
    def test_appointment_lookup_does_not_mutate(self) -> None:
        from tests.test_step8_hardening import _postgres_test_url
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.services.conversation import ConversationService
        from app.ai.conversation.provider import FakeLLMProvider

        url = _postgres_test_url()
        if url is None:
            pytest.skip("PostgreSQL is not available")
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            world = _build_world(session)
            _seed_original_appointment(session, world, timezone_name="America/Chicago")
            service = ConversationService(session, provider=FakeLLMProvider())
            created = service.create_thread(
                ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
            )
            before = _safety_snapshot(session, world)
            result = service.handle_message(
                created.thread_id,
                ConversationMessageRequest(message="What is my appointment time?"),
            )
            assert result.intent == ConversationIntent.ASK_APPOINTMENT.value
            assert any(call.name == "get_appointment" and call.success for call in result.tool_calls)
            assert "8:00 AM" in result.response
            assert _safety_snapshot(session, world) == before
        finally:
            session.rollback()
            session.close()
            engine.dispose()
