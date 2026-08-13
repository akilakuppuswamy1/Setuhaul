"""Documented ranking policy for the optional facility scheduler.

Shipment priority and expected unloading duration are not in the frozen schema
and are never invented. Criteria that cannot be computed are marked not evaluable.
"""

RANKING_POLICY = (
    "protected confirmed/held appointments are not displaced; "
    "remaining feasible shipments are ordered by arrival evidence "
    "(earlier gate-in/yard check-in first, then shipments still en route); "
    "then lower ETA lateness versus the slot end; "
    "then lower early-wait (ETA before slot start); "
    "then closer ETA-to-slot-start alignment; "
    "then earlier slot start; "
    "then dock name; "
    "then shipment_id; "
    "then slot_id. "
    "Missing ETA is not fabricated: those shipments rank after shipments with a known ETA. "
    "Shipment priority and unload duration are not evaluable with the frozen schema."
)

# Sort-key only. Never persisted or presented as an operational measurement.
MISSING_METRIC_SENTINEL = 10**12
