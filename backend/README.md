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

Requires **Python 3.11+** (tested on 3.11, 3.12 and 3.13) and a PostgreSQL database migrated with `alembic upgrade head` (see `database/README.md`).

1. **Environment.** The backend reads the **repository-root `.env`** (the same file `database/` uses), never `backend/.env`. Two values are required:
   - `DATABASE_URL`
   - `JWT_SECRET_KEY`, at least 32 random characters. The API will not start without it.

   `backend/.env.example` lists every variable with its default. Copy what you need into the root `.env`, and never commit a real `.env`.

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"   # a value for JWT_SECRET_KEY
   ```

2. **Install and run:**

   ```bash
   pip install -r backend/requirements.txt        # from the repo root, venv active (exact, tested pins)
   cd backend
   uvicorn app.main:app --reload
   ```

3. **Tests:**

   ```bash
   pytest                                         # unit tests only; the PostgreSQL tests are skipped
   # Full suite: create an EMPTY database named exactly imedora_test, migrate it, then
   TEST_DATABASE_URL=postgresql+psycopg2://<user>:<password>@localhost:5432/imedora_test pytest
   ```

Before relying on QR lookups against an existing database, run the read-only QR data check. It must be run **from `backend/`** (it fails from the repo root), and it needs only `DATABASE_URL`, read from the environment or the root `.env`. PostgreSQL rejects any write it might attempt.

```bash
cd backend
python -m scripts.check_qr_identifiers      # exit 0 = OK, 1 = issues listed, 2 = DATABASE_URL missing
```

First admin (and real passwords for the dev-seed users, which only have a placeholder hash):

```bash
python -m scripts.create_user --email admin@cairomed.example --full-name "Admin" \
    --role admin --organization-code CAIRO-MED --hospital-code CMC-MAIN
