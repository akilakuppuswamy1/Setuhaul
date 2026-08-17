export type TimelineStage =
  | "idle"
  | "exception_reported"
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
  { id: "exception_reported", label: "Exception reported" },
  { id: "eta_updated", label: "ETA updated" },
  { id: "options_found", label: "Options evaluated" },
  { id: "proposal_created", label: "Appointment proposed" },
  { id: "awaiting_confirmation", label: "Awaiting confirmation" },
  { id: "confirmed", label: "Appointment confirmed" },
] as const;

export type TimelineStepId = (typeof TIMELINE_STEPS)[number]["id"];

export function deriveStage(input: {
  loading?: boolean;
  loadingKind?: string | null;
  hasEtaUpdate?: boolean;
  hasException?: boolean;
  optionCount?: number;
  proposalStatus?: string | null;
  intent?: string | null;
  conversationStatus?: string | null;
  conflict?: boolean;
  escalated?: boolean;
  appointmentStatus?: string | null;
  hasProposalRecord?: boolean;
  rescheduled?: boolean;
}): TimelineStage {
  if (input.conflict || input.conversationStatus === "stale" || input.proposalStatus === "stale") {
    return "stale";
  }
  if (input.escalated) return "escalated";
  if (input.proposalStatus === "confirmed" || input.appointmentStatus === "confirmed" || input.appointmentStatus === "held") {
    return "confirmed";
  }
  if (input.loading && input.loadingKind === "confirm") return "revalidating";
  if (input.intent === "ASK_STATUS") return "status_check";
  if (input.proposalStatus === "proposed") return "awaiting_confirmation";
  if (input.hasProposalRecord) return "proposal_created";
  if (input.optionCount && input.optionCount > 0) return "options_found";
  if (input.hasEtaUpdate) return "eta_updated";
  if (input.hasException) return "exception_reported";
  return "idle";
}

/** Steps completed from persisted operational records, not only the live chat session. */
export function completedTimelineSteps(input: {
  hasException?: boolean;
  hasEtaUpdate?: boolean;
  optionCount?: number;
  hasProposalRecord?: boolean;
  proposalStatus?: string | null;
  appointmentStatus?: string | null;
  rescheduled?: boolean;
}): TimelineStepId[] {
  const done: TimelineStepId[] = [];
  const confirmed =
    input.proposalStatus === "confirmed" ||
    input.appointmentStatus === "confirmed" ||
    input.appointmentStatus === "held" ||
    Boolean(input.rescheduled);
  const proposed =
    input.hasProposalRecord || input.proposalStatus === "proposed" || input.proposalStatus === "confirmed";
  const optionsSeen = Boolean(input.optionCount && input.optionCount > 0) || proposed;

  if (input.hasException) done.push("exception_reported");
  if (input.hasEtaUpdate) done.push("eta_updated");
  if (optionsSeen) done.push("options_found");
  if (proposed) done.push("proposal_created");
  if (input.proposalStatus === "proposed" || confirmed) done.push("awaiting_confirmation");
  if (confirmed) done.push("confirmed");
  return done;
}
