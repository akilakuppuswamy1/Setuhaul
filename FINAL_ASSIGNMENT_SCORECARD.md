# FINAL ASSIGNMENT SCORECARD

Phase 5 audit of the SetuHaul FDE working tree. Status values are PASS, FAIL, PARTIAL, or OUT OF SCOPE only.

Audit date: 16 August 2026  
Branch: `main`  
HEAD: `3db0de9 feat: complete SetuHaul FDE assignment`  
Evidence is from the **current working tree**, not from HEAD alone.

Overall: **PASS** for assignment-required behavior. Submission requires the user to commit required working-tree files (auditor does not commit).

| Area | Status | Evidence |
|------|--------|----------|
| Driver exception | PASS | Step 4 exception/ETA APIs; conversation `create_driver_exception` / delay language; `tests/test_step4_*.py`, `tests/test_step8_*.py` |
| ETA | PASS | Immutable `eta_updates`; latest ETA derived; live SHP-DEMO-NOCAP / Phase 4 shipments have driver ETA rows; `tests/test_step4_operations.py` |
| Original appointment | PASS | Bound shipment + original appointment identified in conversation context and shipment panel; reschedule original `75c4488c-…` still queryable |
| Feasibility | PASS | Step 5 `FeasibilityEngine`; SHOW uses `get_available_options`; `tests/test_step5_*.py` |
| Options | PASS | SHOW does not write consuming appointments; Playwright options path historically consumed race fixture; unit + Phase 2 booking-engine tests |
| Proposal | PASS | `Appointment` `requested` + `STEP7_PROPOSAL`; API status `proposed`; `tests/test_step7_proposals.py` |
| Confirmation | PASS | Explicit confirm → `ProposalService.accept` → Step 5 revalidation → Step 6; UI confirmation card only when backend status is confirmed |
| Capacity | PASS | Consuming statuses `confirmed`/`held` only; live query found **zero** slots with consuming count greater than capacity |
| Concurrency | PASS | PostgreSQL `tests/test_step6_concurrency.py`, `tests/test_step7_concurrency.py`, Phase 2 booking-engine tests: one winner / one conflict. Live two-request race **not re-driven** this audit (fixture consumed) |
| Stale proposal | PASS | Accept marks stale + HTTP 409; UI `data-testid="stale-conflict"`; unit tests. Live loser UI **not re-driven** this audit |
| Reschedule | PASS | Live `SHP-PHASE4-RESCHEDULE-001`: original cancelled with `superseded_by=`; new confirmed; Playwright 16 Aug 2026 |
| History | PASS | Original appointment id remains; old slot OPEN; new slot FULL; appointments table “Cancelled / Superseded” |
| No-capacity escalation | PASS | Live Playwright on `SHP-DEMO-NOCAP`: escalation card, no proposal, no confirmation summary |
| UI | PASS | Driver console + appointments + timeline; Playwright 9/9 including four viewports |
| Timeline | PASS | Persisted steps via `completedTimelineSteps`; Playwright confirmed “Appointment confirmed” / reschedule “New appointment confirmed” |
| Appointments table | PASS | Columns: shipment number, driver, facility, local time, status; UUID secondary |
| Timezone | PASS | Phase 4 / NOCAP bound to `CHI-XD` `America/Chicago`; formatter + Playwright reject `00:30 UTC` labels. Extra unused Chicago rows still stored as `UTC` (limitation) |
| Test isolation | PASS | `tests/db.py` refuses `setuhaul`; pytest 557/0/0 used `setuhaul_test`; live `setuhaul` not dropped |
| Automated tests | PASS | Backend 557 passed / 0 failed / 0 skipped; Vitest 35 passed; Playwright 9 passed |
| Documentation | PASS | README + `docs/` cover problem, architecture, SHOW/PROPOSE/CONFIRM, capacity, concurrency, escalation, isolation. README test counts corrected in this audit |

## Core invariants

| ID | Invariant | Status |
|----|-----------|--------|
| 1 | Showing an option does not consume capacity | PASS |
| 2 | Creating a proposal does not consume capacity | PASS |
| 3 | Only confirmed/held appointments consume capacity | PASS |
| 4 | Capacity-1 slots cannot contain two consuming appointments | PASS |
| 5 | Confirmation occurs only after explicit confirmation | PASS |
| 6 | Confirmation revalidates current feasibility/capacity | PASS |
| 7 | A stale proposal cannot silently move to another slot | PASS |
| 8 | Concurrent confirmation: one success, one stale/conflict | PASS |
| 9 | Sequential retry after successful confirmation is idempotent | PASS |
| 10 | Rescheduling preserves the original appointment as history | PASS |
| 11 | A rescheduled shipment has exactly one current confirmed appointment | PASS |
| 12 | No feasible option results in escalation rather than an invented slot | PASS |
| 13 | Backend state is authoritative over conversational wording | PASS |
| 14 | UI cannot show confirmed before backend confirmation persists | PASS |

## Frozen phases

| Phase | Status |
|-------|--------|
| 1 Operational semantics | PASS / FROZEN (not reopened) |
| 2 Booking engine | PASS / FROZEN (not reopened) |
| 3 Classroom / demo scenario | PASS / FROZEN (not reopened) |
| 4 UI + live E2E | PASS (Playwright 9/9 against live API `127.0.0.1:8010` and UI `127.0.0.1:5173`) |
| 5 Final audit | PASS |
