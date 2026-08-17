"""Delay → next-slot recovery: original appointment preserved, feasible options returned."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.ai.conversation.intents import parse_understanding
from app.ai.conversation.models import ConversationIntent
from app.models import Appointment, AppointmentSlot, Carrier, Dock, Driver, ETAUpdate, Facility, Shipment, Vehicle
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    DockStatus,
    EntityStatus,
    ETASource,
    ShipmentStatus,
)
from app.schemas.conversation import ConversationCreateRequest, ConversationMessageRequest
from app.schemas.proposal import ProposalStatus
from app.services.proposal import ProposalService
from tests.test_step8_conversation import _service


CHI = ZoneInfo("America/Chicago")
DEMO_DAY = datetime(2026, 8, 13, tzinfo=CHI)


def _chi(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CHI)


def _build_reschedule_world(db_session: Session) -> dict[str, object]:
    original_start = DEMO_DAY.replace(hour=18, minute=30)
    original_end = DEMO_DAY.replace(hour=19, minute=0)
    slot_a_start = DEMO_DAY.replace(hour=20, minute=30)
    slot_a_end = DEMO_DAY.replace(hour=21, minute=0)
    slot_b_start = DEMO_DAY.replace(hour=20, minute=30)
    slot_b_end = DEMO_DAY.replace(hour=21, minute=30)

    carrier = Carrier(name="Reschedule Carrier", code="RS-CHI", status=EntityStatus.ACTIVE)
    driver = Driver(carrier=carrier, name="Alex Driver", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate="CHI-5437-VAN",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        status=EntityStatus.ACTIVE,
    )
    facility = Facility(
        name="Chicago Cross-Dock",
        code="CHI-XD-TEST",
        timezone="America/Chicago",
        status=EntityStatus.ACTIVE,
    )
    dock = Dock(
        facility=facility,
        name="Dock A",
        dock_type="standard",
        max_weight_kg=Decimal("25000"),
        status=DockStatus.AVAILABLE,
    )
    original_slot = AppointmentSlot(
        facility=facility,
        start_time=original_start.astimezone(timezone.utc),
        end_time=original_end.astimezone(timezone.utc),
        capacity=1,
        status=AppointmentSlotStatus.OPEN,
    )
    slot_a = AppointmentSlot(
        facility=facility,
        start_time=slot_a_start.astimezone(timezone.utc),
        end_time=slot_a_end.astimezone(timezone.utc),
        capacity=1,
        status=AppointmentSlotStatus.OPEN,
    )
    slot_b = AppointmentSlot(
        facility=facility,
        start_time=slot_b_start.astimezone(timezone.utc),
        end_time=slot_b_end.astimezone(timezone.utc),
        capacity=1,
        status=AppointmentSlotStatus.OPEN,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number="SHP-CHI-5437",
        origin_location="Milwaukee, WI",
        destination_location="Chicago Cross-Dock",
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("9000"),
        pallet_count=14,
    )
    db_session.add_all(
        [carrier, driver, vehicle, facility, dock, original_slot, slot_a, slot_b, shipment]
    )
    db_session.flush()
    shipment.destination_facility_id = facility.id
    db_session.add(
        ETAUpdate(
            shipment_id=shipment.id,
            previous_eta=None,
            new_eta=original_start.astimezone(timezone.utc),
            update_timestamp=DEMO_DAY.replace(hour=8, minute=0).astimezone(timezone.utc),
            source=ETASource.DISPATCH,
            reason="Original scheduled arrival",
        )
    )
    original_appt = Appointment(
        shipment_id=shipment.id,
        facility_id=facility.id,
        appointment_slot_id=original_slot.id,
        dock_id=dock.id,
        status=AppointmentStatus.REQUESTED,
        notes="Original appointment",
    )
    db_session.add(original_appt)
    db_session.commit()
    return {
        "driver": driver,
        "shipment": shipment,
        "facility": facility,
        "original_slot": original_slot,
        "slot_a": slot_a,
        "slot_b": slot_b,
        "original_appointment": original_appt,
        "original_start": original_start,
    }


def _build_closed_world(db_session: Session) -> dict[str, object]:
    world = _build_reschedule_world(db_session)
    for slot in (world["slot_a"], world["slot_b"], world["original_slot"]):
        slot.status = AppointmentSlotStatus.CLOSED
    db_session.commit()
    return world


class TestDriverDelayPreservesOriginalAppointment:
    def test_delay_updates_eta_not_original_window(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        parsed = parse_understanding(
            "I'm going to be 2 hours late. I was supposed to reach by 6:30 PM, but I'll reach around 8:30 PM because of traffic."
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
        assert all(call.name != "accept_proposal" for call in result.tool_calls)

        latest = (
            db_session.query(ETAUpdate)
            .filter(ETAUpdate.shipment_id == world["shipment"].id)
            .order_by(ETAUpdate.update_timestamp.desc())
            .first()
        )
        assert latest is not None
        new_eta = _chi(latest.new_eta)
        assert new_eta.hour == 20 and new_eta.minute == 30
        delay = new_eta - world["original_start"]
        assert delay == timedelta(hours=2)

        original = db_session.get(Appointment, world["original_appointment"].id)
        assert original is not None
        assert original.appointment_slot_id == world["original_slot"].id
        assert original.status == AppointmentStatus.REQUESTED
        slot = db_session.get(AppointmentSlot, world["original_slot"].id)
        assert slot is not None
        assert _chi(slot.start_time).hour == 18
        assert _chi(slot.start_time).minute == 30


class TestNextSlotWhenFeasible:
    def test_next_slot_returns_options_without_escalation(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message=(
                    "I'm going to be 2 hours late. I was supposed to reach by 6:30 PM, "
                    "but I'll reach around 8:30 PM because of traffic."
                )
            ),
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="next slot?"),
        )
        names = [call.name for call in result.tool_calls]
        assert result.intent == ConversationIntent.ASK_OPTIONS.value
        assert "get_available_options" in names
        assert all(call.success for call in result.tool_calls if call.name == "get_available_options")
        assert "request_human_escalation" not in names
        assert result.requires_human is False
        assert "1." in result.response
        assert "8:30 PM" in result.response
        assert all(call.name != "create_proposal" for call in result.tool_calls)
        assert all(call.name != "accept_proposal" for call in result.tool_calls)
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

        original = db_session.get(Appointment, world["original_appointment"].id)
        assert original.appointment_slot_id == world["original_slot"].id


class TestNextSlotWhenNoneFeasible:
    def test_no_open_slots_escalates(self, db_session: Session) -> None:
        world = _build_closed_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message=(
                    "I'm going to be 2 hours late. I was supposed to reach by 6:30 PM, "
                    "but I'll reach around 8:30 PM because of traffic."
                )
            ),
        )
        result = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="next slot?"),
        )
        names = [call.name for call in result.tool_calls]
        assert "get_available_options" in names
        assert "request_human_escalation" in names
        assert result.requires_human is True
        assert result.intent == ConversationIntent.HUMAN_ESCALATION.value
        assert "no safe feasible option" in result.response.lower()


class TestProposalDoesNotConfirmOrOverwriteOriginal:
    def test_selecting_next_slot_creates_proposed_not_confirmed(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message=(
                    "I'm going to be 2 hours late. I was supposed to reach by 6:30 PM, "
                    "but I'll reach around 8:30 PM because of traffic."
                )
            ),
        )
        options = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="next slot?"),
        )
        assert options.requires_human is False
        chosen = service.handle_message(
            created.thread_id,
            ConversationMessageRequest(message="The first one works."),
        )
        assert any(call.name == "create_proposal" and call.success for call in chosen.tool_calls)
        assert all(call.name != "accept_proposal" for call in chosen.tool_calls)
        assert chosen.proposal_id is not None
        proposal = ProposalService(db_session).get(chosen.proposal_id)
        assert proposal.status == ProposalStatus.PROPOSED
        assert db_session.query(Appointment).filter(Appointment.status == AppointmentStatus.CONFIRMED).count() == 0

        original = db_session.get(Appointment, world["original_appointment"].id)
        assert original.appointment_slot_id == world["original_slot"].id
        assert original.status == AppointmentStatus.REQUESTED
        proposed_slot = db_session.get(AppointmentSlot, proposal.slot_id)
        assert proposed_slot is not None
        assert _chi(proposed_slot.start_time).hour == 20
        assert _chi(proposed_slot.start_time).minute == 30


class TestTimezoneAwareDelay:
    def test_delay_uses_facility_timezone(self, db_session: Session) -> None:
        world = _build_reschedule_world(db_session)
        service = _service(db_session)
        created = service.create_thread(
            ConversationCreateRequest(driver_id=world["driver"].id, shipment_id=world["shipment"].id)
        )
        service.handle_message(
            created.thread_id,
            ConversationMessageRequest(
                message=(
                    "I'm going to be 2 hours late. I was supposed to reach by 6:30 PM, "
                    "but I'll reach around 8:30 PM because of traffic."
                )
            ),
        )
        latest = (
            db_session.query(ETAUpdate)
            .filter(ETAUpdate.shipment_id == world["shipment"].id)
            .order_by(ETAUpdate.update_timestamp.desc())
            .first()
        )
        assert latest.new_eta is not None
        local = _chi(latest.new_eta)
        assert local.hour == 20
        original_local = world["original_start"].astimezone(CHI)
        assert original_local.hour == 18
        assert (local - original_local) == timedelta(hours=2)
        utc = _chi(latest.new_eta).astimezone(timezone.utc)
        assert utc.hour == 1
        assert utc.minute == 30