```

Docs: `/docs`, `/redoc`. Health: `/health`, `/health/db`. Versioned prefix: `/api/v1`.

Access rules: any logged-in user can read (always limited to their own organization). Hospitals, departments, locations and the organization itself are changed by `admin`. Devices and the device catalog (categories, manufacturers, models) are changed by `admin` or `biomedical_engineer`. Devices are never hard-deleted: `DELETE /devices/{id}` archives (decommissions) them.

## Access scope (B3.1 CP3)

Who can see and change what is decided in one place, `app/core/access.py`. The scope comes from the logged-in user's own database row, never from request parameters.

| Role | Devices | Hospitals / departments / locations | Device writes |
|---|---|---|---|
| admin | whole organization | whole organization | whole organization |
| biomedical_engineer | own hospital | own hospital | own hospital only |
| technician | own hospital | own hospital | none (role) |
| department_user | own department | own hospital | none (role) |
| department_user without a department | **403 `department_required`** | own hospital | none (role) |

- **Out of scope looks like it doesn't exist.** A record outside the caller's scope answers **404**, exactly like a record that doesn't exist; the API never reveals that it exists. Creating a device in another hospital gets the existing `400 "Hospital does not exist in your organization."`, the same answer as an unknown hospital.
- **Filters only narrow.** Query filters such as `hospital_id`, `department_id` or `q` can narrow the scope but never widen it.
- **Archived devices.** `include_archived=true` is admin-only; other roles get 403. Archived devices still open by ID or QR inside the caller's scope (read-only).

**QR lookup and the mobile app.** `GET /devices/qr/{qr}` can return two shapes:

- **Full `DeviceResponse`** (unchanged; it has no `access` field). This is what every role gets within its scope, and what a department user gets for a device in their own department.
- **Limited `DeviceSummaryResponse`**, marked `"access": "limited"`, when a department user scans a device of **another department in their own hospital**.
  - It contains: `id`, `device_code`, `name`, `qr_identifier`, `status`, `is_archived`, hospital and department ids and names, `location_id`, `location`, `model_name`, `manufacturer_name` and `category_name`.
  - Serial number, criticality, risk level, dates and timestamps are **absent** (not null).
  - Problem reporting from that screen arrives with the B4 ticket APIs.

**Errors the app should handle:**

| Situation | Response |
|---|---|
| A device in another hospital | 404 |
| A department user without a department | 403, error code `department_required` |

### Seed smoke tests (opt-in)

`tests/test_seed_smoke.py` runs only when `TEST_SEED_DATABASE_URL` is set. It refuses any database not named exactly `imedora_seedtest`, and never reads `DATABASE_URL` or `TEST_DATABASE_URL`. It creates temporary users (plus one temporary hospital) and removes them again, even when a test fails. Seed scripts are never changed.

```bash
createdb imedora_seedtest
DATABASE_URL=postgresql+psycopg2://<user>:<pw>@localhost:5432/imedora_seedtest alembic upgrade head          # repo root
DATABASE_URL=postgresql+psycopg2://<user>:<pw>@localhost:5432/imedora_seedtest python database/seeds/run_all.py
cd backend && TEST_SEED_DATABASE_URL=postgresql+psycopg2://<user>:<pw>@localhost:5432/imedora_seedtest pytest -q tests/test_seed_smoke.py
```

## Tickets (B4 CP1)

| Endpoint | Who | Notes |
|---|---|---|
| `POST /api/v1/tickets` | everyone | Report a problem: `{device_id, category, description, priority?}` |
| `GET /api/v1/tickets` | everyone, scoped | Filters: `status`, `priority` (both repeatable), `hospital_id`, `department_id`, `device_id`, `reported_by`, `assigned_to` (`me` or an id), `created_from`, `created_to`, `q`, `include_deleted` (admins only). Sort: `created_at` (default, newest first), `updated_at`, `priority`, `status` |
| `GET /api/v1/tickets/mine` | everyone | Tickets the caller reported, newest first |
| `GET /api/v1/tickets/{id}` | everyone, scoped | Ticket plus its derived `timeline` |
| `GET /api/v1/devices/{id}/tickets` | device scope, then ticket scope | A device's ticket history |

**Which tickets a user sees** (out of scope is 404):

| Role | Tickets |
|---|---|
| admin | whole organization; soft-deleted tickets only with `include_deleted=true` |
| biomedical_engineer, technician | own hospital, plus tickets they reported |
| department_user | only tickets they reported, even after losing their department |

**Reporting a problem:**

- Every role can report, on any device of its own hospital. That includes another department's device scanned by QR, for department users; admins can report anywhere in the organization.
- A department user without a department gets 403 `department_required`.
- Archived devices and devices in inactive hospitals are refused with 400.
- The server sets the organization, hospital, reporter and `status=open`.

**Response fields:**

- `category` is one of `Device not working`, `Abnormal reading`, `Physical damage`, `Alarm/problem`, `Power issue`, `Other`. It is stored as a `[Category] ` prefix of `problem_description`, parsed exactly like the mobile app does; text without a known prefix reads as `Other`.
- `number` is `TKT-XXXXXXXX`, derived from the id and display-only.
- `device` holds identifying fields only.
- For department users, staff appear as a role (`"name": "Technician"`, `"id": null`).

**Timeline:** it is derived from the ticket's audit rows (created, status, priority, deletion) and is never stored. Assignment events arrive in B4 CP2, and work performed in CP3.

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
- **B3.1 (hardening):**
  - **Checkpoint 1:** `backend/.env.example`; 8-hour default token lifetime; exact dependency pins; the QR lookup compares the indexed column directly, so the unique index is usable (the `upper()` fallback scan is removed); fixed the `safe_database_url` test.
  - **Checkpoint 2:**
    - **Audit log:** every change through the API or `scripts/create_user.py` writes an `audit_logs` row in the same transaction. Passwords, hashes and tokens are never stored.
    - **Password stamp:** a password change or reset invalidates all earlier tokens; the user must log in again.
    - **Active status:** an inactive organization or hospital blocks login and existing tokens, and nothing new can be added to an inactive hospital. An admin cannot deactivate their own hospital.
    - **Ticket numbers:** `TKT-XXXXXXXX` is derived from the ticket UUID (`app/utils/ticket_number.py`; `app/schemas/ticket.py` holds `TicketNumberMixin` for B4).
  - **Checkpoint 3 (access scope):**
    - Every device and structure read and write is limited by role (`app/core/access.py`).
    - A department user's QR lookup works across their own hospital, but returns a limited summary for other departments' devices.
    - `include_archived=true` is admin-only.
    - New tests: a schema-compatibility test and opt-in seed smoke tests.
    - The read-only token guard is deferred to the AI phase.
- **B3.1 done** (commit `c2aebbf`).
- **B4 (tickets & maintenance) in progress** on `feature/backend-b4-jana`:
  - **Checkpoint 1 (ticket core):**
    - ORM mirrors of the five maintenance tables and the ticket enums.
    - Report a problem, including on another department's device scanned by QR.
    - Ticket lists, "my tickets", ticket detail with a derived timeline, and a device's ticket history.
    - Visibility rules in `app/core/access.py`.
  - Next: CP2 workflow and assignments, CP3 maintenance records and schedules, CP4 integration.
  - `GET /devices/{id}/history` is deferred until B4/B6 provide the data it shows.
