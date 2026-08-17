# SETUHAUL

## Deterministic Warehouse Appointment Coordination with Conversational AI

SetuHaul uses AI for language understanding and conversation orchestration, while deterministic Python services remain authoritative for feasibility, capacity, proposal state, concurrency-safe allocation, and confirmation.

---

## 1. Executive Summary

Inbound warehouses have **scarce appointment capacity**: limited operating hours, docks, and slot counts. Drivers arrive late, request a new window, or compete for the same remaining capacity. Naive “book the slot I asked for” is unsafe: two concurrent confirmations can both appear feasible, then double-book.

SetuHaul coordinates inbound shipments at a constrained receiving facility by:

1. Recording operational facts (ETA, driver exceptions).
2. Evaluating **feasibility** with explicit rules (Step 5).
3. Creating a **proposal** that does not consume capacity (Step 7).
4. Confirming only after **revalidation + transactional allocation** (Step 7 → Step 5 → Step 6).
5. Exposing that path through a **driver conversation** (Step 8) and a React operations console.
6. Optionally ranking several trucks against one facility snapshot (Step 9, read-only).

**Architectural principle:** LLM for language; deterministic Python rules for operational decisions.

The LLM is not an autonomous booking agent. It cannot independently decide feasibility, lock docks, or confirm appointments.

---

## 2. Assignment Context

The SetuHaul FDE challenge asks for a warehouse appointment coordinator that can talk to a **late or disrupted inbound driver**, show feasible options under **scarce capacity**, and commit a booking only through a **controlled proposal** that remains correct under **concurrency**.

| Assignment theme | How this repository treats it |
|------------------|-------------------------------|
| Driver conversation | Step 8 over frozen `ChatThread` / `ChatMessage` |
| Scarce appointment capacity | Slot `capacity`, dock availability, facility rules |
| Feasibility | Step 5 `FeasibilityEngine` (pure rules) |
| Controlled proposals | Step 7 `Appointment` rows with `status=requested` |
| Concurrency | Step 6 `AllocationService` row locks + capacity re-check |
| Optional facility-level scheduling | Step 9 read-only ranking |

**Required classroom problem:** driver conversation + concurrent scarce capacity. Steps 5–8 are that path.

**Optional extension:** Step 9. It proposes a ranked facility schedule. It does **not** book, lock, reserve, or confirm capacity. There is no Step 9 confirmation endpoint.

LangChain, LangGraph, Redis, Kafka, and OR-Tools are **not** used.

---

## 3. Problem Statement

A receiving facility cannot safely treat a chat message as a booking.

Examples:

- A driver running two hours late (original 6:30 PM window, new ETA 8:30 PM).
- The same driver must **leave by 9:30 PM**, so later slots are operationally useless.
- Docks and slots have finite capacity; several trucks may be eligible for the last remaining window.
- A **proposal** shown earlier may be **stale** by the time the driver says “confirm.”
- Two clients can both see remaining capacity, then confirm at the same time.

Naive booking is unsafe because:

- Showing an option is not the same as holding capacity.
- Feasibility at display time is not feasibility at commit time.
- Without transactional locks and a capacity re-check, two `confirmed` appointments can consume the same slot.

---

## 4. Solution Overview

### Required path (driver → confirmed appointment)

```mermaid
flowchart LR
  D[Driver] --> UI[React Operations Console]
  UI --> API[FastAPI]
  API --> S8[Step 8 Conversation Layer]
  S8 --> S5a[Step 5 Feasibility]
  S8 --> S7[Step 7 Proposal]
  S7 --> S5b[Step 5 Revalidation]
  S5b --> S6[Step 6 AllocationService]
  S6 --> A[Confirmed Appointment]
```

Explicit confirmation follows **Step 7 → Step 5 revalidation → Step 6 allocation**.

### Optional path (Step 9 — no booking)

```mermaid
flowchart LR
  F[Facility snapshot] --> SS[SchedulingService]
  SS --> S5[Step 5 Feasibility]
  S5 --> SE[SchedulingEngine]
  SE --> P[Proposed / ranked schedule]
  P --> X[NO booking]
```

Step 9 is a read-only facility-level ranking engine. It proposes a schedule but never books, locks, reserves, or confirms capacity.

---

## 5. Core Design Principle — AI Boundary

SetuHaul uses AI for language understanding and conversation orchestration, while deterministic Python services remain authoritative for feasibility, capacity, proposal state, concurrency-safe allocation, and confirmation.

### What AI does

- Understand driver language (intent, times, option ordinals).
- Classify intent and extract conversational constraints (ETA, leave-by, earliest start).
- Maintain conversation context from `ChatMessage.metadata` JSON plus thread foreign keys.
- Choose **allowlisted** tools only.
- Explain deterministic backend results in driver-facing text.
- Request human escalation as a **record/flag**.

### What AI does not do

- Decide feasibility.
- Calculate capacity authority.
- Choose or lock docks as a commit.
- Allocate appointments.
- Bypass concurrency controls.
- Confirm bookings independently.
- Execute arbitrary functions or SQL.
- Override Step 5 / 6 / 7 rules.

Privileged confirmation is only:

**Step 8 `accept_proposal` → Step 7 accept → Step 5 revalidation → Step 6 allocation.**

| Provider | Role |
|----------|------|
| `FakeLLMProvider` | **Default.** Deterministic parser (`app/ai/conversation/intents.py`). No network. |
| `OpenRouterProvider` | Optional language adapter. Cannot independently authorize confirmation. Write intents that the parser did not also see are rejected. `confirm` / `reject` flags come from the parser, not the model payload. |

