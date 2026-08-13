export type TimelineStage =
  | "idle"
  | "eta_updated"
  | "options_found"
  | "proposal_created"
  | "awaiting_confirmation"
  | "status_check"
  | "revalidating"
  | "confirmed"
  | "stale"
  | "escalated";

export const TIMELINE_STEPS = [
  { id: "eta_updated", label: "ETA updated" },
  { id: "options_found", label: "Options found" },
  { id: "proposal_created", label: "Proposal created" },
  { id: "awaiting_confirmation", label: "Awaiting confirmation" },
  { id: "revalidating", label: "Revalidating" },
  { id: "confirmed", label: "Confirmed" },
] as const;

export function deriveStage(input: {
  loading?: boolean;
  loadingKind?: string | null;
  hasEtaUpdate?: boolean;
  optionCount?: number;
  proposalStatus?: string | null;
  intent?: string | null;
  conversationStatus?: string | null;
  conflict?: boolean;
  escalated?: boolean;
}): TimelineStage {
  if (input.conflict || input.conversationStatus === "stale" || input.proposalStatus === "stale") {
    return "stale";
  }
  if (input.escalated) return "escalated";
  if (input.proposalStatus === "confirmed") return "confirmed";
  if (input.loading && input.loadingKind === "confirm") return "revalidating";
  if (input.intent === "ASK_STATUS") return "status_check";
  if (input.proposalStatus === "proposed") return "awaiting_confirmation";
  if (input.optionCount && input.optionCount > 0 && !input.proposalStatus) return "options_found";
  if (input.hasEtaUpdate) return "eta_updated";
  return "idle";
}
