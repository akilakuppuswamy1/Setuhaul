"""Step 7 controlled proposal lifecycle with revalidation and Step 6 allocation."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError
from app.engines.feasibility.models import FeasibilityOutcome
from app.models.appointment import Appointment
from app.models.enums import AppointmentStatus
from app.repositories.appointment import AppointmentRepository
from app.repositories.appointment_slot import AppointmentSlotRepository
from app.repositories.dock import DockRepository
from app.repositories.shipment import ShipmentRepository
from app.schemas.allocation import AllocationRequest
from app.schemas.feasibility import FeasibilityEvaluateRequest
from app.schemas.proposal import ProposalCreateRequest, ProposalResponse, ProposalStatus
from app.services.allocation import AllocationService
from app.services.feasibility import FeasibilityService
from app.services.helpers import safe_commit

PROPOSAL_MARKER = "STEP7_PROPOSAL"
PROPOSAL_TTL_MINUTES = 30

_ACTIVE_ALLOCATION_STATUSES = (
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.HELD,
)

_VALID_TRANSITIONS: dict[ProposalStatus, set[ProposalStatus]] = {
    ProposalStatus.PROPOSED: {
        ProposalStatus.ACCEPTED,
        ProposalStatus.REJECTED,
        ProposalStatus.EXPIRED,
        ProposalStatus.STALE,
    },
    ProposalStatus.ACCEPTED: {ProposalStatus.CONFIRMED, ProposalStatus.STALE},
    ProposalStatus.REJECTED: set(),
    ProposalStatus.EXPIRED: set(),
    ProposalStatus.STALE: set(),
    ProposalStatus.CONFIRMED: set(),
}


def _compute_expires_at(created_at: datetime) -> datetime:
    normalized = _ensure_utc(created_at)
    return normalized + timedelta(minutes=PROPOSAL_TTL_MINUTES)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_proposal_record(appointment: Appointment) -> bool:
    return appointment.notes is not None and PROPOSAL_MARKER in appointment.notes


def _build_proposal_notes(user_notes: str | None) -> str:
    if user_notes:
        return f"{PROPOSAL_MARKER}\n{user_notes}"
    return PROPOSAL_MARKER


def _parse_confirmed_appointment_id(notes: str | None) -> UUID | None:
    if notes is None:
        return None
    for line in notes.splitlines():
        if line.startswith("confirmed_appointment_id="):
            return UUID(line.split("=", 1)[1].strip())
    return None


def _parse_stale_reason(notes: str | None) -> str | None:
    if notes is None:
        return None
    for line in notes.splitlines():
        if line.startswith("stale_reason="):
            return line.split("=", 1)[1].strip()
    return None


def _build_confirmed_notes(existing_notes: str | None, appointment_id: UUID) -> str:
    base = existing_notes or PROPOSAL_MARKER
    if PROPOSAL_MARKER not in base:
        base = f"{PROPOSAL_MARKER}\n{base}"
    return f"{base}\nconfirmed_appointment_id={appointment_id}"


def _build_stale_notes(existing_notes: str | None, reason: str) -> str:
    base = existing_notes or PROPOSAL_MARKER
    if PROPOSAL_MARKER not in base:
        base = f"{PROPOSAL_MARKER}\n{base}"
    return f"{base}\nstale_reason={reason}"


class ProposalService:
    """Controlled proposal lifecycle: propose → accept/reject → revalidate → allocate."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._shipment_repo = ShipmentRepository(session)
        self._appointment_repo = AppointmentRepository(session)
        self._slot_repo = AppointmentSlotRepository(session)
        self._dock_repo = DockRepository(session)
        self._feasibility_service = FeasibilityService(session)
        self._allocation_service = AllocationService(session)

    def create(
        self,
        shipment_id: UUID,
        payload: ProposalCreateRequest,
    ) -> ProposalResponse:
        shipment = self._shipment_repo.get_by_id(shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found")

        if shipment.destination_facility_id is None:
            raise SetuHaulError("Shipment has no destination facility assigned")

        slot = self._slot_repo.get_by_id(payload.appointment_slot_id)
        if slot is None:
            raise NotFoundError(f"Appointment slot {payload.appointment_slot_id} not found")

        if slot.facility_id != shipment.destination_facility_id:
            raise SetuHaulError(
                "Appointment slot does not belong to the shipment destination facility"
            )

        if payload.dock_id is not None:
            dock = self._dock_repo.get_by_id(payload.dock_id)
            if dock is None:
                raise NotFoundError(f"Dock {payload.dock_id} not found")
            if dock.facility_id != shipment.destination_facility_id:
                raise SetuHaulError(
                    "Dock does not belong to the shipment destination facility"
                )

        evaluated_at = datetime.now(timezone.utc)
        feasibility = self._feasibility_service.evaluate(
            shipment_id,
            FeasibilityEvaluateRequest(
                appointment_slot_id=payload.appointment_slot_id,
                dock_id=payload.dock_id,
                evaluated_at=evaluated_at,
                ignore_delay_exceptions=True,
            ),
        )

        if feasibility.outcome == FeasibilityOutcome.NOT_EVALUABLE:
            raise SetuHaulError(
                "Proposal context is not evaluable: "
                + "; ".join(feasibility.blocking_reasons or ["missing data"])
            )

        if not feasibility.feasible:
            raise SetuHaulError(
                "Proposal is not feasible: " + "; ".join(feasibility.blocking_reasons)
            )

        appointment = self._appointment_repo.create(
            shipment_id=shipment_id,
            facility_id=shipment.destination_facility_id,
            appointment_slot_id=payload.appointment_slot_id,
            dock_id=payload.dock_id,
            status=AppointmentStatus.REQUESTED,
            notes=_build_proposal_notes(payload.notes),
        )
        safe_commit(self._session)

        return self._to_response(
            appointment,
            status=ProposalStatus.PROPOSED,
            message="Proposal created",
        )

    def get(self, proposal_id: UUID) -> ProposalResponse:
        appointment = self._get_proposal_appointment(proposal_id)
        now = datetime.now(timezone.utc)
        status = self._resolve_status(appointment, now)
        if status == ProposalStatus.EXPIRED and appointment.status == AppointmentStatus.REQUESTED:
            self._expire_proposal(appointment)
            safe_commit(self._session)
        return self._to_response(appointment, status=status, message="Proposal retrieved")

    def find_for_conversation(self, shipment_id: UUID) -> tuple[list[ProposalResponse], int]:
        """Deterministic lookup of pending (and recent stale) proposals for a shipment.

        Returns (candidates, pending_requested_count). Does not accept or allocate.
        """
        items, _ = self._appointment_repo.list_by_shipment(shipment_id, page=1, page_size=50)
        proposals = [item for item in items if _is_proposal_record(item)]
        now = datetime.now(timezone.utc)
        requested = [
            item
            for item in proposals
            if item.status == AppointmentStatus.REQUESTED
            and self._resolve_status(item, now) == ProposalStatus.PROPOSED
        ]
        requested.sort(key=lambda item: (item.created_at, str(item.id)), reverse=True)
        if requested:
            return [self._to_response(item, status=ProposalStatus.PROPOSED, message="Pending proposal") for item in requested], len(requested)
        stale = [
            item
            for item in proposals
            if self._resolve_status(item, now) == ProposalStatus.STALE
            and _parse_confirmed_appointment_id(item.notes) is None
        ]
        stale.sort(key=lambda item: (item.updated_at, str(item.id)), reverse=True)
        if stale:
            latest = stale[0]
            return [self._to_response(latest, status=ProposalStatus.STALE, message="Stale proposal")], 0
        return [], 0

    def reject(self, proposal_id: UUID) -> ProposalResponse:
        appointment = self._get_proposal_appointment(proposal_id)
        now = datetime.now(timezone.utc)
        current = self._resolve_status(appointment, now)

        if current == ProposalStatus.CONFIRMED:
            raise ConflictError("Proposal is already confirmed")

        if current == ProposalStatus.REJECTED:
            return self._to_response(appointment, status=current, message="Proposal already rejected")

        if current == ProposalStatus.STALE:
            raise ConflictError("Proposal is stale and cannot be rejected")

        if current == ProposalStatus.EXPIRED:
            if appointment.status == AppointmentStatus.REQUESTED:
                self._expire_proposal(appointment)
                safe_commit(self._session)
            raise SetuHaulError("Cannot reject an expired proposal")

        if current != ProposalStatus.PROPOSED:
            raise SetuHaulError(
                f"Cannot transition proposal from {current.value} to rejected"
            )

        appointment.status = AppointmentStatus.REJECTED
        self._session.flush()
        safe_commit(self._session)
        self._session.refresh(appointment)

        return self._to_response(
            appointment,
            status=ProposalStatus.REJECTED,
            message="Proposal rejected",
        )

    def accept(self, proposal_id: UUID) -> ProposalResponse:
        appointment = self._get_proposal_appointment(proposal_id)
        shipment_id = appointment.shipment_id

        try:
            if not self._appointment_repo.try_acquire_shipment_advisory_lock(shipment_id):
                raise ConflictError("Proposal is stale: concurrent_confirmation")
            appointment = self._get_proposal_appointment(proposal_id, locked=True)
            now = datetime.now(timezone.utc)

            confirmed_id = _parse_confirmed_appointment_id(appointment.notes)
            if confirmed_id is not None:
                return self._to_response(
                    appointment,
                    status=ProposalStatus.CONFIRMED,
                    message="Proposal already confirmed",
                    appointment_id=confirmed_id,
                )

            matching = self._find_matching_confirmed_allocation(appointment)
            if matching is not None:
                self._mark_confirmed(appointment, matching.id)
                safe_commit(self._session)
                return self._to_response(
                    appointment,
                    status=ProposalStatus.CONFIRMED,
                    message="Proposal already confirmed",
                    appointment_id=matching.id,
                )

            current = self._resolve_status(appointment, now)

            if current == ProposalStatus.EXPIRED:
                if appointment.status == AppointmentStatus.REQUESTED:
                    self._expire_proposal(appointment)
                    safe_commit(self._session)
                raise ConflictError("Proposal has expired")

            if current == ProposalStatus.REJECTED:
                raise SetuHaulError("Cannot accept a rejected proposal")

            if current == ProposalStatus.STALE:
                raise ConflictError("Proposal is stale: slot no longer available")

            self._ensure_acceptable_transition(current, ProposalStatus.ACCEPTED)

            if current != ProposalStatus.PROPOSED:
                raise SetuHaulError(
                    f"Cannot accept proposal in {current.value} state"
                )

            slot_id = appointment.appointment_slot_id
            if slot_id is None:
                raise SetuHaulError("Proposal has no appointment slot")

            slot = self._slot_repo.get_by_id(slot_id)
            if slot is None:
                self._mark_stale(appointment, "slot_not_found")
                safe_commit(self._session)
                raise ConflictError("Proposal slot no longer exists")

            dock_id = appointment.dock_id
            if dock_id is not None:
                dock = self._dock_repo.get_by_id(dock_id)
                if dock is None:
                    self._mark_stale(appointment, "dock_not_found")
                    safe_commit(self._session)
                    raise ConflictError("Proposal dock no longer exists")

            feasibility = self._feasibility_service.evaluate(
                shipment_id,
                FeasibilityEvaluateRequest(
                    appointment_slot_id=slot_id,
                    dock_id=dock_id,
                    evaluated_at=now,
                    ignore_delay_exceptions=True,
                ),
            )

            if feasibility.outcome != FeasibilityOutcome.FEASIBLE or not feasibility.feasible:
                reason = (
                    "feasibility_changed"
                    if feasibility.outcome == FeasibilityOutcome.NOT_FEASIBLE
                    else "not_evaluable"
                )
                self._mark_stale(appointment, reason)
                safe_commit(self._session)
                raise ConflictError(f"Proposal is stale: {reason}")

            try:
                allocation = self._allocation_service.allocate(
                    shipment_id,
                    AllocationRequest(
                        appointment_slot_id=slot_id,
                        dock_id=dock_id,
                        evaluated_at=now,
                    ),
                    commit=False,
                    replace_active=True,
                    ignore_delay_exceptions=True,
                )
            except ConflictError as exc:
                reconciled = self._try_reconcile_confirmed(appointment)
                if reconciled is not None:
                    return reconciled
                self._mark_stale(appointment, "slot_capacity_changed")
                safe_commit(self._session)
                raise ConflictError("Proposal is stale: slot_capacity_changed") from exc
            except SetuHaulError as exc:
                reconciled = self._try_reconcile_confirmed(appointment)
                if reconciled is not None:
                    return reconciled
                self._mark_stale(appointment, "allocation_infeasible")
                safe_commit(self._session)
                raise ConflictError("Proposal is stale: allocation_infeasible") from exc

            confirmed_appointment_id = allocation.appointment.id
            self._mark_confirmed(appointment, confirmed_appointment_id)
            safe_commit(self._session)

            return self._to_response(
                appointment,
                status=ProposalStatus.CONFIRMED,
                message="Proposal confirmed",
                appointment_id=confirmed_appointment_id,
            )
        except (ConflictError, NotFoundError, SetuHaulError):
            raise
        except Exception:
            self._session.rollback()
            raise

    def _try_reconcile_confirmed(self, appointment: Appointment) -> ProposalResponse | None:
        """Recover when Step 6 committed but proposal state was not updated."""
        matching = self._find_matching_confirmed_allocation(appointment)
        if matching is None:
            return None
        self._mark_confirmed(appointment, matching.id)
        safe_commit(self._session)
        return self._to_response(
            appointment,
            status=ProposalStatus.CONFIRMED,
            message="Proposal already confirmed",
            appointment_id=matching.id,
        )

    def _get_proposal_appointment(self, proposal_id: UUID, *, locked: bool = False) -> Appointment:
        if locked:
            appointment = self._appointment_repo.get_by_id_locked(proposal_id)
        else:
            appointment = self._appointment_repo.get_by_id(proposal_id)
        if appointment is None:
            raise NotFoundError(f"Proposal {proposal_id} not found")
        if not _is_proposal_record(appointment):
            raise NotFoundError(f"Proposal {proposal_id} not found")
        return appointment

    def _resolve_status(self, appointment: Appointment, now: datetime) -> ProposalStatus:
        confirmed_id = _parse_confirmed_appointment_id(appointment.notes)
        if confirmed_id is not None:
            return ProposalStatus.CONFIRMED

        stale_reason = _parse_stale_reason(appointment.notes)
        if stale_reason is not None:
            return ProposalStatus.STALE

        if appointment.status == AppointmentStatus.REJECTED:
            return ProposalStatus.REJECTED

        if appointment.status == AppointmentStatus.EXPIRED:
            return ProposalStatus.EXPIRED

        if appointment.status == AppointmentStatus.CANCELLED:
            return ProposalStatus.STALE

        if appointment.status == AppointmentStatus.REQUESTED:
            expires_at = _compute_expires_at(appointment.created_at)
            if now > expires_at:
                return ProposalStatus.EXPIRED
            return ProposalStatus.PROPOSED

        raise SetuHaulError(f"Appointment {appointment.id} is not a valid proposal record")

    def _expire_proposal(self, appointment: Appointment) -> None:
        appointment.status = AppointmentStatus.EXPIRED

    def _mark_stale(self, appointment: Appointment, reason: str) -> None:
        appointment.status = AppointmentStatus.CANCELLED
        appointment.notes = _build_stale_notes(appointment.notes, reason)

    def _mark_confirmed(self, appointment: Appointment, confirmed_appointment_id: UUID) -> None:
        appointment.status = AppointmentStatus.CANCELLED
        appointment.notes = _build_confirmed_notes(appointment.notes, confirmed_appointment_id)

    def _find_matching_confirmed_allocation(
        self,
        proposal: Appointment,
    ) -> Appointment | None:
        active = self._appointment_repo.get_active_for_shipment(
            proposal.shipment_id,
            _ACTIVE_ALLOCATION_STATUSES,
        )
        if active is None:
            return None
        if active.appointment_slot_id != proposal.appointment_slot_id:
            return None
        if proposal.dock_id is not None and active.dock_id != proposal.dock_id:
            return None
        return active

    @staticmethod
    def _ensure_acceptable_transition(
        current: ProposalStatus,
        target: ProposalStatus,
    ) -> None:
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise SetuHaulError(
                f"Cannot transition proposal from {current.value} to {target.value}"
            )

    def _to_response(
        self,
        appointment: Appointment,
        *,
        status: ProposalStatus,
        message: str,
        appointment_id: UUID | None = None,
    ) -> ProposalResponse:
        resolved_appointment_id = appointment_id or _parse_confirmed_appointment_id(
            appointment.notes
        )
        return ProposalResponse(
            proposal_id=appointment.id,
            shipment_id=appointment.shipment_id,
            slot_id=appointment.appointment_slot_id,
            dock_id=appointment.dock_id,
            status=status,
            expires_at=_compute_expires_at(appointment.created_at),
            message=message,
            reason=_parse_stale_reason(appointment.notes),
            appointment_id=resolved_appointment_id,
        )