LangChain and LangGraph are not used.

---

## 6. System Architecture

### Frontend

React 19 + Vite + TypeScript + React Router.

| Route | Page |
|-------|------|
| `/` | Driver Console |
| `/shipments` | Shipments |
| `/appointments` | Appointments |
| `/facility-schedule` | Facility Schedule (Step 9) |
| `/demo` | Demo Scenarios |
| `/concurrency` | Concurrency explanation (does not fire two live confirms) |

The UI displays API results. It does not duplicate feasibility or allocation logic.

### API

FastAPI (`app/main.py`), CORS from `CORS_ORIGINS`, routers in `app/api/`.

Health: `GET /health` → `{"status":"ok","service":"setuhaul"}`.

### Services

Orchestration and persistence (facts from repositories; no invented operational measurements):

| Service | Role |
|---------|------|
| `ConversationService` | Threads, messages, agent orchestration |
| `ETAUpdateService` / `DriverExceptionService` | Step 4 writes |
| `FeasibilityService` | Load facts, call `FeasibilityEngine` |
| `ProposalService` | Step 7 lifecycle; accept wraps revalidation + allocation |
| `AllocationService` | Transaction, row locks, capacity re-check, commit |
| `SchedulingService` | Load facility snapshot, call `SchedulingEngine` |
| Catalog services | Carriers, drivers, vehicles, shipments, facilities, docks, slots, appointments, check-ins, contacts, operational messages |

### Engines

| Component | Kind | Authority |
|-----------|------|-----------|
| `FeasibilityEngine` | Pure deterministic rules | Eligibility. No database. No writes. |
| `SchedulingEngine` | Pure deterministic ranking | Proposed order only. No writes. |
| `AllocationService` | Transactional service | **Not** a separate `AllocationEngine`. Owns locks, re-check, and commit. |

### Persistence

PostgreSQL 16, SQLAlchemy 2, Alembic. **16-table frozen Step 2 schema.** Steps 3–9 add no tables.

---

## 7. Step-by-Step Implementation

| Step | Capability | Status |
|------|------------|--------|
| 1 | Foundation (FastAPI, config, health) | Implemented |
| 2 | Frozen system of record (16 tables) | Implemented |
| 2H | Indexes and constraints | Implemented |
| 3 | Read-only business APIs | Implemented |
| 4 | ETA updates and driver exceptions | Implemented |
| 5 | Deterministic feasibility | Implemented |
| 6 | Concurrency-safe allocation | Implemented |
| 6H | Allocation hardening | Implemented |
| 7 | Controlled proposals | Implemented |
| 8 | Conversational AI | Implemented |
| 8H | Adversarial / confirmation hardening | Implemented |
| 9 | Optional read-only facility ranking | Implemented |

### Step 1 — Foundation

**Purpose.** Runnable API with configuration and health.

**Implementation.** `app/main.py`, `app/core/config.py`, `app/core/database.py`, `GET /health`.

**Design decision.** Health includes `"service":"setuhaul"` so the console can reject a different process on port 8000.

**Evidence.** `tests/test_health.py`. Live: `GET http://127.0.0.1:8010/health`.

**Boundary.** No domain writes yet.

### Step 2 — Frozen system of record

**Purpose.** PostgreSQL is the system of record for operational facts.

**Implementation.** 16 SQLAlchemy tables, UUID primary keys, `created_at` on every table (`TimestampMixin` also has `updated_at` on mutable entities). Alembic revisions:

- `888176505d00_create_step_2_domain_tables.py`
- `102c692c1be2_step2_hardening_indexes_and_constraints.py`

**Design decision.** Freeze the schema. Later steps reuse `Appointment` and `ChatMessage.metadata` instead of new tables.

**Evidence.** `tests/test_models.py`, `tests/test_models_hardening.py`, `tests/test_migration.py` (`EXPECTED_DOMAIN_TABLES` has 16 names).

**Boundary.** Step 3 exposes these rows; it does not add decision logic.

### Step 3 — Business APIs

**Purpose.** Read-only operational facts with pagination (`page`, `page_size`, max 100).

**Implementation.** FastAPI → Pydantic → service → repository → PostgreSQL.

**Design decision.** Collection endpoints retrieve history; they do not recommend slots or allocate.

**Evidence.** `tests/test_api.py`.

**Boundary.** Writes for ETA/exceptions begin in Step 4.

### Step 4 — ETA and driver exceptions

**Purpose.** Immutable ETA history; latest ETA is derived, never stored on `Shipment`. Driver exceptions are operational blockers when `open` or `acknowledged`.

**Implementation.** `POST /shipments/{id}/eta-updates`, `GET /shipments/{id}/latest-eta`, `POST /shipments/{id}/exceptions`, `PATCH /driver-exceptions/{id}`.

**Design decision.** Driver-reported delay is a fact, not a booking.

**Evidence.** `tests/test_step4_operations.py`, `tests/test_step4_hardening.py`.

**Boundary.** Step 5 reads latest ETA and active exceptions.

### Step 5 — Deterministic feasibility

**Purpose.** Answer whether a shipment/slot/dock combination can be accepted under persisted facts.

**Implementation.** `POST /shipments/{id}/feasibility` → `FeasibilityService` → `FeasibilityEngine`. Outcomes: `feasible`, `not_feasible`, `not_evaluable`. Ordered `rule_results`.

Rules actually implemented (`app/engines/feasibility/rules.py`):

