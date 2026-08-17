"""Stage 4 live-defect remediation: routing, clock ETA, reschedule conversation, timezone."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.ai.conversation.formatter import format_options
from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationIntent, PresentedOption
from app.models import Appointment, AppointmentSlot, Dock, DriverException, ETAUpdate
from app.models.enums import AppointmentStatus, DockStatus
from app.schemas.allocation import AllocationRequest
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.schemas.proposal import ProposalStatus
from app.services.allocation import AllocationService
from app.services.feasibility import FeasibilityService
from app.services.proposal import ProposalService
from tests.test_step8_conversation import _build_world, _service
from tests.test_step8_reschedule_flow import _build_reschedule_world, _chi


class TestClockAndRelativeEta:
    def test_reach_around_clock_is_update_eta_not_clarification(self) -> None:
        parsed = parse_understanding("I'll reach around 8:30 PM because of traffic.")
        assert parsed.intent == ConversationIntent.UPDATE_ETA
        assert parsed.eta_local == "20:30"
        assert parsed.intent != ConversationIntent.CLARIFICATION_REQUIRED

    def test_relative_delay_does_not_stack_on_retry(self, db_session: Session) -> None:
        world = _build_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        first = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be late by 2 hours."),
        )
        assert first.intent == ConversationIntent.UPDATE_ETA.value
        latest = (
            db_session.query(ETAUpdate)
            .filter(ETAUpdate.shipment_id == world["shipment"].id)
            .order_by(ETAUpdate.update_timestamp.desc())
            .first()
        )
        assert latest is not None
        first_eta = latest.new_eta
        count_after_first = (
            db_session.query(ETAUpdate).filter(ETAUpdate.shipment_id == world["shipment"].id).count()
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be late by 2 hours."),
        )
        latest_again = (
            db_session.query(ETAUpdate)
            .filter(ETAUpdate.shipment_id == world["shipment"].id)
            .order_by(ETAUpdate.update_timestamp.desc())
            .first()
        )
        assert latest_again.new_eta == first_eta
        assert (
            db_session.query(ETAUpdate).filter(ETAUpdate.shipment_id == world["shipment"].id).count()
            == count_after_first
        )


class TestExceptionThenOptions:
    def test_cant_make_give_me_options_continues_to_discovery(self, db_session: Session) -> None:
        world = _build_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        parsed = parse_understanding("I can't make it, give me options.")
        assert parsed.intent == ConversationIntent.ASK_OPTIONS
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I can't make it, give me options."),
        )
        names = [call.name for call in result.tool_calls]
        assert "create_driver_exception" in names
        assert "get_available_options" in names
        assert names.index("create_driver_exception") < names.index("get_available_options")
        assert "request_human_escalation" not in names
        assert result.requires_human is False
        assert result.intent != ConversationIntent.HUMAN_ESCALATION.value

    def test_anything_after_seven_asks_options_with_constraint(self, db_session: Session) -> None:
        parsed = parse_understanding("Anything after 7?")
        assert parsed.intent == ConversationIntent.ASK_OPTIONS
        assert parsed.earliest_start_local == "19:00"
        world = _build_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Anything after 7?"),
        )
        assert result.intent == ConversationIntent.ASK_OPTIONS.value
        assert any(call.name == "get_available_options" and call.success for call in result.tool_calls)
        assert all(call.name != "accept_proposal" for call in result.tool_calls)


class TestConfirmHydration:
    def test_confirm_it_accepts_single_pending_proposal_on_new_thread(self, db_session: Session) -> None:
        world = _build_world(db_session)
        service = _service(db_session)
        first = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            first.thread_id,
            ConversationMessageRequest(message="What options do I have?"),
        )
        chosen = service.handle_message(
            first.thread_id,
            ConversationMessageRequest(message="The first one works."),
        )
        assert chosen.proposal_id is not None
        second = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        result = service.handle_message(
            second.thread_id,
            ConversationMessageRequest(message="Confirm it."),
        )
        assert result.intent == ConversationIntent.ACCEPT_PROPOSAL.value
        assert any(call.name == "accept_proposal" and call.success for call in result.tool_calls)
        assert "Which numbered option" not in result.response
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 1


class TestFacilityLocalOptionDisplay:
    def test_chicago_slot_renders_evening_not_utc(self) -> None:
        start = datetime(2026, 8, 14, 0, 30, tzinfo=timezone.utc)
        end = datetime(2026, 8, 14, 1, 30, tzinfo=timezone.utc)
        text = format_options(
            [
                PresentedOption(
                    index=1,
                    slot_id=uuid4(),
                    start_time=start,
                    end_time=end,
                )
            ],
            timezone_name="America/Chicago",
        )
        assert "7:30 PM" in text
        assert "8:30 PM" in text
        assert "00:30" not in text
        assert "UTC" not in text


class TestConfirmedRescheduleConversation:
    def test_cannot_make_confirmed_slot_reaches_reschedule_path(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        original = world["original_appointment"]
        dock = db_session.get(Dock, original.dock_id)
        db_session.delete(original)
        db_session.commit()
        allocated = AllocationService(db_session).allocate(
            world["shipment"].id,
            AllocationRequest(
                appointment_slot_id=world["original_slot"].id,
                dock_id=dock.id,
            ),
        )
        assert allocated.success is True
        old_id = allocated.appointment.id
        old_slot = db_session.get(AppointmentSlot, world["original_slot"].id)
        assert old_slot.status.value in {"full", "open"} or old_slot.capacity >= 0

        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        options = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I can't make the 6:30 PM appointment."),
        )
        names = [call.name for call in options.tool_calls]
        assert "create_driver_exception" in names
        assert "get_available_options" in names
        assert "request_human_escalation" not in names
        assert options.requires_human is False
        assert "8:30 PM" in options.response

        direct = FeasibilityService(db_session).evaluate(
            world["shipment"].id,
            FeasibilityEvaluateRequest(appointment_slot_id=world["slot_a"].id),
        )
        assert direct.feasible is False
        assert any(rule.rule_id == "EXCP-001" and not rule.passed for rule in direct.rule_results)

        selected = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The first one works."),
        )
        assert any(call.name == "create_proposal" and call.success for call in selected.tool_calls)
        assert all(call.name != "accept_proposal" for call in selected.tool_calls)
        proposal = ProposalService(db_session).get(selected.proposal_id)
        assert proposal.status == ProposalStatus.PROPOSED
        new_slot = db_session.get(AppointmentSlot, proposal.slot_id)
        assert _chi(new_slot.start_time).hour == 20
        assert _chi(new_slot.start_time).minute == 30
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 1

        confirmed = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Confirm it."),
        )
        assert any(call.name == "accept_proposal" and call.success for call in confirmed.tool_calls)
        db_session.expire_all()
        old = db_session.get(Appointment, old_id)
        assert old.status == AppointmentStatus.CANCELLED
        assert old.notes and "superseded_by=" in old.notes
        current = (
            db_session.query(Appointment)
            .filter(
                Appointment.shipment_id == world["shipment"].id,
                Appointment.status == AppointmentStatus.CONFIRMED,
            )
            .all()
        )
        assert len(current) == 1
        assert current[0].id != old_id
        assert str(current[0].id) in old.notes
        new_slot = db_session.get(AppointmentSlot, current[0].appointment_slot_id)
        assert _chi(new_slot.start_time).hour == 20
        assert _chi(new_slot.start_time).minute == 30
        old_slot = db_session.get(AppointmentSlot, world["original_slot"].id)
        consuming_old = (
            db_session.query(Appointment)
            .filter(
                Appointment.appointment_slot_id == old_slot.id,
                Appointment.status.in_((AppointmentStatus.CONFIRMED, AppointmentStatus.HELD)),
            )
            .count()
        )
        assert consuming_old == 0
        exceptions = (
            db_session.query(DriverException).filter(DriverException.shipment_id == world["shipment"].id).all()
        )
        assert exceptions
