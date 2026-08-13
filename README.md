# SetuHaul

SetuHaul is a deterministic logistics and warehouse appointment coordination system. It helps coordinate inbound shipments at constrained receiving facilities by evaluating operating hours, dock capacity, slot availability, vehicle compatibility, and existing appointments using explicit, testable rules.

## Deterministic Architecture

Operational decisions (slot feasibility, capacity, priority, dock compatibility, appointment allocation, and booking confirmation) are implemented with explicit Python rules—not generative AI or LLM services. Every decision path must be reproducible and testable.

## Project Status

| Step | Description | Status |
|------|-------------|--------|
| 1 | Foundation | Complete |
| 2 | Database Model & System of Record | Complete |
| 2H | Database Hardening | Complete |
| 3 | Business APIs | Complete |
| 4 | ETA + Exception Services | Complete |
| 5 | Deterministic Feasibility Engine | Complete |
| 6 | Deterministic Allocation | Complete |
| 6H | Allocation Hardening | Complete |
| 7 | Controlled Actions & Proposals | Complete |
| 8 | Conversational AI + tool orchestration | Complete |
| 9+ | Notifications / remaining assignment work | Not started |

## Step 8 — Conversational AI

Step 8 adds a driver-facing conversational layer. The LLM (or a deterministic fake parser in tests) is responsible for **language understanding and conversation**. Existing Step 5/6/7 services remain the only authority for feasibility, allocation, and booking confirmation.

```
Driver free text
  → Conversation API
  → Intent / entity / context (app/ai)
  → Clarification if required
  → Allowlisted tools
  → ETA / Exception / Feasibility / Proposal services
  → Structured result
  → Driver-facing explanation
```

The LLM cannot independently decide feasibility, capacity, dock compatibility, booking availability, allocation, or final commitment. There is no AI booking pathway: confirmation always flows through Step 7 proposal accept → Step 5 revalidation → Step 6 allocation.

LangChain and LangGraph are **not** used.

### Conversation endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/conversations` | Create a `ChatThread` for a driver (optional shipment) |
| POST | `/conversations/{thread_id}/messages` | Handle a free-text driver message |

Existing Step 3 read APIs (`GET /chat-threads`, `GET /chat-messages`) are unchanged.

### Conversation context

Threads and messages reuse frozen Step 2 `ChatThread` / `ChatMessage` tables. Operational context (shipment, presented options, proposal, pending clarification, escalation) is reconstructed from `ChatMessage.metadata` JSON plus thread foreign keys. Secrets and system prompts are not stored.

### Tool registry

Allowlisted tools (no arbitrary function/SQL execution):

| Tool | Deterministic backend |
|------|------------------------|
| `get_shipment_status` | `ShipmentService` + latest ETA |
| `record_eta_update` | `ETAUpdateService` |
| `create_driver_exception` | `DriverExceptionService` |
| `evaluate_feasibility` | `FeasibilityService` (Step 5) |
| `get_available_options` | open slots + Step 5 evaluation |
| `create_proposal` / `get_proposal` / `accept_proposal` / `reject_proposal` | `ProposalService` (Step 7) |
| `request_human_escalation` | conversation metadata + `[ESCALATED]` thread subject |

### LLM provider

Configuration (environment variables, never committed):

```
LLM_PROVIDER=fake
LLM_API_KEY=
LLM_MODEL=openai/gpt-4o-mini
LLM_BASE_URL=https://openrouter.ai/api/v1
```

`LLM_PROVIDER=fake` (default) uses `FakeLLMProvider` — keyword/structured parsing, no network. `LLM_PROVIDER=openrouter` uses `OpenRouterProvider` only for language understanding. If OpenRouter is selected but `LLM_API_KEY` is empty, the app falls back to the fake provider. Unit tests never call a live model.

### Human escalation

Escalation is recorded on the conversation (message metadata and thread subject). A person has **not** already acted. Full human-task assignment, SLA, and resolution workflow are not in the frozen schema and are not implemented in Step 8.

### Known limitations

- No new conversation tables or migrations.
- Escalation is a flag/record, not a dispatch/notification platform.
- Driver identity is still not authenticated (pre-authentication limitation from earlier steps).


## Step 7 — Controlled Actions & Proposals

Step 7 implements the assignment distinction between showing an option, proposing it, and confirming the operational change. Proposals are **not** allocations — creating a proposal does not consume slot capacity or confirm an appointment.

### Architecture

```
HTTP → ProposalService → FeasibilityService (Step 5, read-only)
                       → AllocationService (Step 6, on accept only)
```

Proposal records are stored as `Appointment` rows with `status=requested` and a `STEP7_PROPOSAL` marker in `notes`. This reuses the frozen Step 2 schema without migration.

### State Lifecycle

| API Status | Persisted As | Meaning |
|------------|--------------|---------|
| `proposed` | `requested` | Active proposal, not yet committed |
| `rejected` | `rejected` | Driver/dispatcher rejected |
| `expired` | `expired` | TTL exceeded (30 min from `created_at`) |
| `stale` | `cancelled` + stale reason | Revalidation failed at accept time |
| `confirmed` | separate `confirmed` appointment via Step 6 | Operational change committed |

