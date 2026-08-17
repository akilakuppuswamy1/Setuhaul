"""Deterministic, concurrency-safe resource allocation service (Step 6)."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError
from app.engines.feasibility.models import FeasibilityOutcome
from app.engines.feasibility.rules import CAPACITY_CONSUMING_APPOINTMENT_STATUSES
from app.models.appointment import Appointment
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
        *,
        commit: bool = True,
        replace_active: bool = False,
        ignore_delay_exceptions: bool | None = None,
    ) -> AllocationResponse:
        """Allocate a slot/dock. Delay-class exceptions (delay, traffic, repair,
        breakdown) are ignored when ``ignore_delay_exceptions`` is true, or by
        default when replacing an active appointment (reschedule). Direct
        allocate keeps them blocking. Other/safety exceptions still block.
        """
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
            if existing is not None and self._matches_requested_allocation(
                existing, payload
            ):
                if replace_active:
                    result = self._response_for_existing(
                        shipment, existing, evaluated_at
                    )
                    if commit:
                        safe_commit(self._session)
                    else:
                        self._session.flush()
                    return result
                raise ConflictError(
                    f"Shipment {shipment_id} already has an active allocation "
                    f"(appointment {existing.id}, status {existing.status.value})"
                )
            if existing is not None and not replace_active:
                raise ConflictError(
                    f"Shipment {shipment_id} already has an active allocation "
                    f"(appointment {existing.id}, status {existing.status.value})"
                )

            to_replace = existing if replace_active else None
            if ignore_delay_exceptions is None:
                ignore_delay_exceptions = to_replace is not None
            if to_replace is not None:
                self._lock_involved_resources(
                    existing=to_replace,
                    slot_ids=slot_candidates,
                    dock_ids=dock_candidates,
                )
                self._supersede_active(to_replace)
                dock_candidates = self._resolve_dock_candidates(
                    shipment, payload.dock_id, require_dock=payload.dock_id is not None
                )
                extra_docks = [
                    dock_id for dock_id in dock_candidates if dock_id is not None
                ]
                for dock_id in sorted(extra_docks, key=lambda value: str(value)):
                    self._dock_repo.lock_by_id(dock_id)

            result = self._allocate_with_locks(
                shipment=shipment,
                slot_candidates=slot_candidates,
                dock_candidates=dock_candidates,
                evaluated_at=evaluated_at,
                notes=payload.notes,
                explicit_slot=payload.appointment_slot_id is not None,
                explicit_dock=payload.dock_id is not None,
                ignore_delay_exceptions=ignore_delay_exceptions,
            )
            if to_replace is not None:
                self._record_superseded_by(to_replace, result.appointment.id)
            if commit:
                safe_commit(self._session)
            else:
                self._session.flush()
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
        ignore_delay_exceptions: bool = False,
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
                        ignore_delay_exceptions=ignore_delay_exceptions,
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

    @staticmethod
    def _matches_requested_allocation(
        existing: Appointment,
        payload: AllocationRequest,
    ) -> bool:
        if payload.appointment_slot_id is not None:
            if existing.appointment_slot_id != payload.appointment_slot_id:
                return False
        if payload.dock_id is not None and existing.dock_id != payload.dock_id:
            return False
        return True

    def _lock_involved_resources(
        self,
        *,
        existing: Appointment | None,
        slot_ids: list[UUID],
        dock_ids: list[UUID | None],
    ) -> None:
        slots: set[UUID] = set(slot_ids)
        docks: set[UUID] = {dock_id for dock_id in dock_ids if dock_id is not None}
        if existing is not None:
            if existing.appointment_slot_id is not None:
                slots.add(existing.appointment_slot_id)
            if existing.dock_id is not None:
                docks.add(existing.dock_id)
        for slot_id in sorted(slots, key=lambda value: str(value)):
            self._slot_repo.lock_by_id(slot_id)
        for dock_id in sorted(docks, key=lambda value: str(value)):
            self._dock_repo.lock_by_id(dock_id)

    def _supersede_active(self, existing: Appointment) -> None:
        """Cancel the active appointment and release its slot/dock capacity in-session."""
        old_slot_id = existing.appointment_slot_id
        old_dock_id = existing.dock_id
        existing.status = AppointmentStatus.CANCELLED
        self._session.flush()

        if old_slot_id is not None:
            slot = self._slot_repo.get_by_id(old_slot_id)
            if slot is not None:
                booked = self._appointment_repo.count_by_slot(old_slot_id, _CAPACITY_STATUSES)
                if booked < slot.capacity and slot.status == AppointmentSlotStatus.FULL:
                    slot.status = AppointmentSlotStatus.OPEN

        if old_dock_id is not None:
            remaining = self._appointment_repo.count_by_dock(old_dock_id, _CAPACITY_STATUSES)
            if remaining == 0:
                dock = self._dock_repo.get_by_id(old_dock_id)
                if dock is not None and dock.status == DockStatus.OCCUPIED:
                    dock.status = DockStatus.AVAILABLE
        self._session.flush()

    @staticmethod
    def _record_superseded_by(existing: Appointment, new_appointment_id: UUID) -> None:
        marker = f"superseded_by={new_appointment_id}"
        notes = existing.notes or ""
        if marker not in notes:
            existing.notes = f"{notes}\n{marker}" if notes else marker

    def _response_for_existing(
        self,
        shipment: Shipment,
        existing: Appointment,
        evaluated_at: datetime,
    ) -> AllocationResponse:
        slot = (
            self._slot_repo.get_by_id(existing.appointment_slot_id)
            if existing.appointment_slot_id is not None
            else None
        )
        dock = self._dock_repo.get_by_id(existing.dock_id) if existing.dock_id is not None else None
        feasibility = self._feasibility_service.evaluate(
            shipment.id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=existing.appointment_slot_id,
                dock_id=existing.dock_id,
                evaluated_at=evaluated_at,
            ),
        )
        return AllocationResponse(
            success=True,
            shipment_id=shipment.id,
            appointment=AppointmentResponse.model_validate(existing),
            appointment_slot=(
                AppointmentSlotResponse.model_validate(slot) if slot is not None else None
            ),
            dock=DockResponse.model_validate(dock) if dock is not None else None,
            feasibility=feasibility,
            reason="Shipment already has a matching active allocation",
            conflict=False,
            allocated_at=evaluated_at,
        )
