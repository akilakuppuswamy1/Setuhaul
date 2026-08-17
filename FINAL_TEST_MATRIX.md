# FINAL TEST MATRIX

Phase 5 evidence. No application behavior was changed to obtain these results.

## Automated backend (`python -m pytest tests`)

| Metric | Result |
|--------|--------|
| Passed | 557 |
| Failed | 0 |
| Skipped | 0 |
| Warnings | 1 (`StarletteDeprecationWarning` from FastAPI TestClient / httpx) |
| Duration | 63.19s |
| Database | `setuhaul_test` for destructive PostgreSQL tests |

## PostgreSQL / concurrency subset

Files: `test_db_isolation.py`, `test_migration.py`, `test_step6_concurrency.py`, `test_step7_concurrency.py`, `test_step7_phase2_booking_engine.py`, `test_step7_reschedule.py`, `test_step6_hardening.py`, `test_step7_hardening.py`

| Metric | Result |
|--------|--------|
| Passed | 88 |
| Failed | 0 |
| Skipped | 0 |
| Duration | 23.96s |

Full suite skipped count was also 0, so remaining PostgreSQL-gated tests in Step 4/5/8/9 also ran.

Verified in those tests: one winner, one loser/conflict, one confirmed appointment, capacity consumed once; `DROP SCHEMA` refused on `setuhaul`.

## Frontend unit (`npm test` in `frontend/`)

| Metric | Result |
|--------|--------|
| Passed | 35 |
| Failed | 0 |
| Files | 7 (timeline, appointments, client, format, conversationThread, AppointmentsPage, DriverConsolePage) |
| Duration | 2.94s |

## Frontend build (`npm run build`)

PASS (Vite production build, TypeScript `--noEmit`).

## Live Playwright (`npx playwright test`, 16 August 2026)

Against live API `http://127.0.0.1:8010` and UI `http://127.0.0.1:5173`.

| Test | Result | Notes |
|------|--------|-------|
| Health | PASS | `{"status":"ok","service":"setuhaul"}` |
| Viewport 1366×768 | PASS | No horizontal overflow; composer reachable |
| Viewport 1440×900 | PASS | Same |
| Viewport 768×1024 | PASS | Mobile menu used |
| Viewport 390×844 | PASS | Same |
| Shipment switching RACE → RESCHEDULE | PASS | Driver/facility/thread switch; prior message gone |
| No-capacity `SHP-DEMO-NOCAP` | PASS | Escalation visible; no proposal card; no confirmation summary |
| Reschedule `SHP-PHASE4-RESCHEDULE-001` | PASS | Fixture already rescheduled; browser verified history + appointments table |
| Race `SHP-PHASE4-RACE-001` | PASS | Fixture already confirmed; browser verified confirmation card, timeline, appointments, slot FULL. **Two-request 200/409 race not re-driven** |

## Assignment traceability

| Assignment requirement | Implementation | Automated test | Live demo | Status |
|------------------------|----------------|----------------|-----------|--------|
| 1. Driver reports exception | Step 4 + Step 8 delay/ETA language | `test_step4_*`, `test_step8_*` | Consumed Phase 4 race conversation history; NOCAP live this audit | PASS |
| 2. System understands operational situation | Deterministic parser + optional OpenRouter adapter; tools allowlisted | `test_step8_p1_routing.py`, paraphrase matrix | Conversation intents in UI | PASS |
| 3. Driver bound to correct shipment | Thread create binds driver/shipment; UI selector | Step 8 binding tests | Playwright switching | PASS |
| 4. Original appointment identified | Context + original slot panel | Step 8 / reschedule tests | Reschedule original still in DB | PASS |
| 5. ETA updated appropriately | `record_eta_update` / ETA API | Step 4 tests | Live ETA rows present | PASS |
| 6. Original appointment feasibility evaluated | Step 5 on original + options | `test_step5_*` | Implied by options/escalation | PASS |
| 7. Feasible alternatives shown | `get_available_options` | Step 5/8 tests | Not re-shown on consumed race; NOCAP shows none | PASS |
| 8. Showing options does not consume capacity | EVALUATE tool; no allocate | Booking-engine tests | Live over-capacity query empty | PASS |
| 9. Driver can choose an option | `create_proposal` from option | Step 7/8 tests | Not re-driven (consumed) | PASS |
| 10. Proposal is created | `requested` + `STEP7_PROPOSAL` | `test_step7_proposals.py` | Cancelled proposal rows remain | PASS |
| 11. Proposal distinct from confirmation | Proposed vs confirmed statuses | Step 7 tests | Confirmation card absent until confirmed | PASS |
| 12. Driver explicitly confirms | `accept_proposal` only | Step 8 hardening | Not re-driven; card after persist | PASS |
| 13. Confirmation revalidates current state | Accept → Step 5 → Step 6 | Step 7 accept tests | Code path unchanged | PASS |
| 14. Allocation occurs atomically | Locks shipment → slot → dock | `test_step6_concurrency.py` | Not re-driven live | PASS |
| 15. Exactly one capacity unit consumed | Capacity re-check | Concurrency tests | Race/book slots FULL, consuming=1 | PASS |
| 16. Appointment becomes confirmed | Separate confirmed row | Step 7 tests | Live confirmed rows exist | PASS |
| 17. Double booking prevented | Locks + capacity | Concurrency tests | No over-capacity slots in live DB | PASS |
| 18. Stale proposals rejected | HTTP 409 + stale notes | `test_step7_concurrency.py` | Live loser UI not re-driven | PASS |
| 19. Concurrent confirmation one winner | PostgreSQL race tests | Same | Fixture consumed | PASS |
| 20. No-capacity escalates | `request_human_escalation` | Step 8 tests | Playwright NOCAP | PASS |
| 21. Confirmed reschedule preserves history | `superseded_by=` notes | `test_step7_reschedule.py` | Live original id preserved | PASS |
| 22. UI reflects persisted backend state | Console reads API | Vitest + Playwright | UI = API = DB on consumed fixtures | PASS |

