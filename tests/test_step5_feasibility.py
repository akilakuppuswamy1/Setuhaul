"""Step 5 deterministic feasibility engine tests."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.engines.feasibility.engine import FeasibilityEngine
from app.engines.feasibility.models import (
    AppointmentFacts,
    DockFacts,
    EntityStatusFacts,
    FacilityFacts,
    FacilityRuleFacts,
    FeasibilityContext,
    FeasibilityOutcome,
    ShipmentFacts,
    SlotFacts,
    VehicleFacts,
)
from app.models import (
    Appointment,
    AppointmentSlot,
    Carrier,
    Dock,
    Driver,
    DriverException,
    Facility,
    FacilityRule,
    Shipment,
    Vehicle,
)
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    DockStatus,
    EntityStatus,
    ExceptionStatus,
    ExceptionType,
    ShipmentStatus,
)
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.services.feasibility import FeasibilityService


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _feasible_context(**overrides) -> FeasibilityContext:
    shipment_id = uuid.uuid4()
    facility_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    dock_id = uuid.uuid4()
    evaluated_at = _utc(2026, 8, 13, 10, 0)

    defaults = FeasibilityContext(
        evaluated_at=evaluated_at,
        shipment=ShipmentFacts(
            shipment_id=shipment_id,
            shipment_number="FEAS-001",
            is_active=True,
            status="in_transit",
            destination_facility_id=facility_id,
            carrier_id=uuid.uuid4(),
            driver_id=uuid.uuid4(),
            vehicle_id=uuid.uuid4(),
            weight_kg=Decimal("5000"),
            volume_cbm=Decimal("20"),
            pallet_count=10,
            scheduled_delivery_at=None,
        ),
        carrier=EntityStatusFacts(uuid.uuid4(), "Carrier", "active"),
        driver=EntityStatusFacts(uuid.uuid4(), "Driver", "active"),
        vehicle=VehicleFacts(
            uuid.uuid4(),
            "53ft_dry_van",
            "active",
            Decimal("20000"),
            Decimal("90"),
        ),
        facility=FacilityFacts(facility_id, "FAC-01", "active", "UTC"),
        appointment=AppointmentFacts(
            uuid.uuid4(),
            "confirmed",
            facility_id,
            slot_id,
            dock_id,
        ),
        slot=SlotFacts(
            slot_id,
            facility_id,
            _utc(2026, 8, 13, 12, 0),
            _utc(2026, 8, 13, 13, 0),
            capacity=3,
            status="open",
            booked_count=1,
            includes_current_shipment=True,
        ),
        dock=DockFacts(
            dock_id,
            facility_id,
            "Dock A",
            "available",
            Decimal("25000"),
            False,
        ),
        latest_eta=_utc(2026, 8, 13, 12, 30),
        active_exceptions=(),
        facility_rules=(),
        daily_appointment_count=1,
    )
    return overrides.get("replace", defaults) if "replace" in overrides else defaults


class TestFeasibilityEngineUnit:
    def test_fully_feasible_case(self) -> None:
        engine = FeasibilityEngine()
        result = engine.evaluate(_feasible_context())
        assert result.outcome == FeasibilityOutcome.FEASIBLE
        assert result.feasible is True
        assert result.blocking_reasons == ()

    def test_inactive_shipment_blocks(self) -> None:
        ctx = _feasible_context()
        ctx = FeasibilityContext(
            **{
                **ctx.__dict__,
                "shipment": ShipmentFacts(
                    **{**ctx.shipment.__dict__, "is_active": False}
                ),
            }
        )
        result = FeasibilityEngine().evaluate(ctx)
        assert result.outcome == FeasibilityOutcome.NOT_FEASIBLE
        assert any(rule.rule_id == "SHIP-001" and not rule.passed for rule in result.rule_results)

    def test_missing_appointment_context_blocks(self) -> None:
        ctx = _feasible_context()
        ctx = FeasibilityContext(
            **{**ctx.__dict__, "appointment": None, "slot": None, "dock": None}
        )
        result = FeasibilityEngine().evaluate(ctx)
        assert result.outcome == FeasibilityOutcome.NOT_FEASIBLE
        assert any(rule.rule_id == "APPT-001" and not rule.passed for rule in result.rule_results)

    def test_slot_capacity_failure(self) -> None:
        ctx = _feasible_context()
        ctx = FeasibilityContext(
            **{
                **ctx.__dict__,
                "slot": SlotFacts(
                    **{
                        **ctx.slot.__dict__,
                        "booked_count": 3,
                        "capacity": 3,
                        "includes_current_shipment": False,
                    }
                ),
            }
        )
        result = FeasibilityEngine().evaluate(ctx)
        assert any(rule.rule_id == "SLOT-004" and not rule.passed for rule in result.rule_results)

    def test_facility_rule_max_daily_failure(self) -> None:
        ctx = _feasible_context()
        rule = FacilityRuleFacts(
            uuid.uuid4(),
            "max_daily_appointments",
            {"limit": 2},
            _utc(2026, 1, 1),
            None,
            True,
        )
        ctx = FeasibilityContext(
            **{**ctx.__dict__, "facility_rules": (rule,), "daily_appointment_count": 2}
        )
        result = FeasibilityEngine().evaluate(ctx)
        assert any(rule.rule_id == "RULE-001" and not rule.passed for rule in result.rule_results)

    def test_dock_compatibility_failure(self) -> None:
        ctx = _feasible_context()
        rule = FacilityRuleFacts(
            uuid.uuid4(),
            "dock_compatibility",
            {"allowed_vehicle_types": ["48ft_reefer"], "max_pallets": 24},
            _utc(2026, 1, 1),
            None,
            True,
        )
        ctx = FeasibilityContext(**{**ctx.__dict__, "facility_rules": (rule,)})
        result = FeasibilityEngine().evaluate(ctx)
        assert any(rule.rule_id == "RULE-003" and not rule.passed for rule in result.rule_results)

    def test_vehicle_weight_failure(self) -> None:
        ctx = _feasible_context()
        ctx = FeasibilityContext(
            **{
                **ctx.__dict__,
                "shipment": ShipmentFacts(
                    **{**ctx.shipment.__dict__, "weight_kg": Decimal("25000")}
                ),
                "vehicle": VehicleFacts(
                    **{**ctx.vehicle.__dict__, "max_weight_kg": Decimal("20000")}
                ),
            }
        )
        result = FeasibilityEngine().evaluate(ctx)
        assert any(rule.rule_id == "VEHI-002" and not rule.passed for rule in result.rule_results)

    def test_active_exception_blocks(self) -> None:
        from app.engines.feasibility.models import DriverExceptionFacts

        ctx = _feasible_context()
        exc = DriverExceptionFacts(uuid.uuid4(), "traffic", "open", "Delay")
        result = FeasibilityEngine().evaluate(
            FeasibilityContext(**{**ctx.__dict__, "active_exceptions": (exc,)})
        )
        assert any(rule.rule_id == "EXCP-001" and not rule.passed for rule in result.rule_results)

    def test_resolved_exception_does_not_block(self) -> None:
        from app.engines.feasibility.models import DriverExceptionFacts

        ctx = _feasible_context()
        exc = DriverExceptionFacts(uuid.uuid4(), "traffic", "resolved", "Resolved")
        result = FeasibilityEngine().evaluate(
            FeasibilityContext(**{**ctx.__dict__, "active_exceptions": (exc,)})
        )
        exc_rule = next(rule for rule in result.rule_results if rule.rule_id == "EXCP-001")
        assert exc_rule.passed is True

    def test_acknowledged_exception_blocks(self) -> None:
        from app.engines.feasibility.models import DriverExceptionFacts

        ctx = _feasible_context()
        exc = DriverExceptionFacts(uuid.uuid4(), "delay", "acknowledged", "Acked")
        result = FeasibilityEngine().evaluate(
            FeasibilityContext(**{**ctx.__dict__, "active_exceptions": (exc,)})
        )
        assert any(rule.rule_id == "EXCP-001" and not rule.passed for rule in result.rule_results)

    def test_missing_eta_makes_evaluation_not_evaluable(self) -> None:
        ctx = _feasible_context()
        result = FeasibilityEngine().evaluate(
            FeasibilityContext(**{**ctx.__dict__, "latest_eta": None})
        )
        assert result.outcome == FeasibilityOutcome.NOT_EVALUABLE
        eta_rule = next(rule for rule in result.rule_results if rule.rule_id == "ETA-001")
        assert eta_rule.passed is False
        assert eta_rule.evaluable is False

    def test_multiple_failures_have_deterministic_order(self) -> None:
        ctx = _feasible_context()
        ctx = FeasibilityContext(
            **{
                **ctx.__dict__,
                "shipment": ShipmentFacts(
                    **{
                        **ctx.shipment.__dict__,
                        "is_active": False,
                        "status": "cancelled",
                    }
                ),
            }
        )
        result = FeasibilityEngine().evaluate(ctx)
        failed_ids = [rule.rule_id for rule in result.rule_results if not rule.passed]
        assert failed_ids.index("SHIP-001") < failed_ids.index("SHIP-002")

    def test_identical_input_produces_identical_result(self) -> None:
        engine = FeasibilityEngine()
        ctx = _feasible_context()
        first = engine.evaluate(ctx)
        second = engine.evaluate(ctx)
        assert first.outcome == second.outcome
        assert first.blocking_reasons == second.blocking_reasons
        assert [rule.rule_id for rule in first.rule_results] == [
            rule.rule_id for rule in second.rule_results
        ]


class TestFeasibilityService:
    def test_missing_shipment_raises_not_found(self, db_session: Session) -> None:
        service = FeasibilityService(db_session)
        with pytest.raises(NotFoundError):
            service.evaluate(uuid.uuid4())

    def test_seeded_shipment_with_open_exception_not_feasible(
        self, seeded_session: dict[str, object], db_session: Session
    ) -> None:
        shipment = seeded_session["shipments"][0]
        service = FeasibilityService(db_session)
        result = service.evaluate(
            shipment.id,
            FeasibilityEvaluateRequest(evaluated_at=_utc(2026, 8, 13, 10, 0)),
        )
        assert result.feasible is False
        assert result.outcome == FeasibilityOutcome.NOT_FEASIBLE
        assert any("active driver exception" in reason for reason in result.blocking_reasons)

    def test_seeded_shipment_feasible_after_exception_resolved(
        self, seeded_session: dict[str, object], db_session: Session
    ) -> None:
        shipment = seeded_session["shipments"][0]
        exception = seeded_session["exception"]
        exception.status = ExceptionStatus.RESOLVED
        exception.resolved_at = _utc(2026, 8, 13, 10, 0)
        db_session.commit()

        result = FeasibilityService(db_session).evaluate(
            shipment.id,
            FeasibilityEvaluateRequest(evaluated_at=_utc(2026, 8, 13, 10, 0)),
        )
        assert result.feasible is True
        assert result.outcome == FeasibilityOutcome.FEASIBLE

    def test_shipment_without_appointment_not_feasible(
        self, seeded_session: dict[str, object], db_session: Session
    ) -> None:
        shipment = seeded_session["shipments"][1]
        result = FeasibilityService(db_session).evaluate(
            shipment.id,
            FeasibilityEvaluateRequest(evaluated_at=_utc(2026, 8, 13, 10, 0)),
        )
        assert result.feasible is False
        assert any("appointment or slot context" in reason.lower() for reason in result.blocking_reasons)

    def test_missing_destination_facility(
        self, db_session: Session
    ) -> None:
        carrier = Carrier(name="No Fac Carrier", code="NF-01")
        shipment = Shipment(
            carrier=carrier,
            shipment_number="NO-FAC-1",
            origin_location="A",
            destination_location="B",
            status=ShipmentStatus.ASSIGNED,
            is_active=True,
        )
        db_session.add_all([carrier, shipment])
        db_session.commit()

        result = FeasibilityService(db_session).evaluate(shipment.id)
        assert result.feasible is False
        assert any(rule.rule_id == "SHIP-003" and not rule.passed for rule in result.rule_results)

    def test_invalid_slot_relationship(
        self, seeded_session: dict[str, object], db_session: Session
    ) -> None:
        shipment = seeded_session["shipments"][1]
        other_facility = Facility(
            name="Other",
            code="OTHER-01",
            address="Elsewhere",
            timezone="UTC",
            status=EntityStatus.ACTIVE,
        )
        db_session.add(other_facility)
        db_session.flush()
        foreign_slot = AppointmentSlot(
            facility_id=other_facility.id,
            start_time=_utc(2026, 8, 13, 14, 0),
            end_time=_utc(2026, 8, 13, 15, 0),
            capacity=1,
            status=AppointmentSlotStatus.OPEN,
        )
        db_session.add(foreign_slot)
        db_session.commit()

        result = FeasibilityService(db_session).evaluate(
            shipment.id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=foreign_slot.id,
                evaluated_at=_utc(2026, 8, 13, 10, 0),
            ),
        )
        assert any(rule.rule_id == "SLOT-002" and not rule.passed for rule in result.rule_results)

    def test_no_database_mutation_during_evaluation(
        self, seeded_session: dict[str, object], db_session: Session
    ) -> None:
        tables = [
            Appointment,
            AppointmentSlot,
            Carrier,
            Dock,
            Driver,
            DriverException,
            Facility,
            FacilityRule,
            Shipment,
            Vehicle,
        ]
        before = {
            table.__tablename__: db_session.scalar(select(func.count()).select_from(table))
            for table in tables
        }
        shipment = seeded_session["shipments"][0]
        FeasibilityService(db_session).evaluate(
            shipment.id,
            FeasibilityEvaluateRequest(evaluated_at=_utc(2026, 8, 13, 10, 0)),
        )
        after = {
            table.__tablename__: db_session.scalar(select(func.count()).select_from(table))
            for table in tables
        }
        assert before == after


class TestFeasibilityAPI:
    def test_api_success(self, seeded_client: TestClient, seeded_session: dict[str, object]) -> None:
        shipment = seeded_session["shipments"][0]
        exception = seeded_session["exception"]
        exception.status = ExceptionStatus.RESOLVED
        exception.resolved_at = _utc(2026, 8, 13, 10, 0)

        response = seeded_client.post(
            f"/shipments/{shipment.id}/feasibility",
            json={"evaluated_at": "2026-08-13T10:00:00+00:00"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["feasible"] is True
        assert body["outcome"] == "feasible"
        assert isinstance(body["rule_results"], list)
        assert len(body["rule_results"]) > 0

    def test_api_missing_shipment(self, client: TestClient) -> None:
        response = client.post(f"/shipments/{uuid.uuid4()}/feasibility", json={})
        assert response.status_code == 404
        assert "detail" in response.json()
        assert "traceback" not in response.text.lower()

    def test_api_validation_failure(self, seeded_client: TestClient, seeded_session: dict[str, object]) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/feasibility",
            json={"evaluated_at": "not-a-datetime"},
        )
        assert response.status_code == 422

    def test_api_missing_slot_returns_404(
        self, seeded_client: TestClient, seeded_session: dict[str, object]
    ) -> None:
        shipment = seeded_session["shipments"][1]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/feasibility",
            json={"appointment_slot_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404

    def test_api_error_does_not_expose_internals(self, client: TestClient) -> None:
        response = client.post(f"/shipments/{uuid.uuid4()}/feasibility", json={})
        assert response.status_code == 404
        assert "sqlalchemy" not in response.text.lower()
        assert "traceback" not in response.text.lower()


def _build_complete_scenario(db_session: Session) -> dict[str, object]:
    now = _utc(2026, 8, 13, 10, 0)
    carrier = Carrier(name="Complete Carrier", code="COMP-01", status=EntityStatus.ACTIVE)
    driver = Driver(carrier=carrier, name="Complete Driver", status=EntityStatus.ACTIVE)
    vehicle = Vehicle(
        carrier=carrier,
        license_plate="OK-1",
        vehicle_type="53ft_dry_van",
        max_weight_kg=Decimal("20000"),
        max_volume_cbm=Decimal("90"),
        status=EntityStatus.ACTIVE,
    )
    facility = Facility(
        name="Complete Facility",
        code="COMP-FAC",
        address="1 Complete Way",
        timezone="UTC",
        status=EntityStatus.ACTIVE,
    )
    dock = Dock(
        facility=facility,
        name="Dock 1",
        dock_type="standard",
        max_weight_kg=Decimal("25000"),
        status=DockStatus.AVAILABLE,
    )
    slot = AppointmentSlot(
        facility=facility,
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
        capacity=5,
        status=AppointmentSlotStatus.OPEN,
    )
    shipment = Shipment(
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        shipment_number="COMP-SHP-1",
        origin_location="Origin",
        destination_location="Complete Facility",
        destination_facility_id=facility.id,
        status=ShipmentStatus.IN_TRANSIT,
        is_active=True,
        weight_kg=Decimal("8000"),
        volume_cbm=Decimal("30"),
        pallet_count=12,
    )
    db_session.add_all([carrier, driver, vehicle, facility, dock, slot, shipment])
    db_session.flush()
    shipment.destination_facility_id = facility.id
    appointment = Appointment(
        shipment_id=shipment.id,
        facility_id=facility.id,
        appointment_slot_id=slot.id,
        dock_id=dock.id,
        status=AppointmentStatus.CONFIRMED,
    )
    db_session.add(appointment)
    db_session.commit()
    return {
        "shipment": shipment,
        "slot": slot,
        "dock": dock,
        "facility": facility,
        "now": now,
    }


class TestFeasibilityScenarios:
    def test_complete_scenario_is_feasible(self, db_session: Session) -> None:
        data = _build_complete_scenario(db_session)
        from app.models import ETAUpdate
        from app.models.enums import ETASource

        db_session.add(
            ETAUpdate(
                shipment_id=data["shipment"].id,
                previous_eta=None,
                new_eta=data["now"] + timedelta(hours=2, minutes=15),
                update_timestamp=data["now"],
                source=ETASource.DISPATCH,
            )
        )
        db_session.commit()

        result = FeasibilityService(db_session).evaluate(
            data["shipment"].id,
            FeasibilityEvaluateRequest(evaluated_at=data["now"]),
        )
        assert result.feasible is True

    def test_inactive_driver_blocks(self, db_session: Session) -> None:
        data = _build_complete_scenario(db_session)
        driver = data["shipment"].driver
        assert driver is not None
        driver.status = EntityStatus.INACTIVE
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        assert any(rule.rule_id == "DRIV-001" and not rule.passed for rule in result.rule_results)

    def test_closed_slot_blocks(self, db_session: Session) -> None:
        data = _build_complete_scenario(db_session)
        data["slot"].status = AppointmentSlotStatus.CLOSED
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        assert any(rule.rule_id == "SLOT-003" and not rule.passed for rule in result.rule_results)

    def test_occupied_dock_blocks(self, db_session: Session) -> None:
        data = _build_complete_scenario(db_session)
        data["dock"].status = DockStatus.OCCUPIED
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        assert any(rule.rule_id == "DOCK-003" and not rule.passed for rule in result.rule_results)

    def test_reefer_requires_temperature_controlled_dock(self, db_session: Session) -> None:
        data = _build_complete_scenario(db_session)
        vehicle = data["shipment"].vehicle
        assert vehicle is not None
        vehicle.vehicle_type = "48ft_reefer"
        data["dock"].temperature_controlled = False
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        assert any(rule.rule_id == "DOCK-005" and not rule.passed for rule in result.rule_results)

    def test_operating_hours_rule(self, db_session: Session) -> None:
        data = _build_complete_scenario(db_session)
        db_session.add(
            FacilityRule(
                facility_id=data["facility"].id,
                rule_type="operating_hours",
                rule_value={"open": "08:00", "close": "17:00"},
                effective_start=data["now"] - timedelta(days=1),
                is_active=True,
            )
        )
        data["slot"].start_time = _utc(2026, 8, 13, 22, 0)
        data["slot"].end_time = _utc(2026, 8, 13, 23, 0)
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(
            data["shipment"].id,
            FeasibilityEvaluateRequest(evaluated_at=data["now"]),
        )
        assert any(rule.rule_id == "RULE-002" and not rule.passed for rule in result.rule_results)

    def test_eta_outside_slot_window(self, db_session: Session) -> None:
        data = _build_complete_scenario(db_session)
        from app.models import ETAUpdate
        from app.models.enums import ETASource

        db_session.add(
            ETAUpdate(
                shipment_id=data["shipment"].id,
                previous_eta=None,
                new_eta=data["now"] + timedelta(hours=5),
                update_timestamp=data["now"],
                source=ETASource.DRIVER,
            )
        )
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(
            data["shipment"].id,
            FeasibilityEvaluateRequest(evaluated_at=data["now"]),
        )
        assert result.outcome == FeasibilityOutcome.NOT_FEASIBLE
        assert any(rule.rule_id == "ETA-001" and not rule.passed for rule in result.rule_results)
