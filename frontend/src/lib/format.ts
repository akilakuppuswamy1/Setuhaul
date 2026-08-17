export function formatDateTime(value?: string | null, timeZone?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    day: "numeric",
    timeZone: timeZone || undefined,
    ...(timeZone ? { timeZoneName: "short" as const } : {}),
  }).format(date);
}

export function formatTime(value?: string | null, timeZone?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: timeZone || undefined,
    ...(timeZone ? { timeZoneName: "short" as const } : {}),
  }).format(date);
}

export function formatWindow(
  start?: string | null,
  end?: string | null,
  timeZone?: string | null,
): string {
  if (!start && !end) return "—";
  return `${formatTime(start, timeZone)} – ${formatTime(end, timeZone)}`;
}

export function formatDelay(from?: string | null, to?: string | null): string | null {
  if (!from || !to) return null;
  const a = new Date(from).getTime();
  const b = new Date(to).getTime();
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  const minutes = Math.round((b - a) / 60000);
  if (minutes === 0) return "0m";
  const sign = minutes > 0 ? "+" : "";
  const abs = Math.abs(minutes);
  const hours = Math.floor(abs / 60);
  const rest = abs % 60;
  if (hours && rest) return `${sign}${hours}h ${rest}m`;
  if (hours) return `${sign}${hours}h`;
  return `${sign}${rest}m`;
}

export function loadingCopy(message: string): string {
  const text = message.toLowerCase();
  if (/\b(has|have|is).{0,40}confirmed\b/.test(text) || text.includes("appointment status")) {
    return "Checking status (read-only)…";
  }
    if (text.includes("confirm it") || text.includes("book it") || text.includes("lock it in") || /^\s*confirm[.!]?\s*$/i.test(text)) {
    return "Revalidating…";
  }
  if (text.includes("option") && (text.includes("works") || /\b(first|second|third|\d+)\b/.test(text))) {
    return "Creating proposal…";
  }
  if (text.includes("what options") || text.includes("available options") || text.includes("another slot") || text.includes("next slot")) {
    return "Checking feasible options…";
  }
  if (text.includes("late") || text.includes("eta") || text.includes("traffic")) {
    return "Recording operational update…";
  }
  if (text.includes("human") || text.includes("dispatch")) {
    return "Recording escalation…";
  }
  return "Understanding…";
}
