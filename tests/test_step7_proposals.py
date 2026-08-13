"""Step 7 proposal lifecycle, revalidation, and API tests."""

import importlib
import pkgutil
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError
from app.models import (
    Appointment,
    AppointmentSlot,
    Carrier,
    Dock,
    Driver,
    ETAUpdate,
    Facility,
    Shipment,
    Vehicle,
)
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    DockStatus,
    EntityStatus,
    ETASource,
    ShipmentStatus,
)
from app.schemas.allocation import AllocationRequest
from app.schemas.proposal import ProposalCreateRequest, ProposalStatus
from app.services.allocation import AllocationService
from app.services.proposal import PROPOSAL_TTL_MINUTES, ProposalService


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _build_proposal_scenario(
    db_session: Session,
    *,
    slot_capacity: int = 5,
    shipment_number: str = "PROP-SHP-1",
    include_eta: bool = True,
) -> dict[str, object]:
    now = _utc(2026, 8, 13, 10, 0)
    carrier = Carrier(name="Prop Carrier", code=f"PC-{uuid.uuid4().hex[:6]}", status=EntityStatus.ACTIVE)
    driver = Driver(carrier=carrier, name="Prop Driver", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate=f"PR-{uuid.uuid4().hex[:4]}",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        status=EntityStatus.ACTIVE,
    )
    facility = Facility(
        name="Prop Facility",
        code=f"PF-{uuid.uuid4().hex[:6]}",
        timezone="UTC",
        status=EntityStatus.ACTIVE,
    )
    dock = Dock(
        facility=facility,
        name="Dock A",
        dock_type="standard",
        max_weight_kg=Decimal("25000"),
        status=DockStatus.AVAILABLE,
    )
    slot = AppointmentSlot(
        facility=facility,
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
        capacity=slot_capacity,
        status=AppointmentSlotStatus.OPEN,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number=shipment_number,
        origin_location="Origin",
        destination_location="Prop Facility",
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("8000"),
        pallet_count=12,
    )
    db_session.add_all([carrier, driver, vehicle, facility, dock, slot, shipment])
    db_session.flush()
    shipment.destination_facility_id = facility.id

    if include_eta:
        db_session.add(
            ETAUpdate(
                shipment_id=shipment.id,
                previous_eta=None,
                new_eta=now + timedelta(hours=2, minutes=15),
                update_timestamp=now,
                source=ETASource.DISPATCH,
            )
        )

    db_session.commit()
    return {
        "shipment": shipment,
        "slot": slot,
        "dock": dock,
        "facility": facility,
        "now": now,
    }


def _add_shipment(
    db_session: Session,
    facility: Facility,
    *,
    shipment_number: str,
    now: datetime,
) -> Shipment:
    existing = db_session.scalar(
        select(Shipment).where(Shipment.destination_facility_id == facility.id).limit(1)
    )
    assert existing is not None
    carrier = existing.carrier
    driver = Driver(carrier=carrier, name=f"Driver {shipment_number}", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate=f"V-{shipment_number}",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        status=EntityStatus.ACTIVE,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number=shipment_number,
        origin_location="Origin",
        destination_location=facility.name,
        destination_facility_id=facility.id,
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("5000"),
        pallet_count=10,
    )
    db_session.add_all([driver, vehicle, shipment])
    db_session.flush()
    db_session.add(
        ETAUpdate(
            shipment_id=shipment.id,
            previous_eta=None,
            new_eta=now + timedelta(hours=2, minutes=15),
            update_timestamp=now,
            source=ETASource.DISPATCH,
        )
    )
    db_session.commit()
    return shipment


def _confirmed_count(db_session: Session, slot_id: uuid.UUID) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.appointment_slot_id == slot_id)
            .where(Appointment.status == AppointmentStatus.CONFIRMED)
        )
        or 0
    )


