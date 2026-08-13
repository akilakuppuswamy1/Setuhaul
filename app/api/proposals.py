"""Step 7 proposal API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import get_proposal_service
from app.schemas.proposal import ProposalCreateRequest, ProposalResponse
from app.services.proposal import ProposalService

router = APIRouter(tags=["Proposals"])


@router.post(
    "/shipments/{shipment_id}/proposals",
    response_model=ProposalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a controlled operational proposal",
    responses={
        404: {"description": "Shipment, slot, or dock not found"},
        400: {"description": "Infeasible or invalid business request"},
        422: {"description": "Malformed request"},
    },
)
def create_proposal(
    shipment_id: UUID,
    payload: ProposalCreateRequest,
    service: ProposalService = Depends(get_proposal_service),
) -> ProposalResponse:
    return service.create(shipment_id, payload)


@router.get(
    "/proposals/{proposal_id}",
    response_model=ProposalResponse,
    summary="Get proposal by ID",
    responses={404: {"description": "Proposal not found"}},
)
def get_proposal(
    proposal_id: UUID,
    service: ProposalService = Depends(get_proposal_service),
) -> ProposalResponse:
    return service.get(proposal_id)


@router.post(
    "/proposals/{proposal_id}/accept",
    response_model=ProposalResponse,
    summary="Accept a proposal with final revalidation and allocation",
    responses={
        404: {"description": "Proposal not found"},
        409: {"description": "Stale proposal or conflicting state"},
        400: {"description": "Invalid transition"},
    },
)
def accept_proposal(
    proposal_id: UUID,
    service: ProposalService = Depends(get_proposal_service),
) -> ProposalResponse:
    return service.accept(proposal_id)


@router.post(
    "/proposals/{proposal_id}/reject",
    response_model=ProposalResponse,
    summary="Reject a proposal",
    responses={
        404: {"description": "Proposal not found"},
        409: {"description": "Conflicting state"},
        400: {"description": "Invalid transition"},
    },
)
def reject_proposal(
    proposal_id: UUID,
    service: ProposalService = Depends(get_proposal_service),
) -> ProposalResponse:
    return service.reject(proposal_id)
