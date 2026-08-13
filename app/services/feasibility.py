"""Feasibility evaluation service — data retrieval and engine orchestration."""

from datetime import datetime, time, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.engines.feasibility.engine import FeasibilityEngine
from app.engines.feasibility.models import (
    AppointmentFacts,
    DockFacts,
    DriverExceptionFacts,
    EntityStatusFacts,
    FacilityFacts,
    FacilityRuleFacts,
    FeasibilityContext,
    FeasibilityEvaluation,
    ShipmentFacts,
    SlotFacts,
    VehicleFacts,
)
from app.engines.feasibility.rules import CAPACITY_CONSUMING_APPOINTMENT_STATUSES
from app.models.appointment import Appointment
from app.models.appointment_slot import AppointmentSlot
from app.models.carrier import Carrier
from app.models.dock import Dock
from app.models.driver import Driver
from app.models.enums import AppointmentStatus
from app.models.facility import Facility
from app.models.shipment import Shipment
from app.models.vehicle import Vehicle
from app.repositories.appointment import AppointmentRepository
from app.repositories.appointment_slot import AppointmentSlotRepository
from app.repositories.carrier import CarrierRepository
from app.repositories.dock import DockRepository
from app.repositories.driver import DriverRepository
from app.repositories.driver_exception import DriverExceptionRepository
from app.repositories.facility import FacilityRepository
from app.repositories.facility_rule import FacilityRuleRepository
from app.repositories.shipment import ShipmentRepository
from app.repositories.vehicle import VehicleRepository
from app.schemas.feasibility import FeasibilityEvaluateRequest, FeasibilityResponse, RuleResultResponse

_ACTIVE_APPOINTMENT_STATUSES = (
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.HELD,
)
_CAPACITY_STATUSES = tuple(
    AppointmentStatus(status) for status in CAPACITY_CONSUMING_APPOINTMENT_STATUSES
)