| Rule ID | What it checks |
|---------|----------------|
| SHIP-001–003 | Shipment active, not terminal, destination facility assigned |
| CARR-001 / DRIV-001 / VEHI-001 | Carrier, driver, vehicle active |
| VEHI-002 / 003 | Vehicle weight/volume when data present |
| FACI-001 | Destination facility active |
| APPT-001 / 002 | Appointment or slot context; facility alignment |
| SLOT-001–004 | Slot exists, facility match, status open, capacity remaining |
| DOCK-001–005 | Dock presence, facility, availability, weight, reefer compatibility |
| RULE-001–003 | `max_daily_appointments`, operating hours, dock compatibility (vehicle type / pallet limits) |
| ETA-001 / 002 | Latest ETA in slot window (blocking); outside hours (warning) |
| EXCP-001 | No `open` or `acknowledged` driver exceptions |

Capacity-consuming appointment statuses: `confirmed`, `held` only. `requested` proposals do not consume capacity.

**Design decision.** Pure engine: no SQL, no LLM. Missing facts yield `not_evaluable`, not invented travel times.

**Evidence.** `tests/test_step5_feasibility.py`, `tests/test_step5_hardening.py`, `tests/test_step5_adversarial.py`.

**Boundary.** Step 6 must re-run Step 5 inside the lock. Step 6 is not a second feasibility engine.

### Step 6 — Concurrency-safe allocation

**Purpose.** Commit a slot/dock without double-booking.

**Implementation.** `POST /shipments/{id}/allocate` → `AllocationService.allocate`.

Lock order (`ALLOCATION_LOCK_ORDER`): **shipment → slot → dock**.

Inside one transaction:

1. Advisory / row locks.
2. Step 5 revalidation.
3. Capacity re-check (`confirmed` + `held` vs slot `capacity`).
4. Write `confirmed` (or `held` if requested) appointment.
5. Commit (`safe_commit`).

**Design decision.** Allocation is a **service with locks**, not a second pure engine. Concurrent confirmation cannot both commit the last unit of capacity.

**Evidence.** `tests/test_step6_allocation.py`, `tests/test_step6_hardening.py`, `tests/test_step6_concurrency.py` (PostgreSQL).

**Boundary.** Conversation never calls allocate directly. Confirmation uses Step 7 accept.

### Step 7 — Proposal workflow

**Purpose.** Distinguish **show** vs **propose** vs **confirm**.

```
Show (options) → Propose (Appointment requested) → Confirm (Step 5 + Step 6)
```

There is **no** `Proposal` table. Proposals are `Appointment` rows with `status=requested` and a `STEP7_PROPOSAL` marker in `notes`.

| API status | Persisted as | Meaning |
|------------|--------------|---------|
| `proposed` | `requested` | Active; capacity not consumed |
| `rejected` | `rejected` | Driver/ops rejected |
| `expired` | `expired` | Application TTL: `created_at + 30 minutes` (no `expires_at` column) |
| `stale` | `cancelled` + reason | Revalidation failed at accept |
| `confirmed` | Separate `confirmed` appointment via Step 6 | Capacity committed |

Accept: shipment advisory lock → Step 5 → Step 6 → HTTP 409 + `stale` if capacity/feasibility changed. No `PATCH /proposals/{id}` status mutation. No silent retry.

**Evidence.** `tests/test_step7_proposals.py`, `tests/test_step7_hardening.py`, `tests/test_step7_concurrency.py`.

**Boundary.** Step 8 tools call `ProposalService`; they do not replace it.

### Step 8 — Conversational AI

**Purpose.** Driver free text → allowlisted tools → existing services.

**Implementation.** `POST /conversations`, `POST /conversations/{thread_id}/messages`. Agent in `app/ai/conversation/`. Context reconstructed from `ChatMessage.metadata` plus `ChatThread` FKs.

Hardening actually present:

- Allowlisted tools; `ToolArguments` `extra="forbid"`; UUID validation.
- Deterministic parser (`FakeLLMProvider` default).
- Injection markers skip irreversible tools.
- Status questions (`Has it been confirmed?`) classify as `ASK_STATUS` and call `get_proposal` / `get_shipment_status` only.
- Leave-by stored in conversation context and applied when listing/selecting options.
- OpenRouter cannot independently authorize privileged confirmation.
- API errors sanitized; secrets stripped from public metadata.

**Evidence.** `tests/test_step8_conversation.py`, `tests/test_step8_hardening.py`, `tests/test_step8_p1_routing.py`, `tests/test_step8_chat_constraints.py`, live `scripts/e2e_hero_flow.py`.

**Boundary.** Step 9 tool is optional and read-only.

### Step 9 — Optional facility scheduling

**Purpose.** Rank eligible shipments against open slots at **one** facility.

**Implementation.** `POST /facilities/{facility_id}/schedule/evaluate` → `SchedulingService` → Step 5 eligibility → `SchedulingEngine`.

Response includes `read_only: true`, `commits_capacity: false`, `proposed_assignments`, and `unassigned_shipments` when applicable.

**Design decision.** No OR-Tools. No confirmation endpoint. Recalculation = call again after operational state changes.

**Evidence.** `tests/test_step9_scheduling.py`.

**Boundary.** A recommended slot still confirms through Step 7 → 5 → 6.

---

## 8. Conversation Tool Registry

Allowlisted names (`app/ai/conversation/tools.py`). Unknown names are rejected. There is no `eval`, `exec`, or SQL from the model.

Classes: **READ**, **EVALUATE**, **FACT WRITE**, **PROPOSAL WRITE**, **CAPACITY COMMIT**, **ESCALATION FLAG**.

