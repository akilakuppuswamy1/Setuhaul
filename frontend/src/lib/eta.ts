import type { ETAUpdate } from "@/api/types";
import { formatDelay } from "@/lib/format";

export interface EtaDisplay {
  originalEta: string | null;
  updatedEta: string | null;
  delayLabel: string | null;
}

/** Derive original vs updated ETA from immutable backend history. Never use appointment slot time. */
export function deriveEtaDisplay(history: ETAUpdate[]): EtaDisplay {
  if (!history.length) {
    return { originalEta: null, updatedEta: null, delayLabel: null };
  }
  const latest = history[history.length - 1];
  const dispatch = history.find((item) => item.source === "dispatch");
  const originalEta =
    latest.previous_eta ??
    dispatch?.new_eta ??
    history[0]?.previous_eta ??
    (history.length > 1 ? history[0]?.new_eta : null);
  const updatedEta = latest.new_eta;
  return {
    originalEta,
    updatedEta,
    delayLabel: formatDelay(originalEta, updatedEta),
  };
}
