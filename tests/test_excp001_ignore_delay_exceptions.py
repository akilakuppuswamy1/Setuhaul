"""EXCP-001 vs ignore_delay_exceptions: delay-class vs genuinely blocking types."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.models import Appointment, AppointmentSlot, Dock, DriverException, ETAUpdate
from app.models.enums import AppointmentStatus, ETASource, ExceptionStatus, ExceptionType
from app.schemas.allocation import AllocationRequest
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.schemas.proposal import ProposalCreateRequest, ProposalStatus
from app.services.allocation import AllocationService
from app.services.feasibility import FeasibilityService
from app.services.proposal import ProposalService
from tests.test_step5_feasibility import _build_complete_scenario
from tests.test_step7_proposals import _build_proposal_scenario
from tests.test_step8_conversation import _service
from tests.test_step8_reschedule_flow import _build_reschedule_world, _chi


def _excp(result):
    return next(rule for rule in result.rule_results if rule.rule_id == "EXCP-001")


def _add_exception(
    db_session: Session,
    data: dict[str, object],
    exception_type: ExceptionType,
) -> None:
    db_session.add(
        DriverException(
            shipment_id=data["shipment"].id,
            driver_id=data["shipment"].driver_id,
            exception_type=exception_type,
            description=f"{exception_type.value} exception",
            status=ExceptionStatus.OPEN,
            occurred_at=data["now"],
        )
    )


def _evaluate(db_session: Session, data: dict[str, object], *, ignore: bool):
    return FeasibilityService(db_session).evaluate(
        data["shipment"].id,
        FeasibilityEvaluateRequest(
            appointment_slot_id=data["slot"].id,
            evaluated_at=data["now"],
            ignore_delay_exceptions=ignore,
        ),
    )


def _ready_scenario(db_session: Session, exception_type: ExceptionType | None):
    data = _build_complete_scenario(db_session)
    db_session.add(
        ETAUpdate(
            shipment_id=data["shipment"].id,
            previous_eta=None,
            new_eta=data["now"] + timedelta(hours=2, minutes=15),
            update_timestamp=data["now"],
            source=ETASource.DRIVER,
        )
    )
    if exception_type is not None:
        _add_exception(db_session, data, exception_type)
    db_session.commit()
    return data


class TestIgnoreDelayExceptionsByType:
    def test_a_delay_ignored_for_alternative_slot(self, db_session: Session) -> None:
        data = _ready_scenario(db_session, ExceptionType.DELAY)
        blocked = _evaluate(db_session, data, ignore=False)
        ignored = _evaluate(db_session, data, ignore=True)
        assert _excp(blocked).passed is False
        assert blocked.feasible is False
        assert _excp(ignored).passed is True
        assert ignored.feasible is True

    def test_b_traffic_ignored_for_alternative_slot(self, db_session: Session) -> None:
        data = _ready_scenario(db_session, ExceptionType.TRAFFIC)
        blocked = _evaluate(db_session, data, ignore=False)
        ignored = _evaluate(db_session, data, ignore=True)
        assert _excp(blocked).passed is False
        assert _excp(ignored).passed is True
        assert ignored.feasible is True

    def test_c_repair_ignored_for_alternative_slot(self, db_session: Session) -> None:
        data = _ready_scenario(db_session, ExceptionType.REPAIR)
        blocked = _evaluate(db_session, data, ignore=False)
        ignored = _evaluate(db_session, data, ignore=True)
        assert _excp(blocked).passed is False
        assert blocked.feasible is False
        assert _excp(ignored).passed is True
        assert ignored.feasible is True

    def test_c_breakdown_ignored_for_alternative_slot(self, db_session: Session) -> None:
        data = _ready_scenario(db_session, ExceptionType.BREAKDOWN)
        blocked = _evaluate(db_session, data, ignore=False)
        ignored = _evaluate(db_session, data, ignore=True)
        assert _excp(blocked).passed is False
        assert blocked.feasible is False
        assert _excp(ignored).passed is True
        assert ignored.feasible is True

    def test_d_other_still_blocks_when_ignoring_delay_class(self, db_session: Session) -> None:
        data = _ready_scenario(db_session, ExceptionType.OTHER)
        blocked = _evaluate(db_session, data, ignore=False)
        ignored = _evaluate(db_session, data, ignore=True)
        assert _excp(blocked).passed is False
        assert _excp(ignored).passed is False
        assert ignored.feasible is False

    def test_e_no_exception_unchanged(self, db_session: Session) -> None:
        data = _ready_scenario(db_session, None)
        direct = _evaluate(db_session, data, ignore=False)
        ignored = _evaluate(db_session, data, ignore=True)
        assert _excp(direct).passed is True
        assert _excp(ignored).passed is True
        assert direct.feasible is True
        assert ignored.feasible is True


class TestShowProposeConfirmWithRepair:
    def test_f_tyre_repair_show_propose_confirm(self, db_session: Session) -> None:
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

        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        options = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message="I have a tyre problem and will reach around 8:30 PM. Show me what else is available."
            ),
        )
        names = [call.name for call in options.tool_calls]
        assert "create_driver_exception" in names
        assert "record_eta_update" in names
        assert "get_available_options" in names
        assert "request_human_escalation" not in names
        assert options.requires_human is False
        assert "8:30 PM" in options.response

        exceptions = (
            db_session.query(DriverException)
            .filter(DriverException.shipment_id == world["shipment"].id)
            .all()
        )
        assert any(row.exception_type == ExceptionType.REPAIR for row in exceptions)

        direct = FeasibilityService(db_session).evaluate(
            world["shipment"].id,
            FeasibilityEvaluateRequest(appointment_slot_id=world["slot_a"].id),
        )
        assert direct.feasible is False
        assert _excp(direct).passed is False

        ignored = FeasibilityService(db_session).evaluate(
            world["shipment"].id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=world["slot_a"].id,
                ignore_delay_exceptions=True,
            ),
        )
        assert ignored.feasible is True
        assert _excp(ignored).passed is True

        selected = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The first one works."),
        )
        assert any(call.name == "create_proposal" and call.success for call in selected.tool_calls)
        assert all(call.name != "accept_proposal" for call in selected.tool_calls)
        proposal = ProposalService(db_session).get(selected.proposal_id)
        assert proposal.status == ProposalStatus.PROPOSED

        confirmed = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="Confirm it."),
        )
        assert any(call.name == "accept_proposal" and call.success for call in confirmed.tool_calls)
        db_session.expire_all()
        old = db_session.get(Appointment, old_id)
        assert old.status == AppointmentStatus.CANCELLED
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
        new_slot = db_session.get(AppointmentSlot, current[0].appointment_slot_id)
        assert _chi(new_slot.start_time).hour == 20
        assert _chi(new_slot.start_time).minute == 30

    def test_f_breakdown_plus_options_does_not_escalate(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message="My truck broke down. I'll reach around 8:30 PM. Show me what else is available."
            ),
        )
        names = [call.name for call in result.tool_calls]
        assert "create_driver_exception" in names
        assert "get_available_options" in names
        assert "request_human_escalation" not in names
        assert result.requires_human is False
        assert "8:30 PM" in result.response


class TestRevalidationConcurrencyUnchanged:
    def test_g_repair_does_not_stale_proposal_accept(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        db_session.add(
            DriverException(
                shipment_id=data["shipment"].id,
                driver_id=data["shipment"].driver_id,
                exception_type=ExceptionType.REPAIR,
                description="Tyre repair during proposal",
                status=ExceptionStatus.OPEN,
                occurred_at=data["now"],
            )
        )
        db_session.commit()
        accepted = service.accept(created.proposal_id)
        assert accepted.status == ProposalStatus.CONFIRMED

    def test_g_other_exception_still_stales_accept(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        db_session.add(
            DriverException(
                shipment_id=data["shipment"].id,
                driver_id=data["shipment"].driver_id,
                exception_type=ExceptionType.OTHER,
                description="Safety stop",
                status=ExceptionStatus.OPEN,
                occurred_at=data["now"],
            )
        )
        db_session.commit()
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)
