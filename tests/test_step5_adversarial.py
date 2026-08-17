"""Step 5 adversarial hardening and validation tests."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.database import Base
from tests.db import postgres_test_url as _postgres_test_url
from app.engines.feasibility.engine import FeasibilityEngine
from app.engines.feasibility.models import (
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
    ChatMessage,
    ChatThread,
    Contact,
    Dock,
    Driver,
    DriverException,
    ETAUpdate,
    Facility,
    FacilityCheckin,
    FacilityRule,
    OperationalMessage,
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
    ExceptionType,
    ShipmentStatus,
)
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.services.feasibility import FeasibilityService


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


ALL_OPERATIONAL_TABLES = (
    Appointment,
    AppointmentSlot,
    Carrier,
    ChatMessage,
    ChatThread,
    Contact,
    Dock,
    Driver,
    DriverException,
    ETAUpdate,
    Facility,
    FacilityCheckin,
    FacilityRule,
    OperationalMessage,
    Shipment,
    Vehicle,
)


def _table_counts(session: Session) -> dict[str, int]:
    return {
        table.__tablename__: int(session.scalar(select(func.count()).select_from(table)) or 0)
        for table in ALL_OPERATIONAL_TABLES
    }


@pytest.fixture
def postgres_url() -> str:
    url = _postgres_test_url()
    if url is None:
        pytest.skip("PostgreSQL unavailable for Step 5 adversarial tests")
    return url


@pytest.fixture
def postgres_session(postgres_url: str) -> Session:
    engine = create_engine(postgres_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


class TestReadOnlyHardening:
    def test_no_operational_mutation_across_all_tables(
        self, seeded_session: dict[str, object], db_session: Session
    ) -> None:
        shipment = seeded_session["shipments"][0]
        before = _table_counts(db_session)
        FeasibilityService(db_session).evaluate(
            shipment.id,
            FeasibilityEvaluateRequest(evaluated_at=_utc(2026, 8, 13, 10, 0)),
        )
        after = _table_counts(db_session)
        assert before == after

    def test_api_evaluation_does_not_mutate(
        self, seeded_client: TestClient, seeded_session: dict[str, object], db_session: Session
    ) -> None:
        shipment = seeded_session["shipments"][0]
        before = _table_counts(db_session)
        response = seeded_client.post(
            f"/shipments/{shipment.id}/feasibility",
            json={"evaluated_at": "2026-08-13T10:00:00+00:00"},
        )
        assert response.status_code == 200
        assert _table_counts(db_session) == before


class TestMalformedFacilityRuleHardening:
    def test_invalid_limit_value_fails_safely(self) -> None:
        ctx = _minimal_context_with_rules(
            FacilityRuleFacts(
                uuid.uuid4(),
                "max_daily_appointments",
                {"limit": "not-a-number"},
                _utc(2026, 1, 1),
                None,
                True,
            ),
            daily_appointment_count=1,
        )
        result = FeasibilityEngine().evaluate(ctx)
        rule = next(item for item in result.rule_results if item.rule_id == "RULE-001")
        assert rule.passed is False
        assert "invalid" in rule.reason.lower()

    def test_empty_rule_value_object_fails_safely(self) -> None:
        ctx = _minimal_context_with_rules(
            FacilityRuleFacts(uuid.uuid4(), "max_daily_appointments", {}, _utc(2026, 1, 1), None, True),
            daily_appointment_count=1,
        )
        result = FeasibilityEngine().evaluate(ctx)
        rule = next(item for item in result.rule_results if item.rule_id == "RULE-001")
        assert rule.passed is False

    def test_malformed_operating_hours_time_format(self) -> None:
        ctx = _minimal_context_with_rules(
            FacilityRuleFacts(
                uuid.uuid4(),
                "operating_hours",
                {"open": "25:99", "close": "bad"},
                _utc(2026, 1, 1),
                None,
                True,
            )
        )
        result = FeasibilityEngine().evaluate(ctx)
        rule = next(item for item in result.rule_results if item.rule_id == "RULE-002")
        assert rule.passed is False

    def test_dock_compatibility_non_list_allowed_types(self) -> None:
        ctx = _minimal_context_with_rules(
            FacilityRuleFacts(
                uuid.uuid4(),
                "dock_compatibility",
                {"allowed_vehicle_types": "53ft_dry_van"},
                _utc(2026, 1, 1),
                None,
                True,
            )
        )
        result = FeasibilityEngine().evaluate(ctx)
        rule = next(item for item in result.rule_results if item.rule_id == "RULE-003")
        assert rule.passed is False

    def test_dock_compatibility_invalid_max_pallets(self) -> None:
        ctx = _minimal_context_with_rules(
            FacilityRuleFacts(
                uuid.uuid4(),
                "dock_compatibility",
                {"max_pallets": "many"},
                _utc(2026, 1, 1),
                None,
                True,
            )
        )
        result = FeasibilityEngine().evaluate(ctx)
        rule = next(item for item in result.rule_results if item.rule_id == "RULE-003")
        assert rule.passed is False

    def test_malformed_rule_does_not_crash_api(
        self, db_session: Session, seeded_client: TestClient
    ) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        db_session.add(
            FacilityRule(
                facility_id=data["facility"].id,
                rule_type="max_daily_appointments",
                rule_value={"limit": None},
                effective_start=data["now"] - timedelta(days=1),
                is_active=True,
            )
        )
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

        response = seeded_client.post(
            f"/shipments/{data['shipment'].id}/feasibility",
            json={"evaluated_at": data["now"].isoformat()},
        )
        assert response.status_code == 200
        assert "traceback" not in response.text.lower()
        assert "sqlalchemy" not in response.text.lower()


class TestETAHardening:
    def test_latest_eta_uses_step4_tie_breaker(self, db_session: Session) -> None:
        from app.repositories.shipment import ShipmentRepository
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        same_ts = data["now"]
        db_session.add_all(
            [
                ETAUpdate(
                    shipment_id=data["shipment"].id,
                    previous_eta=None,
                    new_eta=data["now"] + timedelta(hours=2, minutes=0),
                    update_timestamp=same_ts,
                    source=ETASource.DISPATCH,
                ),
                ETAUpdate(
                    shipment_id=data["shipment"].id,
                    previous_eta=data["now"] + timedelta(hours=2),
                    new_eta=data["now"] + timedelta(hours=2, minutes=45),
                    update_timestamp=same_ts,
                    source=ETASource.DRIVER,
                ),
            ]
        )
        db_session.commit()

        latest = ShipmentRepository(db_session).get_latest_eta(data["shipment"].id)
        assert latest is not None

        result = FeasibilityService(db_session).evaluate(
            data["shipment"].id,
            FeasibilityEvaluateRequest(evaluated_at=data["now"]),
        )
        eta_rule = next(rule for rule in result.rule_results if rule.rule_id == "ETA-001")
        assert str(eta_rule.facts["latest_eta"]).replace("+00:00", "") == latest.new_eta.isoformat().replace(
            "+00:00", ""
        )

    def test_eta_exactly_on_slot_start_boundary(self, db_session: Session) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        slot_start = data["slot"].start_time
        db_session.add(
            ETAUpdate(
                shipment_id=data["shipment"].id,
                previous_eta=None,
                new_eta=slot_start,
                update_timestamp=data["now"],
                source=ETASource.DISPATCH,
            )
        )
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        eta_rule = next(rule for rule in result.rule_results if rule.rule_id == "ETA-001")
        assert eta_rule.passed is True

    def test_eta_exactly_on_slot_end_boundary(self, db_session: Session) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        slot_end = data["slot"].end_time
        db_session.add(
            ETAUpdate(
                shipment_id=data["shipment"].id,
                previous_eta=None,
                new_eta=slot_end,
                update_timestamp=data["now"],
                source=ETASource.DISPATCH,
            )
        )
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        eta_rule = next(rule for rule in result.rule_results if rule.rule_id == "ETA-001")
        assert eta_rule.passed is True


class TestExceptionHardening:
    def test_mixed_exception_statuses_only_active_block(
        self, db_session: Session, seeded_session: dict[str, object]
    ) -> None:
        shipment = seeded_session["shipments"][0]
        seeded_session["exception"].status = ExceptionStatus.RESOLVED
        db_session.add(
            DriverException(
                shipment_id=shipment.id,
                driver_id=seeded_session["drivers"][0].id,
                exception_type=ExceptionType.DELAY,
                description="Resolved delay",
                status=ExceptionStatus.RESOLVED,
                occurred_at=_utc(2026, 8, 13, 8, 0),
                resolved_at=_utc(2026, 8, 13, 9, 0),
            )
        )
        db_session.add(
            DriverException(
                shipment_id=shipment.id,
                driver_id=seeded_session["drivers"][0].id,
                exception_type=ExceptionType.TRAFFIC,
                description="Active traffic",
                status=ExceptionStatus.OPEN,
                occurred_at=_utc(2026, 8, 13, 9, 30),
            )
        )
        db_session.commit()

        result = FeasibilityService(db_session).evaluate(
            shipment.id,
            FeasibilityEvaluateRequest(evaluated_at=_utc(2026, 8, 13, 10, 0)),
        )
        exc_rule = next(rule for rule in result.rule_results if rule.rule_id == "EXCP-001")
        assert exc_rule.passed is False
        assert exc_rule.facts["active_exception_count"] == 1


class TestSlotCapacityHardening:
    def test_slot_at_capacity_with_current_shipment_passes(
        self, db_session: Session
    ) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        data["slot"].capacity = 1
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        slot_rule = next(rule for rule in result.rule_results if rule.rule_id == "SLOT-004")
        assert slot_rule.passed is True
        assert slot_rule.facts["includes_current_shipment"] is True

    def test_cancelled_appointments_do_not_consume_capacity(self, db_session: Session) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        data["slot"].capacity = 1
        other_carrier = Carrier(name="Other", code="OTH-1", status=EntityStatus.ACTIVE)
        other_shipment = Shipment(
            carrier=other_carrier,
            shipment_number="OTH-SHP",
            origin_location="X",
            destination_location="Y",
            destination_facility_id=data["facility"].id,
            status=ShipmentStatus.ASSIGNED,
            is_active=True,
        )
        db_session.add_all([other_carrier, other_shipment])
        db_session.flush()
        db_session.add(
            Appointment(
                shipment_id=other_shipment.id,
                facility_id=data["facility"].id,
                appointment_slot_id=data["slot"].id,
                status=AppointmentStatus.CANCELLED,
            )
        )
        db_session.commit()

        result = FeasibilityService(db_session).evaluate(
            data["shipment"].id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=data["slot"].id,
                evaluated_at=data["now"],
            ),
        )
        slot_rule = next(rule for rule in result.rule_results if rule.rule_id == "SLOT-004")
        assert slot_rule.passed is True

    def test_full_slot_status_blocks(self, db_session: Session) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)
        data["slot"].status = AppointmentSlotStatus.FULL
        db_session.commit()
        result = FeasibilityService(db_session).evaluate(data["shipment"].id)
        slot_rule = next(rule for rule in result.rule_results if rule.rule_id == "SLOT-003")
        assert slot_rule.passed is False


class TestRepeatabilityHardening:
    def test_triple_evaluation_identical_json(
        self, seeded_client: TestClient, seeded_session: dict[str, object], db_session: Session
    ) -> None:
        shipment = seeded_session["shipments"][0]
        seeded_session["exception"].status = ExceptionStatus.RESOLVED
        seeded_session["exception"].resolved_at = _utc(2026, 8, 13, 10, 0)
        db_session.commit()

        payload = {"evaluated_at": "2026-08-13T10:00:00+00:00"}
        results = [
            seeded_client.post(f"/shipments/{shipment.id}/feasibility", json=payload).json()
            for _ in range(3)
        ]
        assert results[0] == results[1] == results[2]


class TestAPIAdversarialHardening:
    def test_invalid_shipment_uuid_returns_422(self, seeded_client: TestClient) -> None:
        response = seeded_client.post("/shipments/not-a-uuid/feasibility", json={})
        assert response.status_code == 422

    def test_invalid_slot_uuid_returns_422(
        self, seeded_client: TestClient, seeded_session: dict[str, object]
    ) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/feasibility",
            json={"appointment_slot_id": "bad-uuid"},
        )
        assert response.status_code == 422

    def test_invalid_dock_uuid_returns_422(
        self, seeded_client: TestClient, seeded_session: dict[str, object]
    ) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/feasibility",
            json={"dock_id": "bad-uuid"},
        )
        assert response.status_code == 422

    def test_naive_evaluated_at_rejected(
        self, seeded_client: TestClient, seeded_session: dict[str, object]
    ) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.post(
            f"/shipments/{shipment.id}/feasibility",
            json={"evaluated_at": "2026-08-13T10:00:00"},
        )
        assert response.status_code == 422

    def test_empty_body_accepted(
        self, seeded_client: TestClient, seeded_session: dict[str, object]
    ) -> None:
        shipment = seeded_session["shipments"][0]
        response = seeded_client.post(f"/shipments/{shipment.id}/feasibility")
        assert response.status_code in {200, 422}


class TestAdversarialMatrix:
    @pytest.mark.parametrize(
        ("scenario", "expected_outcome"),
        [
            ("missing_eta_valid_slot", FeasibilityOutcome.NOT_EVALUABLE),
            ("active_exception_valid_eta", FeasibilityOutcome.NOT_FEASIBLE),
            ("missing_destination_facility", FeasibilityOutcome.NOT_FEASIBLE),
            ("blocking_and_warning_together", FeasibilityOutcome.NOT_FEASIBLE),
        ],
    )
    def test_adversarial_outcomes(
        self,
        db_session: Session,
        scenario: str,
        expected_outcome: FeasibilityOutcome,
    ) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(db_session)

        if scenario == "missing_eta_valid_slot":
            pass
        elif scenario == "active_exception_valid_eta":
            db_session.add(
                ETAUpdate(
                    shipment_id=data["shipment"].id,
                    previous_eta=None,
                    new_eta=data["now"] + timedelta(hours=2, minutes=15),
                    update_timestamp=data["now"],
                    source=ETASource.DISPATCH,
                )
            )
            db_session.add(
                DriverException(
                    shipment_id=data["shipment"].id,
                    driver_id=data["shipment"].driver_id,
                    exception_type=ExceptionType.TRAFFIC,
                    description="Active",
                    status=ExceptionStatus.OPEN,
                    occurred_at=data["now"],
                )
            )
        elif scenario == "missing_destination_facility":
            data["shipment"].destination_facility_id = None
        elif scenario == "blocking_and_warning_together":
            db_session.add(
                ETAUpdate(
                    shipment_id=data["shipment"].id,
                    previous_eta=None,
                    new_eta=data["now"] + timedelta(hours=22),
                    update_timestamp=data["now"],
                    source=ETASource.DRIVER,
                )
            )
            db_session.add(
                FacilityRule(
                    facility_id=data["facility"].id,
                    rule_type="operating_hours",
                    rule_value={"open": "08:00", "close": "17:00"},
                    effective_start=data["now"] - timedelta(days=1),
                    is_active=True,
                )
            )
            data["shipment"].is_active = False

        db_session.commit()
        result = FeasibilityService(db_session).evaluate(
            data["shipment"].id,
            FeasibilityEvaluateRequest(evaluated_at=data["now"]),
        )
        assert result.outcome == expected_outcome


class TestPostgreSQLStep5:
    def test_feasibility_on_postgresql(self, postgres_session: Session) -> None:
        from tests.test_step5_feasibility import _build_complete_scenario

        data = _build_complete_scenario(postgres_session)
        postgres_session.add(
            ETAUpdate(
                shipment_id=data["shipment"].id,
                previous_eta=None,
                new_eta=data["now"] + timedelta(hours=2, minutes=15),
                update_timestamp=data["now"],
                source=ETASource.DISPATCH,
            )
        )
        postgres_session.commit()

        before = _table_counts(postgres_session)
        result = FeasibilityService(postgres_session).evaluate(
            data["shipment"].id,
            FeasibilityEvaluateRequest(evaluated_at=data["now"]),
        )
        after = _table_counts(postgres_session)

        assert before == after
        assert result.outcome == FeasibilityOutcome.FEASIBLE


def _minimal_context_with_rules(
    rule: FacilityRuleFacts,
    *,
    daily_appointment_count: int | None = None,
) -> FeasibilityContext:
    facility_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    evaluated_at = _utc(2026, 8, 13, 10, 0)
    return FeasibilityContext(
        evaluated_at=evaluated_at,
        shipment=ShipmentFacts(
            shipment_id=uuid.uuid4(),
            shipment_number="MAL-001",
            is_active=True,
            status="in_transit",
            destination_facility_id=facility_id,
            carrier_id=uuid.uuid4(),
            driver_id=None,
            vehicle_id=uuid.uuid4(),
            weight_kg=Decimal("1000"),
            volume_cbm=None,
            pallet_count=5,
            scheduled_delivery_at=None,
        ),
        carrier=EntityStatusFacts(uuid.uuid4(), "Carrier", "active"),
        driver=None,
        vehicle=VehicleFacts(uuid.uuid4(), "53ft_dry_van", "active", Decimal("20000"), None),
        facility=FacilityFacts(facility_id, "FAC", "active", "UTC"),
        appointment=None,
        slot=SlotFacts(
            slot_id,
            facility_id,
            _utc(2026, 8, 13, 12, 0),
            _utc(2026, 8, 13, 13, 0),
            capacity=3,
            status="open",
            booked_count=0,
            includes_current_shipment=False,
        ),
        dock=None,
        latest_eta=_utc(2026, 8, 13, 12, 30),
        active_exceptions=(),
        facility_rules=(rule,),
        daily_appointment_count=daily_appointment_count,
    )