class TestProposalCreation:
    def test_create_proposal(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        result = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        assert result.status == ProposalStatus.PROPOSED
        assert result.shipment_id == data["shipment"].id
        assert result.slot_id == data["slot"].id
        assert result.dock_id == data["dock"].id
        assert result.appointment_id is None
        assert _confirmed_count(db_session, data["slot"].id) == 0

    def test_create_does_not_allocate(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session, slot_capacity=1)
        service = ProposalService(db_session)
        service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        assert _confirmed_count(db_session, data["slot"].id) == 0

    def test_create_infeasible_rejected(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session, include_eta=False)
        with pytest.raises(SetuHaulError, match="not evaluable|not feasible"):
            ProposalService(db_session).create(
                data["shipment"].id,
                ProposalCreateRequest(appointment_slot_id=data["slot"].id),
            )

    def test_create_missing_shipment(self, db_session: Session) -> None:
        with pytest.raises(NotFoundError):
            ProposalService(db_session).create(
                uuid.uuid4(),
                ProposalCreateRequest(appointment_slot_id=uuid.uuid4()),
            )

    def test_create_missing_slot(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        with pytest.raises(NotFoundError, match="slot"):
            ProposalService(db_session).create(
                data["shipment"].id,
                ProposalCreateRequest(appointment_slot_id=uuid.uuid4()),
            )

    def test_create_slot_wrong_facility(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        other_facility = Facility(
            name="Other",
            code=f"OF-{uuid.uuid4().hex[:4]}",
            timezone="UTC",
            status=EntityStatus.ACTIVE,
        )
        other_slot = AppointmentSlot(
            facility=other_facility,
            start_time=data["now"] + timedelta(hours=5),
            end_time=data["now"] + timedelta(hours=6),
            capacity=1,
            status=AppointmentSlotStatus.OPEN,
        )
        db_session.add_all([other_facility, other_slot])
        db_session.commit()
        with pytest.raises(SetuHaulError, match="destination facility"):
            ProposalService(db_session).create(
                data["shipment"].id,
                ProposalCreateRequest(appointment_slot_id=other_slot.id),
            )


class TestProposalRetrieval:
    def test_get_proposal(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        fetched = service.get(created.proposal_id)
        assert fetched.proposal_id == created.proposal_id
        assert fetched.status == ProposalStatus.PROPOSED

    def test_get_missing_proposal(self, db_session: Session) -> None:
        with pytest.raises(NotFoundError):
            ProposalService(db_session).get(uuid.uuid4())

    def test_get_non_proposal_appointment_rejected(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        appointment = Appointment(
            shipment_id=data["shipment"].id,
            facility_id=data["facility"].id,
            appointment_slot_id=data["slot"].id,
            status=AppointmentStatus.CONFIRMED,
            notes="not a proposal",
        )
        db_session.add(appointment)
        db_session.commit()
        with pytest.raises(NotFoundError):
            ProposalService(db_session).get(appointment.id)


class TestProposalRejection:
    def test_reject_proposal(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        result = service.reject(created.proposal_id)
        assert result.status == ProposalStatus.REJECTED

    def test_reject_idempotent(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        service.reject(created.proposal_id)
        again = service.reject(created.proposal_id)
        assert again.status == ProposalStatus.REJECTED

    def test_reject_confirmed_fails(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        service.accept(created.proposal_id)
        with pytest.raises(ConflictError, match="already confirmed"):
            service.reject(created.proposal_id)


class TestProposalAcceptance:
    def test_accept_confirms_via_step6(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        result = service.accept(created.proposal_id)
        assert result.status == ProposalStatus.CONFIRMED
        assert result.appointment_id is not None
        assert _confirmed_count(db_session, data["slot"].id) == 1

    def test_accept_idempotent(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        first = service.accept(created.proposal_id)
        second = service.accept(created.proposal_id)
        assert second.status == ProposalStatus.CONFIRMED
        assert second.appointment_id == first.appointment_id
        assert _confirmed_count(db_session, data["slot"].id) == 1

    def test_accept_rejected_fails(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        service.reject(created.proposal_id)
        with pytest.raises(SetuHaulError, match="rejected"):
            service.accept(created.proposal_id)

    def test_accept_expired_fails(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        appointment = db_session.get(Appointment, created.proposal_id)
        appointment.created_at = datetime.now(timezone.utc) - timedelta(
            minutes=PROPOSAL_TTL_MINUTES + 1
        )
        db_session.commit()
        with pytest.raises(ConflictError, match="expired"):
            service.accept(created.proposal_id)

    def test_accept_stale_when_capacity_exhausted(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session, slot_capacity=1)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        other = _add_shipment(
            db_session,
            data["facility"],
            shipment_number="PROP-SHP-2",
            now=data["now"],
        )
        AllocationService(db_session).allocate(
            other.id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)
        fetched = service.get(created.proposal_id)
        assert fetched.status == ProposalStatus.STALE
        assert fetched.reason in ("slot_capacity_changed", "feasibility_changed")

    def test_step6_failure_does_not_confirm_proposal(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session, slot_capacity=1)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        other = _add_shipment(
            db_session,
            data["facility"],
            shipment_number="PROP-SHP-3",
            now=data["now"],
        )
        AllocationService(db_session).allocate(
            other.id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        with pytest.raises(ConflictError):
            service.accept(created.proposal_id)
        assert _confirmed_count(db_session, data["slot"].id) == 1


class TestProposalExpiration:
    def test_expired_on_get(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        appointment = db_session.get(Appointment, created.proposal_id)
        appointment.created_at = datetime.now(timezone.utc) - timedelta(
            minutes=PROPOSAL_TTL_MINUTES + 5
        )
        db_session.commit()
        fetched = service.get(created.proposal_id)
        assert fetched.status == ProposalStatus.EXPIRED


class TestInvalidTransitions:
    def test_cannot_accept_stale(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session, slot_capacity=1)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        other = _add_shipment(
            db_session,
            data["facility"],
            shipment_number="PROP-SHP-4",
            now=data["now"],
        )
        AllocationService(db_session).allocate(
            other.id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        with pytest.raises(ConflictError):
            service.accept(created.proposal_id)
        with pytest.raises(SetuHaulError, match="stale"):
            service.accept(created.proposal_id)


class TestFeasibilityChangedAfterProposal:
    def test_stale_when_feasibility_lost(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        data["slot"].status = AppointmentSlotStatus.CLOSED
        db_session.commit()
        with pytest.raises(ConflictError, match="stale"):
            service.accept(created.proposal_id)


class TestSessionRecovery:
    def test_session_usable_after_accept_failure(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session, slot_capacity=1)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        other = _add_shipment(
            db_session,
            data["facility"],
            shipment_number="PROP-SHP-5",
            now=data["now"],
        )
        AllocationService(db_session).allocate(
            other.id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        with pytest.raises(ConflictError):
            service.accept(created.proposal_id)
        result = service.get(created.proposal_id)
        assert result.status == ProposalStatus.STALE


class TestProposalAPI:
    def test_create_proposal_api(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        from app.core.database import get_db
        from app.main import app as fastapi_app

        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_db] = override_get_db
        with TestClient(fastapi_app) as client:
            response = client.post(
                f"/shipments/{data['shipment'].id}/proposals",
                json={
                    "appointment_slot_id": str(data["slot"].id),
                    "dock_id": str(data["dock"].id),
                },
            )
            assert response.status_code == 201
            body = response.json()
            assert body["status"] == "proposed"
            assert body["proposal_id"] is not None
        fastapi_app.dependency_overrides.clear()

    def test_accept_proposal_api(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(
                appointment_slot_id=data["slot"].id,
                dock_id=data["dock"].id,
            ),
        )
        from app.core.database import get_db
        from app.main import app as fastapi_app

        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_db] = override_get_db
        with TestClient(fastapi_app) as client:
            response = client.post(f"/proposals/{created.proposal_id}/accept")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "confirmed"
            assert body["appointment_id"] is not None
        fastapi_app.dependency_overrides.clear()

    def test_stale_returns_409(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session, slot_capacity=1)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        other = _add_shipment(
            db_session,
            data["facility"],
            shipment_number="PROP-SHP-6",
            now=data["now"],
        )
        AllocationService(db_session).allocate(
            other.id,
            AllocationRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        from app.core.database import get_db
        from app.main import app as fastapi_app

        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_db] = override_get_db
        with TestClient(fastapi_app) as client:
            response = client.post(f"/proposals/{created.proposal_id}/accept")
            assert response.status_code == 409
            assert "stale" in response.json()["detail"].lower()
        fastapi_app.dependency_overrides.clear()

    def test_no_direct_status_mutation_endpoint(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        from app.core.database import get_db
        from app.main import app as fastapi_app

        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_db] = override_get_db
        with TestClient(fastapi_app) as client:
            response = client.patch(
                f"/proposals/{created.proposal_id}",
                json={"status": "confirmed"},
            )
            assert response.status_code == 405
        fastapi_app.dependency_overrides.clear()

    def test_api_errors_safe(self, db_session: Session) -> None:
        from app.core.database import get_db
        from app.main import app as fastapi_app

        def override_get_db():
            yield db_session

        fastapi_app.dependency_overrides[get_db] = override_get_db
        with TestClient(fastapi_app) as client:
            response = client.get(f"/proposals/{uuid.uuid4()}")
            assert response.status_code == 404
            body = response.json()
            assert "detail" in body
            assert "sql" not in body["detail"].lower()
            assert "traceback" not in body["detail"].lower()
        fastapi_app.dependency_overrides.clear()


class TestAcceptanceInvokesStep6:
    def test_accept_calls_allocation_service(self, db_session: Session) -> None:
        data = _build_proposal_scenario(db_session)
        service = ProposalService(db_session)
        created = service.create(
            data["shipment"].id,
            ProposalCreateRequest(appointment_slot_id=data["slot"].id),
        )
        with patch.object(
            service._allocation_service,
            "allocate",
            wraps=service._allocation_service.allocate,
        ) as mock_allocate:
            service.accept(created.proposal_id)
            mock_allocate.assert_called_once()


class TestNoAIImports:
    def test_no_ai_framework_imports_in_step7(self) -> None:
        forbidden = ("langchain", "openai", "anthropic", "langgraph")
        step7_modules = [
            importlib.import_module("app.services.proposal"),
            importlib.import_module("app.api.proposals"),
            importlib.import_module("app.schemas.proposal"),
        ]
        for module in step7_modules:
            source = importlib.import_module(module.__name__).__file__
            assert source is not None
            with open(source, encoding="utf-8") as handle:
                content = handle.read().lower()
            for term in forbidden:
                assert term not in content

    def test_no_ai_in_app_package(self) -> None:
        import app

        forbidden = ("langchain", "langgraph", "openai")
        for _finder, name, _ispkg in pkgutil.walk_packages(app.__path__, app.__name__ + "."):
            if "proposal" not in name and "step7" not in name:
                continue
            module = importlib.import_module(name)
            if module.__file__ is None:
                continue
            with open(module.__file__, encoding="utf-8") as handle:
                content = handle.read().lower()
            for term in forbidden:
                assert term not in content


class TestDeterministicStateTransitions:
    def test_valid_transitions_documented(self) -> None:
        from app.services.proposal import _VALID_TRANSITIONS

        assert ProposalStatus.PROPOSED in _VALID_TRANSITIONS
        assert ProposalStatus.CONFIRMED in _VALID_TRANSITIONS[ProposalStatus.ACCEPTED]
        assert ProposalStatus.CONFIRMED not in _VALID_TRANSITIONS[ProposalStatus.REJECTED]