Valid transitions: `proposed → accepted → confirmed`, `proposed → rejected`, `proposed → expired`, `proposed → stale`. Terminal states cannot transition to `confirmed`.

### Proposal Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/shipments/{id}/proposals` | Create proposal (feasibility-checked, no allocation) |
| GET | `/proposals/{id}` | Retrieve proposal status |
| POST | `/proposals/{id}/accept` | Revalidate + invoke Step 6 allocation |
| POST | `/proposals/{id}/reject` | Reject proposal |

There is **no** `PATCH /proposals/{id}` status mutation endpoint. Confirmation only occurs through controlled accept logic.

### Revalidation

Acceptance always re-runs Step 5 feasibility and invokes Step 6 allocation. A proposal feasible at creation time is **not** assumed valid at acceptance time. If capacity, slot status, or feasibility changed, the proposal is marked `stale` and returns HTTP 409.

### Concurrency Boundary

Step 7 acquires a shipment advisory lock during accept, then delegates final allocation concurrency to Step 6 (slot/dock row locks, capacity re-check). Step 7 does not implement a second locking mechanism.

### AI Boundary

Step 7 contains no LLM, LangChain, agent framework, or natural-language decision logic. It accepts structured requests only. A future conversational layer may call these APIs.

### Known Limitations

- **Hold/reservation with expiry**: `AppointmentStatus.HELD` exists but there is no `expires_at` column. Hold-with-expiry is deferred until schema support is approved.
- **No idempotency key**: Repeated accepts on a confirmed proposal return the existing confirmation; no request deduplication key in schema.
- **Proposal expiration**: Computed from `created_at + 30 minutes` (application TTL), not a persisted `expires_at` field.
- **Two appointment rows on confirm**: Proposal row transitions to `cancelled`; Step 6 creates the `confirmed` appointment.
- **Two-commit boundary**: Step 6 commits the confirmed appointment; Step 7 updates proposal state in a second commit. Matching-allocation recovery reconciles proposal state on retry if the second commit fails.
- **No driver identity verification**: Accept/reject endpoints do not authenticate which driver is acting (pre-authentication limitation).

## Step 6 — Deterministic Allocation

Step 6 adds concurrency-safe, deterministic resource allocation. Allocation invokes Step 5 feasibility inside the lock and cannot bypass feasibility rules.

### Allocation Endpoint

| Method | Path | Description |
|--------|------|-------------|
| POST | `/shipments/{id}/allocate` | Allocate slot and dock atomically |

## Step 5 — Deterministic Feasibility Engine

Step 5 adds a read-only, deterministic feasibility evaluation engine. It answers whether a shipment's operational request can be safely accepted under known constraints and persisted facts. The engine does **not** allocate resources, mutate state, or use AI/LLM services.

### Architecture

```
HTTP → Router → Pydantic Schema → FeasibilityService → FeasibilityEngine
                                              ↓
                                        Repositories (read-only)
```

Layers:

- `app/engines/feasibility/` — pure rule evaluation (no database access)
- `app/services/feasibility.py` — fact retrieval and orchestration
- `app/schemas/feasibility.py` — request/response contracts

### Feasibility Endpoint

| Method | Path | Description |
|--------|------|-------------|
| POST | `/shipments/{id}/feasibility` | Evaluate operational feasibility |

Optional request body:

```json
{
  "appointment_slot_id": "uuid (optional — evaluate a specific slot)",
  "dock_id": "uuid (optional — evaluate a specific dock)",
  "evaluated_at": "2026-08-13T10:00:00+00:00 (optional — explicit timestamp for determinism)"
}
```

### Result Semantics

| Outcome | Meaning |
|---------|---------|
| `feasible` | All blocking rules passed |
| `not_feasible` | One or more blocking rules failed |
| `not_evaluable` | Required facts missing (e.g. ETA unavailable when slot window check is required) |

Each response includes ordered `rule_results` with `rule_id`, `reason`, `severity`, and supporting `facts`.

### Supported Deterministic Rules

| Rule ID | Category | Description |
|---------|----------|-------------|
| SHIP-001 | Shipment | Shipment must be active |
| SHIP-002 | Shipment | Status must not be terminal (cancelled/delivered) |
| SHIP-003 | Shipment | Destination facility must be assigned |
| CARR-001 | Carrier | Carrier must be active |
| DRIV-001 | Driver | Assigned driver must be active |
| VEHI-001 | Vehicle | Assigned vehicle must be active |
| VEHI-002/003 | Vehicle | Weight/volume within vehicle capacity (when data present) |
| FACI-001 | Facility | Destination facility must be active |
| APPT-001/002 | Appointment | Appointment or slot context required; facility alignment |
| SLOT-001–004 | Slot | Slot exists, facility match, status open, capacity available |
| DOCK-001–005 | Dock | Dock presence, facility match, availability, weight, reefer compatibility |
| RULE-001 | FacilityRule | `max_daily_appointments` limit |
| RULE-002 | FacilityRule | `operating_hours` window (facility timezone) |
| RULE-003 | FacilityRule | `dock_compatibility` vehicle type and pallet limits |
| ETA-001 | ETA | Latest ETA (from Step 4 history) within slot window |
| ETA-002 | ETA | Latest ETA outside operating hours (warning) |
| EXCP-001 | Exception | No OPEN or ACKNOWLEDGED driver exceptions |

