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
| 5+ | Feasibility, allocation, actions | Not started |

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
├── core/          # Configuration, database, shared infrastructure
├── models/        # SQLAlchemy database models (Step 2 — frozen)
├── schemas/       # Pydantic request/response schemas
├── repositories/  # Database access
├── services/      # Application services
├── engines/       # Deterministic decision engines (future steps)
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

Alembic manages schema migrations. Step 3 does not change the database schema.

```bash
alembic upgrade head    # apply migrations
alembic check           # verify no schema drift
```
