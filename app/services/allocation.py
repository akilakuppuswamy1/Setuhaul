"""Deterministic, concurrency-safe resource allocation service (Step 6)."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError
from app.engines.feasibility.models import FeasibilityOutcome
from app.engines.feasibility.rules import CAPACITY_CONSUMING_APPOINTMENT_STATUSES
from app.models.appointment_slot import AppointmentSlot
from app.models.dock import Dock
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    DockStatus,
)
from app.models.shipment import Shipment
from app.repositories.appointment import AppointmentRepository
from app.repositories.appointment_slot import AppointmentSlotRepository
from app.repositories.dock import DockRepository
from app.repositories.shipment import ShipmentRepository
from app.schemas.allocation import AllocationRequest, AllocationResponse
from app.schemas.appointment import AppointmentResponse
from app.schemas.appointment_slot import AppointmentSlotResponse
from app.schemas.dock import DockResponse
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.services.feasibility import FeasibilityService
from app.services.helpers import safe_commit

_ACTIVE_ALLOCATION_STATUSES = (
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.HELD,
)
_CAPACITY_STATUSES = tuple(
    AppointmentStatus(status) for status in CAPACITY_CONSUMING_APPOINTMENT_STATUSES
)

# Documented lock acquisition order for deadlock prevention.
ALLOCATION_LOCK_ORDER: tuple[str, ...] = ("shipment", "slot", "dock")


class AllocationService:
    """Allocate appointment slots and docks atomically with concurrency protection.

    Lock ordering (deadlock prevention): shipment advisory lock, then slot row,
    then dock row. Availability is verified and allocation is written inside
    the same transaction.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._shipment_repo = ShipmentRepository(session)
        self._appointment_repo = AppointmentRepository(session)
        self._slot_repo = AppointmentSlotRepository(session)
        self._dock_repo = DockRepository(session)
        self._feasibility_service = FeasibilityService(session)

    def allocate(
        self,
        shipment_id: UUID,
        request: AllocationRequest | None = None,
    ) -> AllocationResponse:
        payload = request or AllocationRequest()
        evaluated_at = payload.evaluated_at or datetime.now(timezone.utc)

        shipment = self._shipment_repo.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found")

        if shipment.destination_facility_id is None:
            raise SetuHaulError("Shipment has no destination facility assigned")

        slot_candidates = self._resolve_slot_candidates(
            shipment, payload.appointment_slot_id
        )
        dock_candidates = self._resolve_dock_candidates(
            shipment, payload.dock_id, require_dock=payload.dock_id is not None
        )

        if not slot_candidates:
            raise ConflictError("No eligible appointment slots available for allocation")

        try:
            self._appointment_repo.acquire_shipment_advisory_lock(shipment_id)

            existing = self._appointment_repo.get_active_for_shipment(
                shipment_id, _ACTIVE_ALLOCATION_STATUSES
            )
            if existing is not None:
                raise ConflictError(
                    f"Shipment {shipment_id} already has an active allocation "
                    f"(appointment {existing.id}, status {existing.status.value})"
                )

            result = self._allocate_with_locks(
                shipment=shipment,
                slot_candidates=slot_candidates,
                dock_candidates=dock_candidates,
                evaluated_at=evaluated_at,
                notes=payload.notes,
                explicit_slot=payload.appointment_slot_id is not None,
                explicit_dock=payload.dock_id is not None,
            )
            safe_commit(self._session)
            return result
        except Exception:
            self._session.rollback()
            raise

    def _resolve_slot_candidates(
        self,
        shipment: Shipment,
        appointment_slot_id: UUID | None,
    ) -> list[UUID]:
        facility_id = shipment.destination_facility_id
        assert facility_id is not None

        if appointment_slot_id is not None:
            slot = self._slot_repo.get_by_id(appointment_slot_id)
            if slot is None:
                raise NotFoundError(f"Appointment slot {appointment_slot_id} not found")
            return [slot.id]

        open_slots = self._slot_repo.list_open_by_facility(facility_id)
        return [slot.id for slot in open_slots]

    def _resolve_dock_candidates(
        self,
        shipment: Shipment,
        dock_id: UUID | None,
        *,
        require_dock: bool,
    ) -> list[UUID | None]:
        facility_id = shipment.destination_facility_id
        assert facility_id is not None

        if dock_id is not None:
            dock = self._dock_repo.get_by_id(dock_id)
            if dock is None:
                raise NotFoundError(f"Dock {dock_id} not found")
            return [dock.id]

        available_docks = self._dock_repo.list_available_by_facility(facility_id)
        if available_docks:
            candidates: list[UUID | None] = [dock.id for dock in available_docks]
            if not require_dock:
                candidates.append(None)
            return candidates
        if require_dock:
            return []
        return [None]

    def _allocate_with_locks(
        self,
        *,
        shipment: Shipment,
        slot_candidates: list[UUID],
        dock_candidates: list[UUID | None],
        evaluated_at: datetime,
        notes: str | None,
        explicit_slot: bool,
        explicit_dock: bool,
    ) -> AllocationResponse:
        facility_id = shipment.destination_facility_id
        assert facility_id is not None

        last_infeasible_reason: str | None = None

        for slot_id in slot_candidates:
            slot = self._slot_repo.lock_by_id(slot_id)
            if slot is None:
                if explicit_slot:
                    raise NotFoundError(f"Appointment slot {slot_id} not found")
                continue

            if not self._slot_is_allocatable(slot):
                if explicit_slot:
                    raise ConflictError(
                        f"Appointment slot {slot_id} is not available (status: {slot.status.value})"
                    )
                continue

            booked = self._appointment_repo.count_by_slot(slot_id, _CAPACITY_STATUSES)
            if booked >= slot.capacity:
                if explicit_slot:
                    raise ConflictError(
                        f"Appointment slot {slot_id} capacity exhausted "
                        f"({booked}/{slot.capacity})"
                    )
                continue

            for dock_option in dock_candidates:
                dock: Dock | None = None
                if dock_option is not None:
                    dock = self._lock_dock_after_slot(slot_id, dock_option)
                    if dock is None:
                        if explicit_dock:
                            raise NotFoundError(f"Dock {dock_option} not found")
                        continue
                    if dock.status != DockStatus.AVAILABLE:
                        if explicit_dock:
                            raise ConflictError(
                                f"Dock {dock_option} is not available "
                                f"(status: {dock.status.value})"
                            )
                        continue

                booked = self._appointment_repo.count_by_slot(slot_id, _CAPACITY_STATUSES)
                if booked >= slot.capacity:
                    if explicit_slot:
                        raise ConflictError(
                            f"Appointment slot {slot_id} capacity exhausted "
                            f"({booked}/{slot.capacity})"
                        )
                    break

                feasibility = self._feasibility_service.evaluate(
                    shipment.id,
                    FeasibilityEvaluateRequest(
                        appointment_slot_id=slot_id,
                        dock_id=dock.id if dock is not None else None,
                        evaluated_at=evaluated_at,
                    ),
                )

                if feasibility.outcome == FeasibilityOutcome.NOT_EVALUABLE:
                    last_infeasible_reason = (
                        "Allocation context is not evaluable: "
                        + "; ".join(feasibility.blocking_reasons or ["missing data"])
                    )
                    if explicit_slot or explicit_dock:
                        raise SetuHaulError(last_infeasible_reason)
                    continue

                if not feasibility.feasible:
                    last_infeasible_reason = (
                        "Allocation is not feasible: "
                        + "; ".join(feasibility.blocking_reasons)
                    )
                    if explicit_slot or explicit_dock:
                        raise SetuHaulError(last_infeasible_reason)
                    continue

                appointment = self._appointment_repo.create(
                    shipment_id=shipment.id,
                    facility_id=facility_id,
                    appointment_slot_id=slot_id,
                    dock_id=dock.id if dock is not None else None,
                    status=AppointmentStatus.CONFIRMED,
                    notes=notes,
                )

                new_booked = booked + 1
                if new_booked >= slot.capacity:
                    slot.status = AppointmentSlotStatus.FULL

                if dock is not None:
                    dock.status = DockStatus.OCCUPIED

                return AllocationResponse(
                    success=True,
                    shipment_id=shipment.id,
                    appointment=AppointmentResponse.model_validate(appointment),
                    appointment_slot=AppointmentSlotResponse.model_validate(slot),
                    dock=DockResponse.model_validate(dock) if dock is not None else None,
                    feasibility=feasibility,
                    reason="Allocation completed successfully",
                    conflict=False,
                    allocated_at=evaluated_at,
                )

        if last_infeasible_reason is not None:
            raise SetuHaulError(last_infeasible_reason)

        raise ConflictError("No available slot and dock combination could be allocated")

    @staticmethod
    def _slot_is_allocatable(slot: AppointmentSlot) -> bool:
        return slot.status == AppointmentSlotStatus.OPEN and slot.capacity > 0

    def _lock_dock_after_slot(self, slot_id: UUID, dock_id: UUID) -> Dock | None:
        """Lock dock after the slot row is already locked (consistent lock ordering)."""
        return self._dock_repo.lock_by_id(dock_id)