| Tool | Class | Backend | Database effect |
|------|-------|---------|-----------------|
| `get_shipment_status` | READ | `ShipmentService` + latest ETA | None |
| `record_eta_update` | FACT WRITE | `ETAUpdateService` | Insert `eta_updates` |
| `create_driver_exception` | FACT WRITE | `DriverExceptionService` | Insert `driver_exceptions` |
| `evaluate_feasibility` | EVALUATE | `FeasibilityService` | None |
| `get_available_options` | EVALUATE | Open slots + Step 5 | None |
| `create_proposal` | PROPOSAL WRITE | `ProposalService.create` | `appointments` `requested` |
| `get_proposal` | READ | `ProposalService.get` | None |
| `accept_proposal` | **CAPACITY COMMIT** | `ProposalService.accept` → Step 5 → Step 6 | Confirmed appointment |
| `reject_proposal` | PROPOSAL WRITE | `ProposalService.reject` | Proposal row rejected |
| `request_human_escalation` | ESCALATION FLAG | Metadata + `[ESCALATED]` subject | Thread subject / message metadata |
| `evaluate_facility_schedule` | EVALUATE | `SchedulingService` | None |

Only **`accept_proposal`** reaches the controlled confirmation path. There is no conversation tool named `allocate`.

`get_available_options` builds `PresentedOption` with `slot_id` and times. **`dock_id` may be null** until a proposal/allocation assigns a dock.

---

## 9. Driver Conversation Example

Verified live hero flow (`scripts/e2e_hero_flow.py`) against shipment **SH-1024**.

### Turn 1

**Driver:** `I'll be two hours late. I was supposed to reach by 6:30 PM, but I'll reach around 8:30 PM.`

| | |
|--|--|
| Intent | `UPDATE_ETA` (or `REPORT_DELAY`) |
| Tool | `record_eta_update` |
| Authority | Step 4 fact write. Not feasibility. Not booking. |
| Database | New `eta_updates` row. Latest ETA derived from history. |

### Turn 2

**Driver:** `I also have an emergency and need to leave by 9:30 PM.`

| | |
|--|--|
| Intent | `CLARIFICATION_REQUIRED` (leave-by stored; not treated as a blocking exception type) |
| Tool | None required |
| Authority | Conversation context only (`leave_by_local` in metadata) |
| Database | No proposal, no accept, no exception required for this phrasing |

Assistant keeps the leave-by constraint and asks whether to find options that finish by then.

### Turn 3

**Driver:** `My ETA is 8:30 PM. What options do I have?`

| | |
|--|--|
| Intent | `ASK_OPTIONS` |
| Tool | `get_available_options` |
| Authority | Step 5 feasibility + leave-by filter |
| Database | None. Showing is not proposing. |

### Turn 4

**Driver:** `The second one works, but I need to leave by 9:30 PM.`

| | |
|--|--|
| Intent | `PROPOSE_CHANGE` |
| Tool | `create_proposal` |
| Authority | Step 7 create (feasibility-checked). Leave-by must still fit the selected slot. |
| Database | `appointments` row `requested`. Status API: `proposed`. |

Confirmation has **not** occurred.

### Turn 5

**Driver:** `Has it been confirmed?`

| | |
|--|--|
| Intent | `ASK_STATUS` |
| Tool | `get_proposal` |
| Authority | READ |
| Database | None |

### Turn 6

**Driver:** `Confirm it.`

| | |
|--|--|
| Intent | `ACCEPT_PROPOSAL` |
| Tool | `accept_proposal` |
| Authority | Step 7 → Step 5 revalidation → Step 6 allocation |
| Database | Confirmed appointment; proposal row reconciled |

---

## 10. Concurrency and Safety

Two clients can both see remaining capacity for the same slot.

```
Request A ──┐
            ├── apparent remaining capacity
Request B ──┘
            │
            ▼
    Step 6 transaction
    shipment → slot → dock locks
            │
     ┌──────┴──────┐
     │             │
  Winner        Loser
  confirmed     Step 5 / capacity re-check fails
                HTTP 409 / stale or conflict
                no false success
                no silent retry
```

Stale proposal handling: accept revalidates. If the slot is full, the facility changed, or feasibility fails, the proposal is marked stale. A second conversation after SH-1024 is already confirmed cannot silently confirm again.

Capacity consumers are **`confirmed` and `held` only**. `requested` proposals do not occupy the slot.

---

## 11. Step 9 Scheduling

```
Input (facility_id + optional window / shipment_ids / evaluated_at)
  → facility snapshot (shipments, open slots, docks, check-ins, ETAs)
  → eligible combinations via Step 5
  → deterministic ranking
  → proposed_assignments + unassigned_shipments
```

Step 9 does not allocate capacity.

Ranking / tie-break actually implemented (`app/engines/scheduling/rules.py`):

1. Confirmed or held appointments are **protected** and are not moved.
2. Remaining feasible shipments: earlier facility check-in first, then en-route shipments.
3. Lower ETA lateness versus slot end (missing ETA is not fabricated; those rank after known ETAs).
4. Lower early-wait (ETA before slot start).
5. Closer ETA-to-slot-start alignment.
6. Earlier slot start, dock name, `shipment_id`, `slot_id`.

Numeric `score` is 0–100 from evaluable ETA metrics. `score` is `null` when ETA is missing. Frozen schema has **no** shipment `priority` and **no** `expected_unload_minutes`; those are not scored.

Bounds: evaluation is capped (50 shipments, 100 slots in the service). No `POST /schedule/confirm`.

---

## 12. Frontend

`frontend/` is a Vite + React 19 + TypeScript operations console. Tests: Vitest.

