# KNOWN LIMITATIONS

Phase 5. These are not hidden test failures. They are boundaries of the classroom implementation or leftover demo-database state.

## 1. Assignment-required limitation (accepted by the brief)

The FDE brief does **not** prescribe a framework, storage design, or allocation algorithm. It does require trustworthy feasibility, freshness, capacity, concurrent requests, and confirmation. Those are implemented.

The brief also requires no-feasible-slot **escalation rather than inventing an answer**. Escalation is a record/flag in conversation metadata, not a dispatcher SLA inbox. That matches the classroom scope.

The brief does **not** require live GPS. ETA is declared, not tracked.

## 2. Optional / non-scored limitation (do not score as assignment failure)

- Classroom authentication: no login, JWT, or verified driver session. Driver identity is a request field.
- No email / SMS / push notifications.
- No OR-Tools / MIP scheduler. Step 9 is a deterministic read-only ranking.
- No Redis/Kafka event bus.
- No LangChain / LangGraph.
- No separate `Proposal` table (proposals reuse `appointments`).
- No `expires_at` column; proposal TTL is 30 minutes from `created_at` in application code.
- `AppointmentStatus.HELD` exists; hold-with-expiry as its own column is not implemented.
- Option `dock_id` may be null until allocation assigns a dock. Live `SHP-PHASE4-RACE-001` confirmed appointment has **no dock_id**; the **slot** is FULL (capacity consumed). `SHP-PHASE4-BOOK-001` did occupy a dock.
- Vehicle length vs dock `max_length_m` is not evaluable (no vehicle length on the frozen schema).
- Conversation does not perform gate check-in.
- Direct `POST /shipments/{id}/allocate` exists for structured clients; the driver conversation uses proposal accept, not allocate.
- Two-row confirm: the proposal row is cancelled; Step 6 writes a separate confirmed appointment.
- Duplicate leftover facilities named “Chicago Cross-Dock” with timezone `UTC` exist from earlier seeds. Phase 4 / NOCAP shipments use `CHI-XD` / `America/Chicago`.
- Live demo database `setuhaul` has the 16 domain tables but **no** `alembic_version` row. Schema matches the frozen Step 2 set. Alembic heads in-repo are a single chain. Pytest migrations run only on `setuhaul_test`. Do not stamp or migrate live as part of this audit.
- README previously cited 399 backend / 5 frontend tests; Phase 5 measured **557 / 35**. Counts in README were corrected during this audit.
- Concurrency sequence PNG may still be missing from `docs/` (markdown/Mermaid is present).
- Local `.env` is gitignored. It currently contains a non-empty `LLM_API_KEY` and `LLM_PROVIDER` is not `fake`. That is a local machine choice. **Do not commit `.env`.** `.env.example` keeps `LLM_PROVIDER=fake` and an empty key.
- `TEST_DATABASE_URL` is absent from local `.env`; pytest used the application default (`setuhaul_test`) and isolation tests passed.

## 3. Future production enhancement (out of scope)

- Production identity provider.
- Notification platform and warehouse confirmation messaging.
- Human-task SLA / dispatcher work queue.
- National routing, live travel time, GPS.
- `POST /schedule/confirm`.
- Facility-wide MIP optimization.
- OpenRouter (or any second provider) as booking authority — must never become that.

## 4. Phase 4 live fixture state (presentation constraint)

These fixtures are **already consumed**. Do not reuse them for a fresh SHOW → PROPOSE → CONFIRM or a live 200/409 race:

- `SHP-PHASE4-BOOK-001` — confirmed; slot FULL; dock occupied.
- `SHP-PHASE4-RACE-001` — confirmed; slot FULL.
- `SHP-PHASE4-RESCHEDULE-001` — original cancelled with `superseded_by=`; new confirmed.

`SHP-DEMO-NOCAP` remains valid for escalation (no proposal rows).

To re-demo booking/concurrency, insert **new** unused fixtures. Do **not** `docker compose down -v` or drop `setuhaul` unless the user explicitly chooses a destructive reset.

## 5. Uncommitted semantic / paraphrase work

Files from a later semantic/paraphrase run (reported 557 passed / 0 failed) are **OPTIONAL** relative to frozen Phase 1/2 acceptance:

- `app/ai/conversation/semantics.py` (untracked)
- modified conversation modules (`agent.py`, `clocks.py`, `intents.py`, `models.py`, `formatter.py`, `context.py`, `provider.py`, `prompts.py`, …)
- `tests/test_step8_paraphrase_matrix.py`

They are **not REQUIRED** to reopen Phase 1/2. They are **not** a submission blocker. The user decides whether to include them in the commit. Do not revert or expand them in Phase 5.
