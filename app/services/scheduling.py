"""Read-only facility scheduling service. Ranking is delegated to SchedulingEngine."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, SetuHaulError
from app.engines.feasibility.rules import (
    ACTIVE_EXCEPTION_STATUSES,
    CAPACITY_CONSUMING_APPOINTMENT_STATUSES,
    TERMINAL_SHIPMENT_STATUSES,
)
from app.engines.scheduling.engine import SchedulingEngine
from app.engines.scheduling.models import (
    DockSnapshot,
    FeasibleOption,
    SchedulingContext,
    ShipmentSnapshot,
    SlotSnapshot,
)
from app.models.enums import (
    AppointmentSlotStatus,
    AppointmentStatus,
    CheckinType,
    DockStatus,
    ShipmentStatus,
)
from app.repositories.appointment import AppointmentRepository
from app.repositories.appointment_slot import AppointmentSlotRepository
from app.repositories.dock import DockRepository
from app.repositories.driver_exception import DriverExceptionRepository
from app.repositories.facility import FacilityRepository
from app.repositories.facility_checkin import FacilityCheckinRepository
from app.repositories.shipment import ShipmentRepository
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.schemas.scheduling import (
    CandidateShipmentResponse,
    ScheduleAssignmentResponse,
    ScheduleEvaluateRequest,
    ScheduleEvaluateResponse,
    UnassignedShipmentResponse,
)
from app.services.feasibility import FeasibilityService

_ELIGIBLE_STATUSES = frozenset(
    {
        ShipmentStatus.PENDING,
        ShipmentStatus.ASSIGNED,
        ShipmentStatus.IN_TRANSIT,
        ShipmentStatus.AT_FACILITY,
    }
)
_PROTECTED_STATUSES = (
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.HELD,
)
_CAPACITY_STATUSES = tuple(
    AppointmentStatus(status) for status in CAPACITY_CONSUMING_APPOINTMENT_STATUSES
)
_ARRIVAL_CHECKINS = frozenset(
    {CheckinType.GATE_IN, CheckinType.YARD_ARRIVAL, CheckinType.DOCK_ARRIVAL}
)
MAX_SHIPMENTS = 50
MAX_SLOTS = 100


class SchedulingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._facilities = FacilityRepository(session)
        self._shipments = ShipmentRepository(session)
        self._slots = AppointmentSlotRepository(session)
        self._docks = DockRepository(session)
        self._appointments = AppointmentRepository(session)
        self._exceptions = DriverExceptionRepository(session)
        self._checkins = FacilityCheckinRepository(session)
        self._feasibility = FeasibilityService(session)
        self._engine = SchedulingEngine()

    def evaluate(
        self,
        facility_id: UUID,
        request: ScheduleEvaluateRequest | None = None,
    ) -> ScheduleEvaluateResponse:
        payload = request or ScheduleEvaluateRequest()
        facility = self._facilities.get_by_id(facility_id)
        if facility is None:
            raise NotFoundError(f"Facility {facility_id} not found")

        evaluated_at = payload.evaluated_at or datetime.now(timezone.utc)
        if evaluated_at.tzinfo is None:
            raise SetuHaulError("evaluated_at must be timezone-aware")
        evaluated_at = evaluated_at.astimezone(timezone.utc)

        window_start = payload.scheduling_start or evaluated_at
        window_end = payload.scheduling_end or (window_start + timedelta(hours=24))
        if window_end <= window_start:
            raise SetuHaulError("scheduling_end must be after scheduling_start")
        window_start = window_start.astimezone(timezone.utc)
        window_end = window_end.astimezone(timezone.utc)

        shipment_ids = _unique_ids(payload.shipment_ids)
        shipments = self._load_shipments(facility_id, shipment_ids)
        slots = self._load_slots(facility_id, window_start, window_end)
        docks = self._load_docks(facility_id)
        protected = self._protected_by_shipment(facility_id)
        checkins = self._latest_arrival(facility_id)

        snapshots: list[ShipmentSnapshot] = []
        for shipment in shipments:
            latest = self._shipments.get_latest_eta(shipment.id)
            exceptions = self._exceptions.list_for_shipment(shipment.id)
            active = [
                item
                for item in exceptions
                if item.status.value in ACTIVE_EXCEPTION_STATUSES
            ]
            hold = protected.get(shipment.id)
            snapshots.append(
                ShipmentSnapshot(
                    shipment_id=shipment.id,
                    shipment_number=shipment.shipment_number,
                    status=shipment.status.value,
                    latest_eta=_aware(latest.new_eta) if latest is not None else None,
                    gate_in_at=_aware(checkins[shipment.id]) if shipment.id in checkins else None,
                    has_active_exception=bool(active),
                    missing_eta=latest is None,
                    protected_slot_id=hold[0] if hold else None,
                    protected_dock_id=hold[1] if hold else None,
                    protected_status=hold[2] if hold else None,
                )
            )
        snapshots.sort(key=lambda item: (item.shipment_number, str(item.shipment_id)))

        slot_snaps = tuple(slots)
        dock_snaps = tuple(docks)
        options = self._evaluate_options(snapshots, slot_snaps, dock_snaps, evaluated_at)
        result = self._engine.evaluate(
            SchedulingContext(
                facility_id=facility_id,
                evaluated_at=evaluated_at,
                scheduling_start=window_start,
                scheduling_end=window_end,
                shipments=tuple(snapshots),
                slots=slot_snaps,
                docks=dock_snaps,
                options=options,
            )
        )
        return ScheduleEvaluateResponse(
            facility_id=result.facility_id,
            evaluated_at=result.evaluated_at,
            scheduling_start=window_start,
            scheduling_end=window_end,
            ranking_policy=result.ranking_policy,
            read_only=True,
            commits_capacity=False,
            candidate_shipments=[
                CandidateShipmentResponse(
                    shipment_id=item.shipment_id,
                    shipment_number=item.shipment_number,
                    status=item.status,
                    latest_eta=item.latest_eta,
                    gate_in_at=item.gate_in_at,
                    has_active_exception=item.has_active_exception,
                    missing_eta=item.missing_eta,
                    protected=item.protected_slot_id is not None,
                )
                for item in snapshots
            ],
            proposed_assignments=[
                ScheduleAssignmentResponse(
                    shipment_id=item.shipment_id,
                    shipment_number=item.shipment_number,
                    slot_id=item.slot_id,
                    dock_id=item.dock_id,
                    rank=item.rank,
                    score=item.score,
                    kind=item.kind,
                    lateness_seconds=item.lateness_seconds,
                    early_wait_seconds=item.early_wait_seconds,
                    alignment_seconds=item.alignment_seconds,
                    yard_wait_seconds=item.yard_wait_seconds,
                    reasons=list(item.reasons),
                )
                for item in result.assignments
            ],
            unassigned_shipments=[
                UnassignedShipmentResponse(
                    shipment_id=item.shipment_id,
                    shipment_number=item.shipment_number,
                    reason=item.reason,
                    detail=item.detail,
                )
                for item in result.unassigned
            ],
            warnings=list(result.warnings),
        )

    def _load_shipments(self, facility_id: UUID, shipment_ids: list[UUID]):
        if shipment_ids:
            loaded = []
            for shipment_id in shipment_ids:
                shipment = self._shipments.get_by_id(shipment_id)
                if shipment is None:
                    raise NotFoundError(f"Shipment {shipment_id} not found")
                if shipment.destination_facility_id != facility_id:
                    raise SetuHaulError("Shipment is not destined to this facility")
                if shipment.status.value in TERMINAL_SHIPMENT_STATUSES or not shipment.is_active:
                    continue
                if shipment.status not in _ELIGIBLE_STATUSES:
                    continue
                loaded.append(shipment)
            loaded.sort(key=lambda item: (item.shipment_number, str(item.id)))
            return loaded[:MAX_SHIPMENTS]
        items, _total = self._shipments.list_paginated(
            page=1,
            page_size=MAX_SHIPMENTS,
            destination_facility_id=facility_id,
            is_active=True,
        )
        eligible = [
            item
            for item in items
            if item.status in _ELIGIBLE_STATUSES and item.status.value not in TERMINAL_SHIPMENT_STATUSES
        ]
        eligible.sort(key=lambda item: (item.shipment_number, str(item.id)))
        return eligible

    def _load_slots(self, facility_id: UUID, start: datetime, end: datetime) -> list[SlotSnapshot]:
        open_slots = self._slots.list_open_by_facility(facility_id)
        selected = [
            slot
            for slot in open_slots
            if slot.status == AppointmentSlotStatus.OPEN
            and _aware(slot.start_time) < end
            and _aware(slot.end_time) > start
        ]
        selected.sort(key=lambda item: (_aware(item.start_time), item.id))
        selected = selected[:MAX_SLOTS]
        snapshots: list[SlotSnapshot] = []
        for slot in selected:
            booked = self._appointments.count_by_slot(slot.id, _CAPACITY_STATUSES)
            snapshots.append(
                SlotSnapshot(
                    slot_id=slot.id,
                    start_time=_aware(slot.start_time),
                    end_time=_aware(slot.end_time),
                    capacity=slot.capacity,
                    remaining_capacity=max(0, slot.capacity - booked),
                    status=slot.status.value,
                )
            )
        return snapshots

    def _load_docks(self, facility_id: UUID) -> list[DockSnapshot]:
        docks = self._docks.list_available_by_facility(facility_id)
        docks.sort(key=lambda item: (item.name, str(item.id)))
        return [
            DockSnapshot(dock_id=dock.id, name=dock.name, status=dock.status.value)
            for dock in docks
            if dock.status == DockStatus.AVAILABLE
        ]

    def _protected_by_shipment(self, facility_id: UUID) -> dict[UUID, tuple[UUID | None, UUID | None, str]]:
        rows = self._appointments.list_consuming_for_facility(facility_id, _PROTECTED_STATUSES)
        mapping: dict[UUID, tuple[UUID | None, UUID | None, str]] = {}
        for row in rows:
            mapping[row.shipment_id] = (row.appointment_slot_id, row.dock_id, row.status.value)
        return mapping

    def _latest_arrival(self, facility_id: UUID) -> dict[UUID, datetime]:
        rows = self._checkins.list_for_facility(facility_id)
        earliest: dict[UUID, datetime] = {}
        for row in rows:
            if row.checkin_type not in _ARRIVAL_CHECKINS:
                continue
            previous = earliest.get(row.shipment_id)
            if previous is None or _aware(row.occurred_at) < previous:
                earliest[row.shipment_id] = _aware(row.occurred_at)
        return earliest

    def _evaluate_options(
        self,
        shipments: list[ShipmentSnapshot],
        slots: tuple[SlotSnapshot, ...],
        docks: tuple[DockSnapshot, ...],
        evaluated_at: datetime,
    ) -> tuple[FeasibleOption, ...]:
        cache: dict[tuple[UUID, UUID, UUID | None], FeasibleOption] = {}
        options: list[FeasibleOption] = []
        for shipment in shipments:
            if shipment.protected_slot_id is not None:
                continue
            for slot in slots:
                chosen: FeasibleOption | None = None
                for dock in docks:
                    option = self._evaluate_pair(
                        cache,
                        shipment,
                        slot,
                        dock.dock_id,
                        evaluated_at,
                    )
                    if option.feasible:
                        chosen = option
                        break
                if chosen is None:
                    chosen = self._evaluate_pair(cache, shipment, slot, None, evaluated_at)
                options.append(chosen)
        options.sort(key=lambda item: (str(item.shipment_id), str(item.slot_id), str(item.dock_id or "")))
        return tuple(options)

    def _evaluate_pair(
        self,
        cache: dict[tuple[UUID, UUID, UUID | None], FeasibleOption],
        shipment: ShipmentSnapshot,
        slot: SlotSnapshot,
        dock_id: UUID | None,
        evaluated_at: datetime,
    ) -> FeasibleOption:
        key = (shipment.shipment_id, slot.slot_id, dock_id)
        cached = cache.get(key)
        if cached is not None:
            return cached
        result = self._feasibility.evaluate(
            shipment.shipment_id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=slot.slot_id,
                dock_id=dock_id,
                evaluated_at=evaluated_at,
            ),
        )
        lateness = None
        early_wait = None
        alignment = None
        if shipment.latest_eta is not None:
            eta = _aware(shipment.latest_eta)
            lateness = max(0, int((eta - _aware(slot.end_time)).total_seconds()))
            early_wait = max(0, int((_aware(slot.start_time) - eta).total_seconds()))
            alignment = abs(int((eta - _aware(slot.start_time)).total_seconds()))
        yard_wait = None
        if shipment.gate_in_at is not None:
            yard_wait = max(0, int((evaluated_at - _aware(shipment.gate_in_at)).total_seconds()))
        option = FeasibleOption(
            shipment_id=shipment.shipment_id,
            slot_id=slot.slot_id,
            dock_id=dock_id,
            feasible=bool(result.feasible),
            outcome=result.outcome.value if hasattr(result.outcome, "value") else str(result.outcome),
            lateness_seconds=lateness,
            early_wait_seconds=early_wait,
            alignment_seconds=alignment,
            yard_wait_seconds=yard_wait,
            blocking_reasons=tuple(result.blocking_reasons),
            warnings=tuple(result.warnings),
        )
        cache[key] = option
        return option


def _unique_ids(values: list[UUID] | None) -> list[UUID]:
    if not values:
        return []
    seen: set[UUID] = set()
    ordered: list[UUID] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