| Concern | Behavior |
|---------|----------|
| Conversation | Sends `POST /conversations/{id}/messages`; shows intent, tools, read-only status |
| ETA / options / proposals | Displays API payloads |
| Stale / conflict | Surfaces backend 409 / stale; does not retry as success |
| Escalation | Shows flag; does not claim a human has acted |
| Facility scheduling | Calls evaluate; labels read-only |
| Logic | No local feasibility, capacity, or confirmation engine |

Verified UX details (not a full WCAG audit): `aria-label` / `role="log"` / `aria-live` on the console; `:focus-visible` outlines; responsive layout via `@media` breakpoints and a mobile menu overlay in `global.css`.

Vitest: **35 passed**. Production build: **passed**.

---

## 13. API Reference

Base for the verified demo: `http://127.0.0.1:8010`. OpenAPI: `/docs`, `/redoc`, `/openapi.json`.

### Health

| Method | Path | Purpose | Read/write |
|--------|------|---------|------------|
| GET | `/health` | Liveness; `service=setuhaul` | READ |

### Conversations

| Method | Path | Purpose | Read/write |
|--------|------|---------|------------|
| POST | `/conversations` | Create `ChatThread` for a driver | WRITE (thread) |
| POST | `/conversations/{thread_id}/messages` | Driver turn; may invoke tools | **Can write** via tools |
| GET | `/chat-threads`, `/chat-threads/{id}` | Thread catalog | READ |
| GET | `/chat-messages`, `/chat-messages/{id}` | Message catalog | READ |
| GET | `/contacts`, `/contacts/{id}` | Contacts | READ |

### Shipments, ETA, exceptions

| Method | Path | Purpose | Read/write |
|--------|------|---------|------------|
| GET | `/shipments`, `/shipments/{id}` | Shipment list/detail | READ |
| GET | `/shipments/{id}/eta-updates` | ETA history | READ |
| POST | `/shipments/{id}/eta-updates` | Record ETA | **WRITE** |
| GET | `/shipments/{id}/latest-eta` | Derived latest ETA | READ |
| GET | `/shipments/{id}/exceptions` | Exception history | READ |
| POST | `/shipments/{id}/exceptions` | Report exception | **WRITE** |
| GET | `/shipments/{id}/appointments` | Appointment history | READ |
| GET | `/shipments/{id}/facility-checkins` | Check-in history | READ |
| GET | `/shipments/{id}/chat-threads` | Threads for shipment | READ |

### Feasibility, allocation, proposals

| Method | Path | Purpose | Read/write |
|--------|------|---------|------------|
| POST | `/shipments/{id}/feasibility` | Step 5 evaluate | EVALUATE (no commit) |
| POST | `/shipments/{id}/allocate` | **Direct Step 6 commit** | **CAPACITY COMMIT** |
| POST | `/shipments/{id}/proposals` | Create proposal | **PROPOSAL WRITE** |
| GET | `/proposals/{id}` | Proposal status | READ |
| POST | `/proposals/{id}/accept` | Confirm path | **CAPACITY COMMIT** |
| POST | `/proposals/{id}/reject` | Reject proposal | **WRITE** |

Dangerous write paths: `POST .../allocate` and `POST .../accept`. Conversation uses accept, not allocate.

### Facilities, docks, slots, scheduling

| Method | Path | Purpose | Read/write |
|--------|------|---------|------------|
| GET | `/facilities`, `/facilities/{id}` | Facilities | READ |
| GET | `/facilities/{id}/docks` | Docks | READ |
| GET | `/facilities/{id}/rules` | Facility rules | READ |
| GET | `/facilities/{id}/appointment-slots` | Slots | READ |
| GET | `/facilities/{id}/check-ins` | Check-ins | READ |
| POST | `/facilities/{id}/schedule/evaluate` | Step 9 ranking | EVALUATE (`read_only`) |
| GET | `/docks`, `/docks/{id}` | Dock catalog | READ |
| GET | `/appointment-slots`, `/appointment-slots/{id}` | Slot catalog | READ |
| GET | `/facility-rules`, `/facility-rules/{id}` | Rules catalog | READ |
| GET | `/appointments`, `/appointments/{id}` | Appointments | READ |

No `POST /schedule/confirm`.

### Drivers, vehicles, carriers, operations

| Method | Path | Purpose | Read/write |
|--------|------|---------|------------|
| GET | `/drivers`, `/drivers/{id}` | Drivers | READ |
| GET | `/vehicles`, `/vehicles/{id}` | Vehicles | READ |
| GET | `/carriers`, `/carriers/{id}` | Carriers | READ |
| GET | `/eta-updates`, `/eta-updates/{id}` | Global ETA catalog | READ |
| GET | `/driver-exceptions`, `/driver-exceptions/{id}` | Exceptions | READ |
| PATCH | `/driver-exceptions/{id}` | Acknowledge / resolve | **WRITE** |
| GET | `/facility-checkins`, `/facility-checkins/{id}` | Check-ins | READ |
| GET | `/operational-messages`, `/operational-messages/{id}` | Ops messages | READ |

There is no login, JWT, or session API.

---

## 14. Database / ER Model

Frozen Step 2 schema. **16 tables.** Steps 3–9 added **zero** tables and **zero** new Alembic upgrade operations beyond Step 2 / 2H.

Diagram: [docs/er-diagram.md](docs/er-diagram.md) · [docs/er_diagram.png](docs/er_diagram.png)

