"""Regression tests for informal options requests and leave-by constraints."""

from __future__ import annotations

from datetime import timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationIntent
from app.models import Appointment, AppointmentSlot, Dock, DriverException, ETAUpdate, Shipment
from app.models.enums import AppointmentStatus
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from tests.test_step8_conversation import _build_world, _service


def _build_evening_world(db_session: Session) -> dict[str, object]:
    """Slots that can contain an 8:30 PM ETA and test 9:00 / 9:30 PM leave-by."""
    world = _build_world(db_session, eta_delta=timedelta(hours=10, minutes=40))
    now = world["now"]
    world["slot_a"].start_time = now.replace(hour=20, minute=0, second=0, microsecond=0)
    world["slot_a"].end_time = now.replace(hour=21, minute=0, second=0, microsecond=0)
    world["slot_b"].start_time = now.replace(hour=20, minute=15, second=0, microsecond=0)
    world["slot_b"].end_time = now.replace(hour=21, minute=15, second=0, microsecond=0)
    db_session.commit()
    return world


def _counts(session: Session) -> dict[str, int]:
    tables = (Appointment, AppointmentSlot, Dock, Shipment, ETAUpdate, DriverException)
    return {table.__tablename__: int(session.scalar(select(func.count()).select_from(table)) or 0) for table in tables}


class TestInformalOptionsPhrases:
    def test_informal_after_seven_intents(self) -> None:
        messages = [
            "Anything after 7?",
            "Anything after 7 PM?",
            "Any slots after 7?",
            "Do you have anything after 7?",
            "Anything later than 7?",
            "Can I come after 7?",
            "Are there options after 7?",
            "Anything available after 7?",
        ]
        for message in messages:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_OPTIONS, message
            assert parsed.earliest_start_local == "19:00", message
            assert parsed.confirm is False, message

    def test_anything_after_seven_shows_options_without_booking(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        before = _counts(db_session)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Anything after 7?"),
        )
        after = _counts(db_session)
        assert result.intent == ConversationIntent.ASK_OPTIONS.value
        assert any(call.name == "get_available_options" and call.success for call in result.tool_calls)
        assert all(call.name != "create_proposal" for call in result.tool_calls)
        assert all(call.name != "accept_proposal" for call in result.tool_calls)
        assert "1." in result.response
        assert after == before
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

    def test_options_evaluation_does_not_mutate_capacity(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        before = _counts(db_session)
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Any slots after 7?"),
        )
        assert _counts(db_session) == before


class TestLeaveByConstraint:
    def test_leave_by_phrases_parse(self) -> None:
        cases = [
            ("The second one works, but I need to leave by 9.", 2, "21:00"),
            ("The second one works, but I need to leave by 9:30 PM.", 2, "21:30"),
            ("I like the second option but have to leave by 9.", 2, "21:00"),
        ]
        for message, index, leave_by in cases:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.PROPOSE_CHANGE, message
            assert parsed.option_index == index, message
            assert parsed.leave_by_local == leave_by, message
            assert parsed.confirm is False, message

    def test_compatible_leave_by_creates_proposal_only(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Anything after 7?"),
        )
        chosen = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The second one works, but I need to leave by 9:30 PM."),
        )
        assert any(call.name == "create_proposal" and call.success for call in chosen.tool_calls)
        assert all(call.name != "accept_proposal" for call in chosen.tool_calls)
        assert chosen.proposal_id is not None
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

    def test_incompatible_leave_by_does_not_create_proposal(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Anything after 7?"),
        )
        before_requested = (
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.REQUESTED).count()
        )
        chosen = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The second one works, but I need to leave by 9."),
        )
        after_requested = (
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.REQUESTED).count()
        )
        assert all(call.name != "create_proposal" for call in chosen.tool_calls)
        assert all(call.name != "accept_proposal" for call in chosen.tool_calls)
        assert chosen.proposal_id is None
        assert after_requested == before_requested
        assert "leave-by" in chosen.response.lower() or "leave by" in chosen.response.lower()
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

    def test_like_second_option_compatible_leave_by(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Can I come after 7?"),
        )
        chosen = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I like the second option but have to leave by 9:30 PM."),
        )
        assert any(call.name == "create_proposal" and call.success for call in chosen.tool_calls)
        assert chosen.proposal_id is not None