Optional facility-level scheduling (assignment §7.3) is implemented read-only as Step 9. **OUT OF SCOPE** as a booking path.

## Live database safety (read-only)

| Item | Value |
|------|-------|
| Connected database | `setuhaul` |
| Test database | `setuhaul_test` |
| Table count | 16 domain tables (no `alembic_version` on live) |
| Drivers | 32 |
| Shipments | 35 |
| Facilities | 8 |
| Docks | 17 |
| Slots | 38 |
| Appointments | 49 |
| Proposals | No separate table; proposals are `appointments` with `STEP7_PROPOSAL` |
| Mutations this audit | Playwright NOCAP sent “What options do I have?”; shipment-switch sent a check-in on the race shipment. No `DROP`, no fixture reset |

## Thread recovery

LIVE 404 NOT EXERCISED (would require deleting a live thread). Unit tests in `frontend/src/lib/conversationThread.test.ts` cover: create-then-send, valid thread, 404 discard + one retry, no infinite retry, no duplicated user payload, 409 does not recreate.

## Assignment demo script (do not improvise)

Use a **clean unused** fixture for a presentation confirm/race. Current `SHP-PHASE4-RACE-001` / `BOOK-001` / `RESCHEDULE-001` are **already consumed**.

If presenting against consumed fixtures, show **result state** (confirmation card, appointments, timeline, history) rather than re-confirming.

Preferred unused sequence when a clean fixture exists:

1. Driver reports delay.
2. ETA updated; original appointment evaluated.
3. Driver asks for options.
4. Feasible options shown (showing ≠ booking).
5. Driver chooses.
6. Proposal created (slot still available).
7. “Has it been confirmed?” → read-only.
8. “Confirm it.” → revalidate + allocate.
9. Show confirmation card, shipment panel, appointments table, timeline.
10. Concurrent confirmation: one HTTP 200, one HTTP 409 stale.
11. Reschedule: old cancelled/superseded, new confirmed, history kept.
12. `SHP-DEMO-NOCAP`: zero options → human escalation.

## Presentation talk track (actual implementation)

**Q1. What problem does SetuHaul solve?**  
Drivers miss warehouse appointments. The hard part is many drivers competing for scarce receiving slots without double-booking.

**Q2. Why is the LLM not the authority for booking?**  
The LLM understands language and selects allowlisted tools. Feasibility, capacity, proposal state, and confirmation are deterministic Python services. OpenRouter cannot independently authorize `accept_proposal`.

**Q3. What is SHOW vs PROPOSE vs CONFIRM?**  
SHOW lists Step 5-feasible slots and writes no consuming capacity. PROPOSE creates an `Appointment` in `requested` (API `proposed`). CONFIRM is explicit accept: revalidate then Step 6 allocate.

**Q4. When is capacity consumed?**  
Only `confirmed` and `held` appointments. Requested proposals do not occupy the slot.

**Q5. What happens when two drivers compete for one slot?**  
Both may see remaining capacity. Inside one transaction with locks, one confirm commits; the other gets HTTP 409 stale/conflict. No silent retry.

**Q6. How is double booking prevented?**  
Lock order shipment → slot → dock, Step 5 revalidation, capacity re-check of confirmed+held vs slot capacity, then commit.

**Q7. What happens to a stale proposal?**  
Accept fails; proposal is marked stale; UI shows conflict, not “appointment confirmed.” It does not move to another slot.

**Q8. What happens when there is no feasible slot?**  
Options list is empty; the system escalates to a human. It does not invent a slot.

**Q9. How does rescheduling preserve history?**  
The original confirmed row is cancelled and annotated `superseded_by=<new id>`. It remains queryable. The new row is the current confirmed appointment.

**Q10. What happens if chat and database disagree?**  
PostgreSQL is the system of record. The UI shows confirmed only from persisted appointment/proposal status.

**Q11. What is the allocation policy?**  
Classroom policy: first successful confirm after revalidation wins the remaining capacity unit. Step 9 can rank a facility snapshot but does not book. There is no OR-Tools optimizer.

**Q12. What are the current limitations?**  
See `KNOWN_LIMITATIONS.md`. Classroom auth, no SMS, no GPS, no OR-Tools, proposal TTL is application-side, live demo DB is not Alembic-stamped, Phase 4 live fixtures are consumed.
