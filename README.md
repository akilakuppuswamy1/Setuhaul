# SetuHaul

SetuHaul is a deterministic logistics and warehouse appointment coordination system. It helps coordinate inbound shipments at constrained receiving facilities by evaluating operating hours, dock capacity, slot availability, vehicle compatibility, and existing appointments using explicit, testable rules.

## Deterministic Architecture

Operational decisions (slot feasibility, capacity, priority, dock compatibility, appointment allocation, and booking confirmation) are implemented with explicit Python rules—not generative AI or LLM services. Every decision path must be reproducible and testable.

## Step 1 Scope

This repository contains the **project foundation only**:

- FastAPI application skeleton
- Configuration via environment variables (`pydantic-settings`)
- SQLAlchemy database setup (no tables yet)
- Alembic migration scaffolding
- PostgreSQL via Docker Compose
- Health check endpoint and basic tests

Business modules (shipments, appointments, scheduling, allocation, etc.) will be added in later steps.

## Project Structure

```
app/
├── core/          # Configuration, database, shared infrastructure
├── models/        # SQLAlchemy database models
├── schemas/       # Pydantic request/response schemas
├── repositories/  # Database access
├── services/      # Application/business services
├── engines/       # Deterministic decision engines
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

### 4. Start the API

```bash
uvicorn app.main:app --reload
```

Health check: [http://localhost:8000/health](http://localhost:8000/health)

## Run Tests

```bash
pytest
```

## Database Migrations

Alembic is initialized but no migrations exist yet. When models are added in later steps:

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```
