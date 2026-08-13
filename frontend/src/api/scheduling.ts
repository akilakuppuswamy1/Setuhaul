import { apiRequest } from "./client";
import type { ScheduleEvaluateResponse } from "./types";

export function evaluateFacilitySchedule(facilityId: string) {
  return apiRequest<ScheduleEvaluateResponse>(`/facilities/${facilityId}/schedule/evaluate`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}
