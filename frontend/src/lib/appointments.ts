import type { Appointment } from "@/api/types";

export function isProposalAppointment(item: Appointment): boolean {
  return (item.notes ?? "").includes("STEP7_PROPOSAL");
}

export function isSupersededAppointment(item: Appointment): boolean {
  const notes = item.notes ?? "";
  return notes.includes("superseded_by=") || notes.includes("DEMO:HISTORY");
}

export function pickCurrentAppointment(appointments: Appointment[]): Appointment | undefined {
  const operational = appointments.filter(
    (item) => !isProposalAppointment(item) && (item.status === "confirmed" || item.status === "held"),
  );
  if (!operational.length) return undefined;
  return [...operational].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}

export function pickPendingProposalAppointment(appointments: Appointment[]): Appointment | undefined {
  const pending = appointments.filter((item) => isProposalAppointment(item) && item.status === "requested");
  if (!pending.length) return undefined;
  return [...pending].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}

export function pickStaleProposalAppointment(appointments: Appointment[]): Appointment | undefined {
  if (pickPendingProposalAppointment(appointments)) return undefined;
  const stale = appointments.filter(
    (item) => isProposalAppointment(item) && (item.notes ?? "").includes("stale_reason="),
  );
  if (!stale.length) return undefined;
  return [...stale].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
}

export function hasSupersededHistory(appointments: Appointment[]): boolean {
  return appointments.some((item) => isSupersededAppointment(item));
}

export function pickOriginalAppointment(appointments: Appointment[]): Appointment | undefined {
  const superseded = appointments.filter((item) => !isProposalAppointment(item) && isSupersededAppointment(item));
  if (superseded.length) {
    return [...superseded].sort((a, b) => a.created_at.localeCompare(b.created_at))[0];
  }
  const operational = appointments.filter(
    (item) =>
      !isProposalAppointment(item) &&
      (item.status === "requested" || item.status === "confirmed" || item.status === "held"),
  );
  const pool = operational.length ? operational : appointments.filter((item) => !isProposalAppointment(item));
  return [...pool].sort((a, b) => a.created_at.localeCompare(b.created_at))[0];
}

export function appointmentStatusLabel(item: Appointment): string {
  const notes = item.notes ?? "";
  if (isSupersededAppointment(item) || (item.status === "cancelled" && notes.includes("superseded_by="))) {
    return "Cancelled / Superseded";
  }
  if (isProposalAppointment(item) && item.status === "requested") return "Proposed";
  if (isProposalAppointment(item) && (item.status === "cancelled" || notes.includes("stale_reason="))) {
    return "Proposal cancelled";
  }
  if (item.status === "confirmed") return "Confirmed";
  if (item.status === "requested") return "Requested";
  if (item.status === "cancelled") return "Cancelled";
  if (item.status === "held") return "Held";
  return item.status;
}