class TestExactMultiTurnScenario:
    def test_delay_options_leave_by_second_option(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        parsed = parse_understanding(
            "I'll be two hours late. I was supposed to reach by 6:30 PM, but I'll reach around 8:30 PM."
        )
        assert parsed.delay_minutes == 120
        assert parsed.eta_local == "20:30"
        assert parsed.intent == ConversationIntent.UPDATE_ETA

        turn1 = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message=(
                    "I'll be two hours late. I was supposed to reach by 6:30 PM, "
                    "but I'll reach around 8:30 PM."
                )
            ),
        )
        assert turn1.intent == ConversationIntent.UPDATE_ETA.value
        assert any(call.name == "record_eta_update" and call.success for call in turn1.tool_calls)
        latest = db_session.query(ETAUpdate).order_by(ETAUpdate.update_timestamp.desc()).first()
        assert latest is not None
        actual = latest.new_eta
        if actual.tzinfo is None:
            actual = actual.replace(tzinfo=timezone.utc)
        assert actual.hour == 20
        assert actual.minute == 30

        turn2 = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I also have an emergency and need to leave by 9:30 PM."),
        )
        assert turn2.requires_clarification is True
        assert all(call.name != "create_proposal" for call in turn2.tool_calls)
        assert all(call.name != "accept_proposal" for call in turn2.tool_calls)

        turn3 = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="My ETA is 8:30 PM. What options do I have?"),
        )
        assert turn3.intent == ConversationIntent.ASK_OPTIONS.value
        assert any(call.name == "get_available_options" and call.success for call in turn3.tool_calls)
        assert all(call.name != "create_proposal" for call in turn3.tool_calls)
        assert "1." in turn3.response

        turn4 = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The second one works, but I need to leave by 9:30 PM."),
        )
        assert any(call.name == "create_proposal" and call.success for call in turn4.tool_calls)
        assert all(call.name != "accept_proposal" for call in turn4.tool_calls)
        assert turn4.proposal_id is not None
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0
        requested = (
            db_session.query(Appointment)
            .filter(Appointment.status == AppointmentStatus.REQUESTED)
            .one()
        )
        assert requested.appointment_slot_id == world["slot_b"].id


class TestConfirmationRegressionStillHolds:
    def test_status_questions_remain_read_only(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(created.thread_id, ConversationMessageRequest(message="Anything after 7?"))
        chosen = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The second one works, but I need to leave by 9:30 PM."),
        )
        assert chosen.proposal_id is not None
        before = (
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count(),
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.REQUESTED).count(),
        )
        for message in (
            "Has it been confirmed?",
            "Is it confirmed?",
            "Can you check if it's confirmed?",
            "Don't confirm it yet.",
        ):
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_STATUS, message
            result = service.handle_message(created.thread_id, ConversationMessageRequest(message=message))
            assert result.intent == ConversationIntent.ASK_STATUS.value, message
            assert all(call.name != "accept_proposal" for call in result.tool_calls), message
        after = (
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count(),
            db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.REQUESTED).count(),
        )
        assert after == before == (0, 1)

    def test_explicit_confirm_still_allocates(self, db_session: Session) -> None:
        world = _build_evening_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(created.thread_id, ConversationMessageRequest(message="Anything after 7?"))
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The second one works, but I need to leave by 9:30 PM."),
        )
        result = service.handle_message(created.thread_id, ConversationMessageRequest(message="Confirm it."))
        assert result.intent == ConversationIntent.ACCEPT_PROPOSAL.value
        assert any(call.name == "accept_proposal" and call.success for call in result.tool_calls)
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 1