| Table | Role |
|-------|------|
| `carriers` | Carrier facts |
| `drivers` | Driver facts |
| `vehicles` | Vehicle facts |
| `contacts` | Contact directory |
| `shipments` | Move identity |
| `eta_updates` | Immutable ETA history |
| `driver_exceptions` | Exception records |
| `facilities` | Receiving/origin facilities |
| `docks` | Dock resources |
| `facility_rules` | Hours, daily max, compatibility JSON |
| `appointment_slots` | Time windows + capacity |
| `appointments` | Proposals **and** bookings |
| `facility_checkins` | Gate / yard / dock presence |
| `chat_threads` | Conversation threads |
| `chat_messages` | Messages; `metadata` JSON for Step 8 context |
| `operational_messages` | Ops outbound messages |

UUID PKs. `created_at` on all tables. Proposals reuse `appointments`. Conversation reuses `chat_threads` / `chat_messages`. Secrets and system prompts are not stored in metadata.

---

## 15. Security and Adversarial Hardening

Verified in code and Step 8H / 9 tests:

| Control | Implementation |
|---------|----------------|
| Allowlisted tools | `ALLOWED_TOOL_NAMES` |
| Strict tool args | Pydantic `extra="forbid"` |
| UUID validation | Tool and path parameters |
| Cross-driver shipment binding | Thread create rejects shipment assigned to another driver; scheduling tool checks actor driver |
| Cross-facility validation | Allocation, proposal, and Step 9 reject mismatched facility/slot/dock |
| Prompt injection | Marker detection; irreversible tools skipped |
| Provider privilege restriction | OpenRouter cannot promote a non-write parser intent to `ACCEPT_PROPOSAL`; `confirm`/`reject` from parser |
| No `eval` / `exec` | Not present in `app/ai` |
| No dynamic SQL from AI | Tools call services only |
| Secrets | `public_metadata` strips `api_key`, `authorization`, prompts |
| Error sanitization | Generic internal errors; no traceback/SQLAlchemy leak in conversation |

**Remaining limitation:** classroom / demo **authentication**. Endpoints do not require login or JWT. The console states “No authentication.” Driver identity is a request field, not a verified session.

---

## 16. Testing

### Backend (verified)

```
557 passed
0 failed
0 skipped
1 warning
```

```bash
pytest -v
```

API and model tests use in-memory SQLite. Migration and concurrency tests require PostgreSQL (`docker compose up -d`).

**Test database boundary:** pytest never uses `DATABASE_URL` for `DROP SCHEMA` / schema reset. Destructive PostgreSQL tests connect to `TEST_DATABASE_URL` (`setuhaul_test` by default). The live demo database `setuhaul` is protected. On first run, pytest creates `setuhaul_test` if it does not exist. Copy `TEST_DATABASE_URL` from `.env.example` into `.env`.

```bash
pytest tests/test_api.py tests/test_health.py tests/test_models.py tests/test_models_hardening.py -v
```

### Frontend (verified)

```
35 passed
```

```bash
cd frontend
npm test
npm run build
```

Build: **PASS**.

### Schema

```bash
alembic check
```

Verified: **no new upgrade operations** after the frozen Step 2 / 2H revisions.

Do not treat this README as inventing additional test names or counts.

---

## 17. Live End-to-End Validation

| Process | Address |
|---------|---------|
| PostgreSQL (`setuhaul-db-1`) | `localhost:5433` (container 5432) |
| SetuHaul API | `127.0.0.1:8010` |
| Frontend | `127.0.0.1:5173` |

```bash
curl http://127.0.0.1:8010/health
# {"status":"ok","service":"setuhaul"}
```

**Port 8000 is another local application and is not used by SetuHaul.** The UI rejects a health payload whose `service` is not `setuhaul`.

### Hero flow

Driver delay → leave-by 9:30 PM → options → second option proposed → “Has it been confirmed?” (read-only) → “Confirm it.” → Step 7 accept → Step 5 → Step 6 → confirmed appointment.

### Conflict path

Second proposal becomes stale or `accept_proposal` fails. Stale/conflict returned. No false success. No silent retry.

### Step 9

`POST /facilities/{facility_id}/schedule/evaluate` returns `read_only: true`, `commits_capacity: false`, proposed assignments, and unassigned shipments where applicable.

---

## 18. Demo Setup

Commands actually used in this repository:

### 1. Start PostgreSQL

```bash
docker compose up -d
```

### 2. Python environment

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 3. Configure environment

```bash
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux
```

`DATABASE_URL` in `.env.example` already points at **localhost:5433**. Leave `LLM_PROVIDER=fake` unless you intentionally enable OpenRouter.

### 4. Migrations

```bash
alembic upgrade head
```

### 5. FastAPI

```bash
uvicorn app.main:app --reload --port 8010 --host 127.0.0.1
```

### 6. Seed demo data

```bash
python scripts/seed_ops_demo.py
```

Creates (or reuses) the classroom dataset on **DATABASE_URL only** (database `setuhaul`). The script prints host/port/database/profile and **aborts** if the target is `postgres`, `template0`, `template1`, or `setuhaul_test`. Frozen schema unchanged. Unique codes skip insert on re-run.

Includes:

- Dallas walkthrough: shipment **SH-1024**, Jane Rivera, original **6:30 PM** appointment (requested), later open slots.
- Chicago Cross-Dock scarce evening capacity: **SHP-DEMO-001–005** (Alex / Priya / Ravi / Maya / Daniel) competing for **3** compatible 8:00 PM windows.
- Reschedule fixture **SHP-DEMO-RESCHEDULE** (confirmed 6:30 PM, open 8:30 PM — seed does not pre-confirm the later slot).
- Concurrency fixture **SHP-DEMO-RACE** (capacity-1 proposal; does not consume capacity; no winner/loser rows).
- No-capacity fixture **SHP-DEMO-NOCAP** (9:15 PM ETA; only containing slot is already confirmed).

