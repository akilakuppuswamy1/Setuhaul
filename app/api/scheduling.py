from uuid import UUID

from fastapi import APIRouter, Body, Depends, status

from app.api.deps import get_scheduling_service
from app.schemas.scheduling import ScheduleEvaluateRequest, ScheduleEvaluateResponse
from app.services.scheduling import SchedulingService

router = APIRouter(tags=["Scheduling"])


@router.post(
    "/facilities/{facility_id}/schedule/evaluate",
    response_model=ScheduleEvaluateResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate a read-only proposed facility schedule",
    responses={
        404: {"description": "Facility or shipment not found"},
        400: {"description": "Invalid scheduling request"},
        422: {"description": "Malformed request"},
    },
)
def evaluate_facility_schedule(
    facility_id: UUID,
    payload: ScheduleEvaluateRequest = Body(default_factory=ScheduleEvaluateRequest),
    service: SchedulingService = Depends(get_scheduling_service),
) -> ScheduleEvaluateResponse:
    return service.evaluate(facility_id, payload)
