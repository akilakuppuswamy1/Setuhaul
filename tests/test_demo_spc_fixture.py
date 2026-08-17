"""Dedicated SHOW → PROPOSE → CONFIRM demo fixture (SHP-DEMO-SPC-001)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.conversation.provider import FakeLLMProvider
from app.engines.feasibility.rules import CAPACITY_CONSUMING_APPOINTMENT_STATUSES
from app.models import Appointment, AppointmentSlot, Driver, ETAUpdate, Facility, Shipment
from app.models.enums import AppointmentStatus
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from app.services.conversation import ConversationService
from app.services.proposal import PROPOSAL_MARKER
from scripts.seed_e2e_fixtures import seed_e2e_fixtures
from scripts.seed_ops_demo import (
    SPC_DRIVER_EXTERNAL_ID,
    SPC_FACILITY_CODE,
    SPC_ORIGINAL_TAG,
    SPC_SHIPMENT_NUMBER,
    reset_demo_spc_fixture,
    seed_ops_demo,
)

_CONSUMING = tuple(AppointmentStatus(status) for status in CAPACITY_CONSUMING_APPOINTMENT_STATUSES)


def _spc(session: Session) -> Shipment:
    return session.query(Shipment).filter_by(shipment_number=SPC_SHIPMENT_NUMBER).one()


def _consuming_on_slot(session: Session, slot_id) -> int:
    return (
        session.query(Appointment)
        .filter(
            Appointment.appointment_slot_id == slot_id,
            Appointment.status.in_(_CONSUMING),
        )
        .count()
    )


def test_fresh_spc_fixture_exists(db_session: Session) -> None:
    seed_ops_demo(db_session)
    shipment = _spc(db_session)
    driver = db_session.query(Driver).filter_by(external_id=SPC_DRIVER_EXTERNAL_ID).one()
    facility = db_session.query(Facility).filter_by(code=SPC_FACILITY_CODE).one()
    assert shipment.driver_id == driver.id
    assert shipment.destination_facility_id == facility.id
    assert facility.timezone == "Asia/Kolkata"
    original = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.notes.contains(SPC_ORIGINAL_TAG),
        )
        .one()
    )
    assert original.status == AppointmentStatus.REQUESTED
    confirmed = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .count()
    )
    assert confirmed == 0


def test_re_running_fixture_does_not_create_duplicates(db_session: Session) -> None:
    seed_ops_demo(db_session)
    first = reset_demo_spc_fixture(db_session)
    shipments_one = db_session.query(Shipment).filter_by(shipment_number=SPC_SHIPMENT_NUMBER).count()
    drivers_one = db_session.query(Driver).filter_by(external_id=SPC_DRIVER_EXTERNAL_ID).count()
    facilities_one = db_session.query(Facility).filter_by(code=SPC_FACILITY_CODE).count()
    second = reset_demo_spc_fixture(db_session)
    assert first["shipment_id"] == second["shipment_id"]
    assert db_session.query(Shipment).filter_by(shipment_number=SPC_SHIPMENT_NUMBER).count() == shipments_one == 1
    assert db_session.query(Driver).filter_by(external_id=SPC_DRIVER_EXTERNAL_ID).count() == drivers_one == 1
    assert db_session.query(Facility).filter_by(code=SPC_FACILITY_CODE).count() == facilities_one == 1


def test_show_propose_confirm_conversation_and_capacity(db_session: Session) -> None:
    seed_ops_demo(db_session)
    reset_demo_spc_fixture(db_session)
    shipment = _spc(db_session)
    service = ConversationService(db_session, provider=FakeLLMProvider())
    created = service.create_thread(
        ConversationCreateRequest(driver_id=shipment.driver_id, shipment_id=shipment.id)
    )

    delay = service.handle_message(
        created.thread_id,
        ConversationMessageRequest(
            message=(
                "I'll be two hours late. I was supposed to reach by 6:30 PM, "
                "but I'll reach around 8:30 PM."
            )
        ),
    )
    delay_names = [call.name for call in delay.tool_calls]
    assert "record_eta_update" in delay_names
    assert "accept_proposal" not in delay_names
    assert "create_proposal" not in delay_names
    etas = (
        db_session.query(ETAUpdate)
        .filter_by(shipment_id=shipment.id)
        .order_by(ETAUpdate.update_timestamp)
        .all()
    )
    assert len(etas) >= 2
    assert etas[0].new_eta != etas[-1].new_eta
    assert (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .count()
        == 0
    )

    show = service.handle_message(
        created.thread_id,
        ConversationMessageRequest(message="My ETA is 8:30 PM. What options do I have?"),
    )
    show_names = [call.name for call in show.tool_calls]
    assert "get_available_options" in show_names
    assert "create_proposal" not in show_names
    options = (show.metadata or {}).get("presented_options") or []
    assert len(options) >= 1, show.response
    assert (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.REQUESTED,
            Appointment.notes.contains(PROPOSAL_MARKER),
        )
        .count()
        == 0
    )
    target_slot_id = UUID(str(options[0]["slot_id"]))
    consuming_after_show = _consuming_on_slot(db_session, target_slot_id)
    assert consuming_after_show == 0

    propose = service.handle_message(
        created.thread_id,
        ConversationMessageRequest(message="The first one works."),
    )
    propose_names = [call.name for call in propose.tool_calls]
    assert "create_proposal" in propose_names
    assert "accept_proposal" not in propose_names
    assert propose.proposal_id is not None
    proposal_row = db_session.get(Appointment, propose.proposal_id)
    assert proposal_row is not None
    assert proposal_row.status == AppointmentStatus.REQUESTED
    assert PROPOSAL_MARKER in (proposal_row.notes or "")
    assert _consuming_on_slot(db_session, target_slot_id) == consuming_after_show

    confirm = service.handle_message(
        created.thread_id,
        ConversationMessageRequest(message="Confirm"),
    )
    confirm_names = [call.name for call in confirm.tool_calls]
    assert "accept_proposal" in confirm_names
    assert confirm.response
    assert "The appointment is confirmed." in confirm.response
    assert "Say confirm if you want me to book it." not in confirm.response
    confirmed = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == shipment.id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .all()
    )
    assert len(confirmed) == 1
    assert _consuming_on_slot(db_session, confirmed[0].appointment_slot_id) == 1

    reset_demo_spc_fixture(db_session)
    restored = (
        db_session.query(Appointment)
        .filter(
            Appointment.shipment_id == _spc(db_session).id,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        .count()
    )
    assert restored == 0


def test_e2e_seed_includes_spc_reset(db_session: Session) -> None:
    seed_ops_demo(db_session)
    result = seed_e2e_fixtures(db_session)
    assert result["spc"]["shipment_number"] == SPC_SHIPMENT_NUMBER
    slot = db_session.get(AppointmentSlot, UUID(result["spc"]["option_slot_ids"][0]))
    assert slot is not None
    assert _consuming_on_slot(db_session, slot.id) == 0
