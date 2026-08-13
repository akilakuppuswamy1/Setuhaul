import { apiRequest } from "./client";
import type { Proposal } from "./types";

export function getProposal(proposalId: string) {
  return apiRequest<Proposal>(`/proposals/${proposalId}`);
}

export function createProposal(
  shipmentId: string,
  payload: { appointment_slot_id: string; dock_id?: string | null; notes?: string },
) {
  return apiRequest<Proposal>(`/shipments/${shipmentId}/proposals`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function acceptProposal(proposalId: string) {
  return apiRequest<Proposal>(`/proposals/${proposalId}/accept`, { method: "POST" });
}

export function rejectProposal(proposalId: string) {
  return apiRequest<Proposal>(`/proposals/${proposalId}/reject`, { method: "POST" });
}
