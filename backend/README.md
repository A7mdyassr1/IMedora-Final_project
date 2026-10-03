# IMedora Backend

REST API and core business logic for the IMedora platform. Web framework is TBD (e.g. FastAPI); the structure below is designed to stay valid regardless of the final choice.

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

No APIs, models, or business logic have been implemented yet — this is the initial scaffold only.