`scripts/seed_data.py` is a broader Step 2 domain seed for model validation; it is not the operations-console snapshot.

### 7. Frontend

```bash
cd frontend
copy .env.example .env   # Windows; VITE_API_BASE_URL=http://127.0.0.1:8010
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173).

### 8. Driver walkthrough

Use **Demo Scenarios** or type the messages in [§9](#9-driver-conversation-example). Optional live script (needs a running API and seeded IDs):

```bash
python scripts/e2e_hero_flow.py
```

If 8010 is taken, pick a free port and set both uvicorn `--port` and `VITE_API_BASE_URL`.

---

## 19. Demo Reset

The E2E script **confirms SH-1024**. Re-running `seed_ops_demo.py` does **not** undo that confirmation (unique codes skip insert).

For a clean live confirmation demonstration:

```bash
docker compose down -v
docker compose up -d
alembic upgrade head
python scripts/seed_ops_demo.py
uvicorn app.main:app --reload --port 8010 --host 127.0.0.1
```

Then start the frontend and run the walkthrough **before** `scripts/e2e_hero_flow.py` if you still need a manual confirm.

Do not hand-edit appointment rows in PostgreSQL as a reset procedure.

---

## 20. Security / Environment Variables

Copy from `.env.example` only. **Never commit `.env` or API keys.**

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Live/demo PostgreSQL (`postgresql+psycopg://setuhaul:setuhaul@localhost:5433/setuhaul`) |
| `TEST_DATABASE_URL` | Pytest-only PostgreSQL (`.../setuhaul_test`). Never the demo database. |
| `APP_ENV` | `development` by default |
| `LLM_PROVIDER` | `fake` (safe default) or `openrouter` |
| `LLM_API_KEY` | Required only for OpenRouter; empty → fake fallback |
| `LLM_MODEL` | Default `openai/gpt-4o-mini` (OpenRouter model id) |
| `LLM_BASE_URL` | Default `https://openrouter.ai/api/v1` |
| `CORS_ORIGINS` | Comma-separated; includes `http://127.0.0.1:5173` |

Frontend: `VITE_API_BASE_URL=http://127.0.0.1:8010`.

`LLM_PROVIDER=fake` is the safe default. OpenRouter is optional language understanding only.

---

## 21. Known Limitations

These are design/schema boundaries, not hidden failures of Steps 1–9.

- Classroom driver authentication (no login/JWT).
- No notification platform (email/SMS/push).
- Escalation is a record/flag, not a dispatcher SLA workflow.
- No OR-Tools / MIP scheduler.
- No national routing or live travel-time prediction.
- No event bus (Redis/Kafka).
- No shipment `priority` field; no `expected_unload_minutes`.
- No `expires_at` database column; proposal TTL is application-side (30 minutes from `created_at`).
- `AppointmentStatus.HELD` exists; hold-with-expiry as a column is not implemented.
- Step 9 is read-only; a proposed assignment is not a hold.
- Option `dock_id` may be null before proposal/allocation.
- Direct `POST /shipments/{id}/allocate` exists for structured clients; conversation does not use it.
- Two-row confirm: proposal row is cancelled; Step 6 writes a separate `confirmed` appointment.
- Vehicle length vs dock `max_length_m` is not evaluable (no vehicle length field).
- Facility check-in is a ranking/read fact; the conversation does not check the driver in at the gate.

---

## 22. Out of Scope

Distinct from limitations: **not part of this submission’s architecture**.

- LangChain / LangGraph
- Redis / Kafka
- OR-Tools or a second allocation/feasibility engine
- National fleet routing / optimization
- Production identity provider / JWT authentication
- Notification platform
- Human-task SLA / dispatcher inbox
- `POST /schedule/confirm`
- A separate `Proposal` table

---

## 23. Architecture Diagrams

Final diagrams in `docs/` (PNG + companion markdown). This README does not duplicate the images.

| # | Topic | Files |
|---|--------|-------|
| 1 | System architecture | [architecture.md](docs/architecture.md) · [system_architecture.png](docs/system_architecture.png) |
| 2 | ER diagram | [er-diagram.md](docs/er-diagram.md) · [er_diagram.png](docs/er_diagram.png) |
| 3 | AI responsibility boundary | [ai_responsibility_boundary.md](docs/ai_responsibility_boundary.md) · [ai_responsibility_boundary.png](docs/ai_responsibility_boundary.png) |
| 4 | Driver conversation sequence | [Driver_conversation_sequence.md](docs/Driver_conversation_sequence.md) · [driver_conversation_sequence.png](docs/driver_conversation_sequence.png) |
| 5 | Show → Propose → Confirm | [Show_Propose_Confirm_Sequence.md](docs/Show_Propose_Confirm_Sequence.md) · [Show_Propose_Confirm_Sequence.png](docs/Show_Propose_Confirm_Sequence.png) |
| 6 | Concurrency / locking | [Concurrency_locking_sequence.md](docs/Concurrency_locking_sequence.md) — markdown + Mermaid in-repo; **PNG not present** in `docs/` at README write time |
| 7 | Proposal state | [proposal_state_diagram.md](docs/proposal_state_diagram.md) · [proposal_state_diagram.png](docs/proposal_state_diagram.png) |
| 8 | ETA / exception flow | [eta_exception_flow.md](docs/eta_exception_flow.md) · [eta_exception_flow.png](docs/eta_exception_flow.png) |
| 9 | Step 9 scheduling | [Scheduling_architecture.md](docs/Scheduling_architecture.md) · [Scheduling_architecture.png](docs/Scheduling_architecture.png) |
| 10 | End-to-end driver journey | [end_to_end_driver_journey.md](docs/end_to_end_driver_journey.md) · [end_to_end_driver_journey.png](docs/end_to_end_driver_journey.png) |

