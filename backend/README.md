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

First admin (and real passwords for the dev-seed users, which only have a placeholder hash):

```bash
python -m scripts.create_user --email admin@cairomed.example --full-name "Admin" \
    --role admin --organization-code CAIRO-MED --hospital-code CMC-MAIN
```

Docs: `/docs`, `/redoc`. Health: `/health`, `/health/db`. Versioned prefix: `/api/v1`.

Access rules: any logged-in user can read (always limited to their own organization). Hospitals, departments, locations and the organization itself are changed by `admin`. Devices and the device catalog (categories, manufacturers, models) are changed by `admin` or `biomedical_engineer`. Devices are never hard-deleted: `DELETE /devices/{id}` archives (decommissions) them.

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

- **B1 (foundation) done:** app factory, settings, PostgreSQL connection, health endpoints, error handling, logging, CORS, `/api/v1`.
- **B2 (auth) done:** login (Argon2 + JWT), `/auth/me`, change password, role-based access (`require_roles`), admin user management (`/users`), organization-scoped.
- **B3 (device management) done:** organization, hospitals, departments, locations, device categories / manufacturers / models, devices (search, filters, sorting, pagination, archive) and QR lookup `GET /devices/qr/{qr_identifier}`. Database constraint errors are translated centrally in `app/core/db_errors.py`.
- Next: B4 (maintenance: types, schedules, tickets, records, assignments). `GET /devices/{id}/history` is deferred until B4/B6 provide the data it shows.
