# IMedora Backend

REST API and core business logic for the IMedora platform, built with FastAPI + SQLAlchemy 2.x on the existing PostgreSQL schema (owned by `database/migrations`, never created from the ORM).

## Structure

```
app/
├── api/           # Route definitions / controllers, grouped by domain
├── core/          # App configuration, settings, startup/shutdown logic
├── models/        # Database models (ORM entities)
├── schemas/       # Request/response data schemas (validation)
├── services/      # Business logic, orchestration between repositories
├── repositories/  # Data-access layer (queries, persistence)
├── middleware/     # Cross-cutting concerns (auth, logging, error handling)
├── utils/         # Generic helper functions
└── main.py        # Application entry point / factory
tests/             # Backend test suite
```

## Design Principles

- **API-first**: the API contract is the source of truth for frontend and AI service integration.
- **Layered architecture**: `api` → `services` → `repositories` → `models`, keeping business logic out of route handlers and data access out of services.
- **One domain, one set of files**: as each domain below is implemented, it should get its own module inside `api/`, `models/`, `schemas/`, `services/`, and `repositories/` (e.g. `api/devices.py`, `models/device.py`, etc.) so teams can work in parallel.

## Running

```bash
pip install -r backend/requirements.txt        # from the repo root, venv active
cd backend
uvicorn app.main:app --reload                  # reads DATABASE_URL from the repo-root .env
pytest                                         # set TEST_DATABASE_URL to include the PostgreSQL tests
```

Docs: `/docs`, `/redoc`. Health: `/health`, `/health/db`. Versioned prefix: `/api/v1`.

## Planned API Domains

- Authentication
- Users
- Hospitals
- Departments
- Medical Devices
- Maintenance (preventive & corrective)
- Tickets
- Parts
- Reports / Analytics
- Risk Management
- Quality Assurance
- AI Assistant (proxy to the `ai/` service)

## Status

**Phase B1 (foundation) done:** app factory, settings, PostgreSQL connection, session dependency, health endpoints, error handling, logging, CORS, `/api/v1` router. No domain APIs yet (auth is Phase B2).
