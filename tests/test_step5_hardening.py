"""Step 5 hardening regression tests for the feasibility engine."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engines.feasibility.engine import FeasibilityEngine
from app.engines.feasibility.models import FeasibilityOutcome
from app.models import (
    Appointment,
    AppointmentSlot,
    Carrier,
    Dock,
    Driver,
    ETAUpdate,
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
    ETASource,
    ExceptionStatus,
    ShipmentStatus,
)
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.services.feasibility import FeasibilityService


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class TestDeterminismHardening:
    def test_rule_result_order_is_stable(self, db_session: Session) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        db_session.add(
            ETAUpdate(
                shipment_id=data["shipment"].id,
                previous_eta=None,
                new_eta=data["now"] + timedelta(hours=2, minutes=10),
                update_timestamp=data["now"],
                source=ETASource.DISPATCH,
            )
        )
        db_session.commit()

        service = FeasibilityService(db_session)
        evaluated_at = data["now"]
        first = service.evaluate(
            data["shipment"].id,
            FeasibilityEvaluateRequest(evaluated_at=evaluated_at),
        )
        second = service.evaluate(
            data["shipment"].id,
            FeasibilityEvaluateRequest(evaluated_at=evaluated_at),
        )
        assert [rule.rule_id for rule in first.rule_results] == [
            rule.rule_id for rule in second.rule_results
        ]
        assert first.blocking_reasons == second.blocking_reasons

    def test_blocking_reason_order_matches_rule_order(self, db_session: Session) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        data["shipment"].is_active = False
        data["slot"].status = AppointmentSlotStatus.CLOSED
        db_session.commit()

        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        failed_rules = [rule for rule in result.rule_results if not rule.passed and rule.evaluable]
        blocking_ids = [rule.rule_id for rule in failed_rules if rule.severity.value == "blocking"]
        assert blocking_ids.index("SHIP-001") < blocking_ids.index("SLOT-003")


class TestMissingDataHardening:
    def test_shipment_without_eta_is_not_evaluable_when_slot_present(
        self, db_session: Session
    ) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        assert result.outcome == FeasibilityOutcome.NOT_EVALUABLE
        eta_rule = next(rule for rule in result.rule_results if rule.rule_id == "ETA-001")
        assert eta_rule.evaluable is False

    def test_missing_vehicle_weight_skips_capacity_check(self, db_session: Session) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        data["shipment"].weight_kg = None
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        dock_rule = next(rule for rule in result.rule_results if rule.rule_id == "DOCK-004")
        assert dock_rule.evaluable is False
        assert dock_rule.passed is True


class TestTimezoneHardening:
    def test_operating_hours_use_facility_timezone(self, db_session: Session) -> None:
        carrier = Carrier(name="TZ Carrier", code="TZ-01", status=EntityStatus.ACTIVE)
        facility = Facility(
            name="Chicago DC",
            code="CHI-01",
            address="Chicago",
            timezone="America/Chicago",
            status=EntityStatus.ACTIVE,
        )
        slot = AppointmentSlot(
            facility=facility,
            start_time=_utc(2026, 8, 13, 20, 0),
            end_time=_utc(2026, 8, 13, 21, 0),
            capacity=2,
            status=AppointmentSlotStatus.OPEN,
        )
        shipment = Shipment(
            carrier=carrier,
            shipment_number="TZ-SHP-1",
            origin_location="A",
            destination_location="Chicago DC",
            destination_facility_id=facility.id,
            status=ShipmentStatus.ASSIGNED,
            is_active=True,
        )
        db_session.add_all([carrier, facility, slot, shipment])
        db_session.flush()
        shipment.destination_facility_id = facility.id
        db_session.add(
            Appointment(
                shipment_id=shipment.id,
                facility_id=facility.id,
                appointment_slot_id=slot.id,
                status=AppointmentStatus.CONFIRMED,
            )
        )
        db_session.add(
            FacilityRule(
                facility_id=facility.id,
                rule_type="operating_hours",
                rule_value={"open": "08:00", "close": "17:00"},
                effective_start=_utc(2026, 1, 1),
                is_active=True,
            )
        )
        db_session.add(
            ETAUpdate(
                shipment_id=shipment.id,
                previous_eta=None,
                new_eta=_utc(2026, 8, 13, 20, 30),
                update_timestamp=_utc(2026, 8, 13, 10, 0),
                source=ETASource.DRIVER,
            )
        )
        db_session.commit()

        result = FeasibilityService(db_session).evaluate(
            shipment.id,
            FeasibilityEvaluateRequest(evaluated_at=_utc(2026, 8, 13, 10, 0)),
        )
        rule = next(item for item in result.rule_results if item.rule_id == "RULE-002")
        assert rule.passed is True


class TestContradictoryRulesHardening:
    def test_multiple_facility_rules_all_evaluated(self, db_session: Session) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        db_session.add_all(
            [
                FacilityRule(
                    facility_id=data["facility"].id,
                    rule_type="max_daily_appointments",
                    rule_value={"limit": 1},
                    effective_start=data["now"] - timedelta(days=1),
                    is_active=True,
                ),
                FacilityRule(
                    facility_id=data["facility"].id,
                    rule_type="dock_compatibility",
                    rule_value={"allowed_vehicle_types": ["53ft_dry_van"], "max_pallets": 50},
                    effective_start=data["now"] - timedelta(days=1),
                    is_active=True,
                ),
            ]
        )
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        rule_ids = [rule.rule_id for rule in result.rule_results]
        assert rule_ids.count("RULE-001") >= 1
        assert rule_ids.count("RULE-003") >= 1


class TestSessionSafetyHardening:
    def test_evaluation_after_not_found_leaves_session_usable(self, db_session: Session) -> None:
        service = FeasibilityService(db_session)
        with pytest.raises(Exception):
            service.evaluate(uuid.uuid4())
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        result = service.evaluate(data["shipment"].id)
        assert result.shipment_id == data["shipment"].id


class TestAPIHardening:
    def test_duplicate_api_calls_return_identical_outcomes(
        self, seeded_client: TestClient, seeded_session: dict[str, object], db_session: Session
    ) -> None:
        shipment = seeded_session["shipments"][0]
        exception = seeded_session["exception"]
        exception.status = ExceptionStatus.RESOLVED
        exception.resolved_at = _utc(2026, 8, 13, 10, 0)
        db_session.commit()

        payload = {"evaluated_at": "2026-08-13T10:00:00+00:00"}
        first = seeded_client.post(f"/shipments/{shipment.id}/feasibility", json=payload)
        second = seeded_client.post(f"/shipments/{shipment.id}/feasibility", json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["outcome"] == second.json()["outcome"]
        assert first.json()["feasible"] == second.json()["feasible"]

    def test_engine_isolation_from_database(self) -> None:
        """Engine module must not import SQLAlchemy session or repository code."""
        import inspect

        import app.engines.feasibility.engine as engine_module
        import app.engines.feasibility.evaluator as evaluator_module

        for module in (engine_module, evaluator_module):
            source = inspect.getsource(module)
            assert "sqlalchemy" not in source.lower()
            assert "repository" not in source.lower()