---

## 24. Traceability Matrix

Assignment language mapped to this repository (no fabricated requirement IDs).

| Assignment requirement | Implementation | Evidence |
|------------------------|----------------|----------|
| Driver conversation | Step 8 `ConversationService` + allowlisted tools | `POST /conversations/{id}/messages`; `tests/test_step8_*.py`; driver sequence diagram |
| Late driver / ETA | Step 4 `ETAUpdateService` | `POST /shipments/{id}/eta-updates`; ETA flow diagram |
| Feasibility under facility constraints | Step 5 `FeasibilityEngine` | `POST /shipments/{id}/feasibility`; `tests/test_step5_*.py` |
| Show vs propose vs confirm | Step 7 `ProposalService` | `POST /shipments/{id}/proposals`, accept/reject; show/propose/confirm diagram |
| Scarce capacity / no double-book | Step 6 `AllocationService` | `POST /shipments/{id}/allocate`; `tests/test_step6_concurrency.py`; concurrency markdown |
| Controlled confirmation | Step 7 → 5 → 6 | `POST /proposals/{id}/accept`; `accept_proposal` tool; e2e hero flow |
| Concurrency / stale proposals | Locks + revalidation | HTTP 409; `tests/test_step7_concurrency.py`; live conflict path |
| Frozen system of record | Step 2 / 2H | 16 tables; `tests/test_migration.py`; ER diagram |
| Optional multi-truck ranking | Step 9 `SchedulingEngine` | `POST /facilities/{id}/schedule/evaluate`; `tests/test_step9_scheduling.py` |
| Operations console | `frontend/` | Routes in `App.tsx`; 35 Vitest tests; production build |
| Deterministic, testable decisions | Python engines/services | 557 backend tests; FakeLLM default |

---

## 25. Repository Structure

Temporary render/cache paths (`docs/_tmp_*`, `docs/_render_*`, `__pycache__`, `node_modules`, `frontend/dist`, `.env`) are omitted.

```
setuhaul/
├── README.md
├── .env.example
├── .gitignore
├── alembic.ini
├── docker-compose.yml
├── requirements.txt
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 888176505d00_create_step_2_domain_tables.py
│       └── 102c692c1be2_step2_hardening_indexes_and_constraints.py
├── app/
│   ├── main.py
│   ├── ai/conversation/          # Step 8 agent, tools, providers
│   ├── api/                      # FastAPI routers
│   ├── core/                     # config, database, exceptions
│   ├── engines/
│   │   ├── feasibility/          # Step 5 pure rules
│   │   └── scheduling/           # Step 9 pure ranking
│   ├── models/                   # Frozen 16-table schema
│   ├── repositories/
│   ├── schemas/
│   └── services/                 # including allocation.py, proposal.py
├── docs/                         # Architecture markdown + PNG diagrams
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── .env.example
│   └── src/
│       ├── App.tsx
│       ├── pages/
│       ├── api/
│       └── components/layout/
├── scripts/
│   ├── seed_ops_demo.py
│   ├── seed_data.py
│   └── e2e_hero_flow.py
└── tests/
    ├── test_health.py
    ├── test_api.py
    ├── test_models.py
    ├── test_models_hardening.py
    ├── test_migration.py
    ├── test_step4_*.py
    ├── test_step5_*.py
    ├── test_step6_*.py
    ├── test_step7_*.py
    ├── test_step8_*.py
    └── test_step9_scheduling.py
```

---

## 26. Final Acceptance Checklist

| Area | Status |
|------|--------|
| Architecture: LLM language / Python authority | Met |
| Backend FastAPI + PostgreSQL | Met |
| Step 5 feasibility rules | Met |
| Step 6 `AllocationService` locks + re-check | Met |
| Step 7 proposals on `Appointment` (no Proposal table) | Met |
| Step 8 conversation + hardening | Met |
| Step 9 read-only ranking | Met |
| Frontend console (React 19 / Vite) | Met |
| PostgreSQL on 5433; API 8010; UI 5173 | Met (verified demo env) |
| Tests 557 / 0 / 0 + 35 frontend + build | Met (verified counts, Phase 5) |
| Security: allowlist, injection, no AI SQL | Met for classroom scope |
| Auth: production identity | **Not implemented** (documented limitation) |
| E2E hero + conflict + Step 9 evaluate | Met |
| Documentation / diagrams | Met; concurrency PNG missing |
| Git cleanliness | Working tree may still contain assignment artifacts; this README task does not commit |

---

## 27. Final Submission Notes

Typical FDE deliverables for this challenge:

- This GitHub repository (source of truth for implementation).
- This **README** as evaluator-facing technical documentation.
- A written report (PDF) with the architecture diagrams embedded, if the assignment asks for a report.
- A walkthrough / presentation if the course requires one.

This README does not claim a specific LMS upload format beyond what the assignment itself states.

**Core reminder.** SetuHaul uses AI for language understanding and conversation orchestration, while deterministic Python services remain authoritative for feasibility, capacity, proposal state, concurrency-safe allocation, and confirmation. Explicit confirmation follows Step 7 → Step 5 revalidation → Step 6 allocation. Step 9 proposes a schedule and never books it.