### Limitations (Not Evaluable with Current Model)

- Travel time / distance prediction (no coordinates or routing data)
- Driver hours-of-service / availability schedules
- Vehicle length vs dock `max_length_m` (vehicle has no length field)
- Equipment string matching (`equipment_required` is free text)
- Automatic slot `FULL` status derivation (status is manually set)
- Dock time-calendar conflict detection (no time-based dock scheduling)
- Exception delay quantification (no `delay_minutes` field)
- Priority ranking among competing shipments
- Double-booking concurrency control (Step 6+)

## Step 4 — ETA + Exception Services

Step 4 adds deterministic operational write services for ETA updates and driver exceptions. ETA history remains immutable in `ETAUpdate`; the latest ETA is always derived from history, never stored on `Shipment`.

### Operational Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/shipments/{id}/eta-updates` | Record a new ETA update |
| GET | `/shipments/{id}/latest-eta` | Latest ETA derived from history |
| POST | `/shipments/{id}/exceptions` | Report a driver exception |
| PATCH | `/driver-exceptions/{id}` | Update exception status (acknowledge/resolve) |

Existing Step 3 read endpoints (`GET /eta-updates`, `GET /shipments/{id}/eta-updates`, etc.) remain unchanged.

## Step 3 — Business APIs

Step 3 exposes the frozen domain model through read-only REST APIs. The API layer retrieves facts and historical records; it does **not** perform operational decision logic (no feasibility, allocation, ETA prediction, or appointment recommendations).

### API Architecture

```
HTTP Request → FastAPI Router → Pydantic Schema → Service → Repository → SQLAlchemy → PostgreSQL
```

Layers:

- `app/api/` — route handlers and dependency injection
- `app/schemas/` — Pydantic request/response models
- `app/services/` — orchestration and 404 handling
- `app/repositories/` — database queries, filters, pagination

### Endpoint Categories

| Category | Endpoints |
|----------|-----------|
| Core entities | `/carriers`, `/drivers`, `/vehicles`, `/shipments`, `/facilities` |
| Facility resources | `/docks`, `/facility-rules`, `/appointment-slots`, `/appointments` |
| Conversations | `/chat-threads`, `/chat-messages`, `/contacts` |
| Operations | `/eta-updates`, `/driver-exceptions`, `/facility-checkins`, `/operational-messages` |
| Shipment history | `/shipments/{id}/eta-updates`, `/exceptions`, `/appointments`, `/facility-checkins`, `/chat-threads` |
| Facility relations | `/facilities/{id}/docks`, `/rules`, `/appointment-slots`, `/check-ins` |

All collection endpoints support `?page=1&page_size=50` (max 100) with deterministic ordering.

### Example API Calls

```bash
# Health check
curl http://localhost:8000/health

# List shipments filtered by status
curl "http://localhost:8000/shipments?status=in_transit&page=1&page_size=10"

# Get shipment with latest ETA (derived from ETAUpdate history)
curl http://localhost:8000/shipments/{shipment_id}

# Shipment ETA history (source of truth for ETA)
curl http://localhost:8000/shipments/{shipment_id}/eta-updates

# Facility docks
curl http://localhost:8000/facilities/{facility_id}/docks
```

### OpenAPI / Swagger

With the server running:

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- OpenAPI JSON: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

## Project Structure

```
app/
├── ai/            # Conversational understanding and allowlisted tool orchestration (Step 8)
├── core/          # Configuration, database, shared infrastructure
├── models/        # SQLAlchemy database models (Step 2 — frozen)
├── schemas/       # Pydantic request/response schemas
├── repositories/  # Database access
├── services/      # Application services
├── engines/       # Deterministic decision engines (Step 5 feasibility)
└── api/           # FastAPI routes
```

## Run Locally

### 1. Start PostgreSQL

```bash
docker compose up -d
```

### 2. Install dependencies

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

`LLM_PROVIDER` defaults to `fake`. Set `LLM_PROVIDER=openrouter` and `LLM_API_KEY` only when you want live language understanding. Tests do not require an API key.

### 4. Apply migrations

```bash
alembic upgrade head
```

### 5. Start the API

```bash
uvicorn app.main:app --reload
```

Health check: [http://localhost:8000/health](http://localhost:8000/health)

## Run Tests

```bash
pytest -v
```

API and model tests use an in-memory SQLite database. Migration tests require a running PostgreSQL instance (see `docker compose up -d`).

```bash
# API and model tests only (no PostgreSQL required)
pytest tests/test_api.py tests/test_health.py tests/test_models.py tests/test_models_hardening.py -v
```

## Database Migrations

Alembic manages schema migrations. Step 5 does not change the database schema.

```bash
alembic upgrade head    # apply migrations
alembic check           # verify no schema drift
```
