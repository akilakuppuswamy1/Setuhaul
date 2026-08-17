"""Phase 1 semantic conversation facts: repair vs ETA, delay baseline, waiting policy."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationIntent
from app.engines.feasibility.engine import FeasibilityEngine
from app.engines.feasibility.models import FeasibilityContext
from app.models import Appointment, ETAUpdate
from app.models.enums import AppointmentStatus, ETASource
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.services.feasibility import FeasibilityService
from app.services.operations import ETAUpdateService
from tests.test_step5_feasibility import _feasible_context, _utc
from tests.test_step8_conversation import _service
from tests.test_step8_reschedule_flow import _build_reschedule_world, _chi


def _thread(db_session: Session, world: dict):
    service = _service(db_session)
    created = service.create_thread(
        ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
    )
    return service, created


def _eta_count(db_session: Session, shipment_id) -> int:
    return db_session.query(ETAUpdate).filter(ETAUpdate.shipment_id == shipment_id).count()


def _latest_eta(db_session: Session, shipment_id):
    return ETAUpdateService(db_session).get_latest(shipment_id).latest_eta


def _tool_names(result) -> list[str]:
    return [call.name for call in result.tool_calls]


def _local_hour_minute(value):
    local = _chi(value)
    return local.hour, local.minute


class TestCategoryARepairWithoutEta:
    def test_paraphrases_do_not_mutate_eta(self, db_session: Session) -> None:
        messages = [
            "Tyre puncture. Repair will take 90 minutes.",
            "Got a flat. Fixing it will take 90 minutes.",
            "Tire issue, the repair needs about ninety minutes.",
        ]
        for message in messages:
            parsed = parse_understanding(message)
            assert parsed.repair_duration_minutes == 90, message
            assert parsed.delay_minutes is None, message
            assert parsed.eta_local is None, message
            assert parsed.exception_type == "repair", message
            assert parsed.intent == ConversationIntent.REPORT_EXCEPTION, message

        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        before = _eta_count(db_session, world["shipment"].id)
        before_eta = _latest_eta(db_session, world["shipment"].id)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Tyre puncture. Repair will take 90 minutes."),
        )
        assert "record_eta_update" not in _tool_names(result)
        assert "create_proposal" not in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)
        assert _eta_count(db_session, world["shipment"].id) == before
        assert _latest_eta(db_session, world["shipment"].id) == before_eta
        assert result.requires_clarification is True
        assert "90" in result.response
        assert "create_driver_exception" in _tool_names(result)
        original = db_session.get(Appointment, world["original_appointment"].id)
        assert original.status == AppointmentStatus.REQUESTED
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0


class TestCategoryBRepairPlusExplicitEta:
    def test_repair_and_arrival_are_independent(self, db_session: Session) -> None:
        parsed = parse_understanding(
            "Tyre issue, repair will take 90 minutes. I should reach around 8:30 PM."
        )
        assert parsed.repair_duration_minutes == 90
        assert parsed.eta_local == "20:30"
        assert parsed.delay_minutes is None
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        before = _eta_count(db_session, world["shipment"].id)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message="Tyre issue, repair will take 90 minutes. I should reach around 8:30 PM."
            ),
        )
        assert "record_eta_update" in _tool_names(result)
        assert any(call.name == "record_eta_update" and call.success for call in result.tool_calls)
        latest = _latest_eta(db_session, world["shipment"].id)
        assert latest is not None
        assert _local_hour_minute(latest) == (20, 30)
        assert _eta_count(db_session, world["shipment"].id) == before + 1
        assert "create_proposal" not in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)


class TestCategoryCExplicitEtaParaphrases:
    def test_arrival_paraphrases_share_canonical_eta(self) -> None:
        messages = [
            "I'll reach around 8:30 PM.",
            "I should be there by 8:30.",
            "Expect me around 20:30.",
            "I'll arrive at about 8:30 tonight.",
            "I can get there around 20:30.",
            "Should be there by 8:30.",
            "Expect me at 8:30.",
        ]
        for message in messages:
            parsed = parse_understanding(message)
            assert parsed.eta_local == "20:30", message
            assert parsed.intent == ConversationIntent.UPDATE_ETA, message
            assert parsed.intent != ConversationIntent.CLARIFICATION_REQUIRED, message
            assert parsed.leave_by_local is None, message


class TestCategoryDRelativeDelayBaseline:
    def test_first_repeat_and_new_delay(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        first = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be 5 hours late."),
        )
        assert first.intent == ConversationIntent.UPDATE_ETA.value
        first_eta = _latest_eta(db_session, world["shipment"].id)
        assert first_eta is not None
        assert _local_hour_minute(first_eta) == (23, 30)
        count = _eta_count(db_session, world["shipment"].id)
        second = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be 5 hours late."),
        )
        assert _latest_eta(db_session, world["shipment"].id) == first_eta
        assert _eta_count(db_session, world["shipment"].id) == count
        assert _local_hour_minute(_latest_eta(db_session, world["shipment"].id)) != (4, 30)
        third = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be 3 hours late."),
        )
        assert any(call.name == "record_eta_update" and call.success for call in third.tool_calls)
        changed = _latest_eta(db_session, world["shipment"].id)
        assert _local_hour_minute(changed) == (21, 30)


class TestCategoryEDelayPlusExplicitEta:
    def test_explicit_eta_wins_in_same_message(self, db_session: Session) -> None:
        parsed = parse_understanding("I'll be two hours late. I should reach around 8:30 PM.")
        assert parsed.delay_minutes == 120
        assert parsed.eta_local == "20:30"
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be two hours late. I should reach around 8:30 PM."),
        )
        latest = _latest_eta(db_session, world["shipment"].id)
        assert _local_hour_minute(latest) == (20, 30)
        assert "create_proposal" not in _tool_names(result)

    def test_explicit_then_repeated_relative_does_not_add(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll reach around 8:30 PM."),
        )
        explicit = _latest_eta(db_session, world["shipment"].id)
        count = _eta_count(db_session, world["shipment"].id)
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be 5 hours late."),
        )
        assert _latest_eta(db_session, world["shipment"].id) == explicit
        assert _eta_count(db_session, world["shipment"].id) == count
        assert _local_hour_minute(explicit) == (20, 30)


class TestCategoryFGHWaitingPolicy:
    def test_engine_three_arrival_relations(self) -> None:
        early = FeasibilityEngine().evaluate(
            FeasibilityContext(**{**_feasible_context().__dict__, "latest_eta": _utc(2026, 8, 13, 11, 15)})
        )
        during = FeasibilityEngine().evaluate(_feasible_context())
        late = FeasibilityEngine().evaluate(
            FeasibilityContext(**{**_feasible_context().__dict__, "latest_eta": _utc(2026, 8, 13, 13, 30)})
        )
        assert next(r for r in early.rule_results if r.rule_id == "ETA-001").facts["arrival_relation"] == "before_window"
        assert next(r for r in during.rule_results if r.rule_id == "ETA-001").facts["arrival_relation"] == "during_window"
        assert next(r for r in late.rule_results if r.rule_id == "ETA-001").facts["arrival_relation"] == "after_window"
        assert early.feasible is True
        assert during.feasible is True
        assert late.feasible is False

    def test_service_early_during_late_against_original_slot(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        slot = world["original_slot"]
        service = FeasibilityService(db_session)
        early_time = slot.start_time - timedelta(minutes=45)
        during_time = slot.start_time + timedelta(minutes=15)
        late_time = slot.end_time + timedelta(minutes=30)
        for when, expected in ((early_time, True), (during_time, True), (late_time, False)):
            db_session.add(
                ETAUpdate(
                    shipment_id=world["shipment"].id,
                    previous_eta=None,
                    new_eta=when,
                    update_timestamp=when,
                    source=ETASource.DRIVER,
                )
            )
            db_session.commit()
            result = service.evaluate(
                world["shipment"].id,
                FeasibilityEvaluateRequest(appointment_slot_id=slot.id, ignore_delay_exceptions=True),
            )
            eta_rule = next(rule for rule in result.rule_results if rule.rule_id == "ETA-001")
            assert eta_rule.passed is expected


class TestCategoryILeaveBy:
    def test_leave_by_is_not_eta(self) -> None:
        parsed = parse_understanding("I'll reach around 8:30 PM and need to leave by 2 AM.")
        assert parsed.eta_local == "20:30"
        assert parsed.leave_by_local == "02:00"
        assert parsed.repair_duration_minutes is None

    def test_leave_by_preserved_on_context(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll reach around 8:30 PM and need to leave by 2 AM."),
        )
        latest = _latest_eta(db_session, world["shipment"].id)
        assert _local_hour_minute(latest) == (20, 30)
        assert result.metadata is not None
        assert result.metadata.get("leave_by_local") == "02:00"
        assert "create_proposal" not in _tool_names(result)


class TestCategoryJExceptionOptions:
    def test_exception_only_does_not_book(self, db_session: Session) -> None:
        parsed = parse_understanding("I have a tyre problem and will reach around 8:30 PM.")
        assert parsed.exception_type == "repair"
        assert parsed.eta_local == "20:30"
        assert parsed.asks_options is False
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I have a tyre problem and will reach around 8:30 PM."),
        )
        names = _tool_names(result)
        assert "create_driver_exception" in names
        assert "record_eta_update" in names
        assert "get_available_options" not in names
        assert "create_proposal" not in names
        assert "accept_proposal" not in names
        assert "no longer feasible" in result.response.lower() or "alternatives" in result.response.lower()

    def test_exception_plus_options_continues(self, db_session: Session) -> None:
        messages = [
            "My truck broke down. What can I do?",
            "I won't make the appointment, can you find another time?",
            "Tyre problem. Show me what else is available.",
            "I'm delayed. Do you have anything later?",
            "I can't make 6:30. What are my options?",
        ]
        for message in messages:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_OPTIONS, message
            assert parsed.asks_options is True, message
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I won't make the appointment, can you find another time?"),
        )
        names = _tool_names(result)
        assert "get_available_options" in names
        assert "create_proposal" not in names
        assert "accept_proposal" not in names


class TestCategoryKOriginalAppointment:
    def test_small_delay_keeps_original_feasible(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be 15 minutes late."),
        )
        assert "record_eta_update" in _tool_names(result)
        assert "evaluate_feasibility" in _tool_names(result)
        assert "still works" in result.response.lower()
        assert "create_proposal" not in _tool_names(result)

    def test_five_hour_delay_makes_original_infeasible(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll be 5 hours late."),
        )
        assert "no longer feasible" in result.response.lower()
        assert "11:30 PM" in result.response
        assert "2026-08" not in result.response
        assert "create_proposal" not in _tool_names(result)
        original = db_session.get(Appointment, world["original_appointment"].id)
        assert original.status == AppointmentStatus.REQUESTED
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0


class TestCategoryLImpossibleConstraints:
    def test_eta_after_leave_by_does_not_book(self, db_session: Session) -> None:
        parsed = parse_understanding("I'll reach around 4:30 AM and need to leave by 2 AM.")
        assert parsed.eta_local == "04:30"
        assert parsed.leave_by_local == "02:00"
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="I'll reach around 4:30 AM and need to leave by 2 AM."),
        )
        assert "create_proposal" not in _tool_names(result)
        assert "accept_proposal" not in _tool_names(result)
        assert result.requires_clarification or result.requires_human
        original = db_session.get(Appointment, world["original_appointment"].id)
        assert original is not None
        assert original.status == AppointmentStatus.REQUESTED
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0


class TestRequiredRegression:
    def test_five_hour_breakdown_leave_by_then_options(self, db_session: Session) -> None:
        message = "I will be 5 hours late due to wheel breakdown and traffic and I will leave by 2am."
        parsed = parse_understanding(message)
        assert parsed.delay_minutes == 300
        assert parsed.leave_by_local == "02:00"
        assert parsed.exception_type == "breakdown"
        assert parsed.eta_local is None
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        first = service.handle_message(created.thread_id, ConversationMessageRequest(message=message))
        first_eta = _latest_eta(db_session, world["shipment"].id)
        assert _local_hour_minute(first_eta) == (23, 30)
        count = _eta_count(db_session, world["shipment"].id)
        retry = service.handle_message(created.thread_id, ConversationMessageRequest(message=message))
        assert _latest_eta(db_session, world["shipment"].id) == first_eta
        assert _eta_count(db_session, world["shipment"].id) == count
        assert "no longer feasible" in first.response.lower() or "no longer feasible" in retry.response.lower()
        options = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Any slot available?"),
        )
        assert parse_understanding("Any slot available?").intent == ConversationIntent.ASK_OPTIONS
        assert "get_available_options" in _tool_names(options)
        assert "create_proposal" not in _tool_names(options)
        assert "accept_proposal" not in _tool_names(options)
        assert options.response != first.response


class TestUnlistedParaphrases:
    def test_options_meaning_not_phrase_list(self) -> None:
        messages = [
            "Can you see what might work for me tonight?",
            "Is there somewhere I can fit in later?",
            "Anything I can make after the delay?",
            "Do I have another window I could take?",
        ]
        for message in messages:
            parsed = parse_understanding(message)
            assert parsed.intent == ConversationIntent.ASK_OPTIONS, message
            assert parsed.asks_options is True, message
            assert parsed.confirm is False, message

    def test_unlisted_options_invoke_read_only_path(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service, created = _thread(db_session, world)
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Can you see what might work for me tonight?"),
        )
        names = _tool_names(result)
        assert "get_available_options" in names
        assert "create_proposal" not in names
        assert "accept_proposal" not in names
        assert "record_eta_update" not in names