class FeasibilityService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._shipment_repo = ShipmentRepository(session)
        self._carrier_repo = CarrierRepository(session)
        self._driver_repo = DriverRepository(session)
        self._vehicle_repo = VehicleRepository(session)
        self._facility_repo = FacilityRepository(session)
        self._appointment_repo = AppointmentRepository(session)
        self._slot_repo = AppointmentSlotRepository(session)
        self._dock_repo = DockRepository(session)
        self._rule_repo = FacilityRuleRepository(session)
        self._exception_repo = DriverExceptionRepository(session)
        self._engine = FeasibilityEngine()

    def evaluate(
        self,
        shipment_id: UUID,
        request: FeasibilityEvaluateRequest | None = None,
    ) -> FeasibilityResponse:
        payload = request or FeasibilityEvaluateRequest()
        evaluated_at = payload.evaluated_at or datetime.now(timezone.utc)

        shipment = self._shipment_repo.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found")

        context = self._build_context(
            shipment=shipment,
            evaluated_at=evaluated_at,
            appointment_slot_id=payload.appointment_slot_id,
            dock_id=payload.dock_id,
        )
        evaluation = self._engine.evaluate(context)
        return self._to_response(evaluation)

    def _build_context(
        self,
        *,
        shipment: Shipment,
        evaluated_at: datetime,
        appointment_slot_id: UUID | None,
        dock_id: UUID | None,
    ) -> FeasibilityContext:
        carrier = self._carrier_repo.get_by_id(shipment.carrier_id)
        driver = (
            self._driver_repo.get_by_id(shipment.driver_id)
            if shipment.driver_id is not None
            else None
        )
        vehicle = (
            self._vehicle_repo.get_by_id(shipment.vehicle_id)
            if shipment.vehicle_id is not None
            else None
        )
        facility = (
            self._facility_repo.get_by_id(shipment.destination_facility_id)
            if shipment.destination_facility_id is not None
            else None
        )

        appointment = self._resolve_appointment(shipment.id, appointment_slot_id)
        slot = self._resolve_slot(shipment.id, appointment, appointment_slot_id)
        dock = self._resolve_dock(shipment.id, appointment, dock_id)

        latest_eta_update = self._shipment_repo.get_latest_eta(shipment.id)
        latest_eta = latest_eta_update.new_eta if latest_eta_update else None

        exceptions = self._exception_repo.list_for_shipment(shipment.id)
        facility_rules = (
            self._rule_repo.list_active_at(facility.id, evaluated_at)
            if facility is not None
            else []
        )

        daily_count = None
        if facility is not None and slot is not None:
            day_start, day_end = self._facility_day_bounds(slot.start_time, facility.timezone)
            daily_count = self._appointment_repo.count_by_facility_between(
                facility.id,
                day_start,
                day_end,
                _CAPACITY_STATUSES,
                exclude_shipment_id=shipment.id,
            )
            counts_toward_daily = (
                appointment is not None and appointment.status in _CAPACITY_STATUSES
            ) or appointment_slot_id is not None
            if counts_toward_daily:
                daily_count += 1

        shipment_on_slot = (
            appointment is not None
            and slot is not None
            and appointment.appointment_slot_id == slot.id
            and appointment.status in _CAPACITY_STATUSES
        )
        booked_count = 0
        if slot is not None:
            booked_count = self._appointment_repo.count_by_slot(slot.id, _CAPACITY_STATUSES)

        return FeasibilityContext(
            evaluated_at=evaluated_at,
            shipment=self._shipment_facts(shipment),
            carrier=self._carrier_facts(carrier) if carrier else None,
            driver=self._driver_facts(driver) if driver else None,
            vehicle=self._vehicle_facts(vehicle) if vehicle else None,
            facility=self._facility_facts(facility) if facility else None,
            appointment=self._appointment_facts(appointment) if appointment else None,
            slot=self._slot_facts(slot, booked_count, shipment_on_slot) if slot else None,
            dock=self._dock_facts(dock) if dock else None,
            latest_eta=latest_eta,
            active_exceptions=tuple(self._exception_facts(exc) for exc in exceptions),
            facility_rules=tuple(self._rule_facts(rule) for rule in facility_rules),
            daily_appointment_count=daily_count,
        )

    def _resolve_appointment(
        self,
        shipment_id: UUID,
        appointment_slot_id: UUID | None,
    ) -> Appointment | None:
        if appointment_slot_id is not None:
            active = self._appointment_repo.get_active_for_shipment(
                shipment_id, _ACTIVE_APPOINTMENT_STATUSES
            )
            if active is not None and active.appointment_slot_id == appointment_slot_id:
                return active
            return None
        return self._appointment_repo.get_active_for_shipment(
            shipment_id, _ACTIVE_APPOINTMENT_STATUSES
        )

    def _resolve_slot(
        self,
        shipment_id: UUID,
        appointment: Appointment | None,
        appointment_slot_id: UUID | None,
    ) -> AppointmentSlot | None:
        target_slot_id = appointment_slot_id
        if target_slot_id is None and appointment is not None:
            target_slot_id = appointment.appointment_slot_id
        if target_slot_id is None:
            return None
        slot = self._slot_repo.get_by_id(target_slot_id)
        if slot is None:
            raise NotFoundError(f"Appointment slot {target_slot_id} not found")
        return slot

    def _resolve_dock(
        self,
        shipment_id: UUID,
        appointment: Appointment | None,
        dock_id: UUID | None,
    ) -> Dock | None:
        target_dock_id = dock_id
        if target_dock_id is None and appointment is not None:
            target_dock_id = appointment.dock_id
        if target_dock_id is None:
            return None
        dock = self._dock_repo.get_by_id(target_dock_id)
        if dock is None:
            raise NotFoundError(f"Dock {target_dock_id} not found")
        return dock

    @staticmethod
    def _facility_day_bounds(
        reference: datetime,
        timezone_name: str,
    ) -> tuple[datetime, datetime]:
        local = reference.astimezone(ZoneInfo(timezone_name))
        day_start_local = datetime.combine(local.date(), time.min, tzinfo=ZoneInfo(timezone_name))
        day_end_local = datetime.combine(local.date(), time.max, tzinfo=ZoneInfo(timezone_name))
        return day_start_local.astimezone(timezone.utc), day_end_local.astimezone(timezone.utc)

    @staticmethod
    def _shipment_facts(shipment: Shipment) -> ShipmentFacts:
        return ShipmentFacts(
            shipment_id=shipment.id,
            shipment_number=shipment.shipment_number,
            is_active=shipment.is_active,
            status=shipment.status.value,
            destination_facility_id=shipment.destination_facility_id,
            carrier_id=shipment.carrier_id,
            driver_id=shipment.driver_id,
            vehicle_id=shipment.vehicle_id,
            weight_kg=shipment.weight_kg,
            volume_cbm=shipment.volume_cbm,
            pallet_count=shipment.pallet_count,
            scheduled_delivery_at=shipment.scheduled_delivery_at,
        )

    @staticmethod
    def _carrier_facts(carrier: Carrier) -> EntityStatusFacts:
        return EntityStatusFacts(
            entity_id=carrier.id,
            name=carrier.name,
            status=carrier.status.value,
        )

    @staticmethod
    def _driver_facts(driver: Driver) -> EntityStatusFacts:
        return EntityStatusFacts(
            entity_id=driver.id,
            name=driver.name,
            status=driver.status.value,
        )

    @staticmethod
    def _vehicle_facts(vehicle: Vehicle) -> VehicleFacts:
        return VehicleFacts(
            vehicle_id=vehicle.id,
            vehicle_type=vehicle.vehicle_type,
            status=vehicle.status.value,
            max_weight_kg=vehicle.max_weight_kg,
            max_volume_cbm=vehicle.max_volume_cbm,
        )

    @staticmethod
    def _facility_facts(facility: Facility) -> FacilityFacts:
        return FacilityFacts(
            facility_id=facility.id,
            code=facility.code,
            status=facility.status.value,
            timezone=facility.timezone,
        )

    @staticmethod
    def _appointment_facts(appointment: Appointment) -> AppointmentFacts:
        return AppointmentFacts(
            appointment_id=appointment.id,
            status=appointment.status.value,
            facility_id=appointment.facility_id,
            appointment_slot_id=appointment.appointment_slot_id,
            dock_id=appointment.dock_id,
        )

    @staticmethod
    def _slot_facts(
        slot: AppointmentSlot,
        booked_count: int,
        includes_current_shipment: bool,
    ) -> SlotFacts:
        return SlotFacts(
            slot_id=slot.id,
            facility_id=slot.facility_id,
            start_time=slot.start_time,
            end_time=slot.end_time,
            capacity=slot.capacity,
            status=slot.status.value,
            booked_count=booked_count,
            includes_current_shipment=includes_current_shipment,
        )

    @staticmethod
    def _dock_facts(dock: Dock) -> DockFacts:
        return DockFacts(
            dock_id=dock.id,
            facility_id=dock.facility_id,
            name=dock.name,
            status=dock.status.value,
            max_weight_kg=dock.max_weight_kg,
            temperature_controlled=dock.temperature_controlled,
        )

    @staticmethod
    def _rule_facts(rule) -> FacilityRuleFacts:
        return FacilityRuleFacts(
            rule_id=rule.id,
            rule_type=rule.rule_type,
            rule_value=rule.rule_value,
            effective_start=rule.effective_start,
            effective_end=rule.effective_end,
            is_active=rule.is_active,
        )

    @staticmethod
    def _exception_facts(exception) -> DriverExceptionFacts:
        return DriverExceptionFacts(
            exception_id=exception.id,
            exception_type=exception.exception_type.value,
            status=exception.status.value,
            description=exception.description,
        )

    @staticmethod
    def _to_response(evaluation: FeasibilityEvaluation) -> FeasibilityResponse:
        return FeasibilityResponse(
            outcome=evaluation.outcome,
            feasible=evaluation.feasible,
            evaluated_at=evaluation.evaluated_at,
            shipment_id=evaluation.shipment_id,
            rule_results=[
                RuleResultResponse(
                    rule_id=result.rule_id,
                    rule_name=result.rule_name,
                    category=result.category,
                    passed=result.passed,
                    severity=result.severity,
                    reason=result.reason,
                    evaluable=result.evaluable,
                    facts=result.facts,
                )
                for result in evaluation.rule_results
            ],
            blocking_reasons=list(evaluation.blocking_reasons),
            warnings=list(evaluation.warnings),
            operational_facts=evaluation.operational_facts,
        )
