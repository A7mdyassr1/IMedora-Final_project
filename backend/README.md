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
├── middleware/     # Cross-cutting concerns (B5: early refusal of oversized uploads)
├── storage/       # File storage for attachments (interface + local disk, B5)
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

**Timeline:** it is derived from the ticket's audit rows (created, status, priority, deletion) and from `ticket_assignments` (assigned, unassigned), and is never stored. The automatic status change caused by an assignment is folded into that one entry. Work performed (maintenance records linked to the ticket) appears as `work_performed` entries.

### Ticket workflow (B4 CP2)

| Endpoint | Who |
|---|---|
| `PATCH /api/v1/tickets/{id}/status` `{status}` | see the rules below |
| `POST /api/v1/tickets/{id}/assignments` `{user_id}` | engineers (own hospital) and admins; technicians only themselves, and only on `open` or `assigned` tickets |
| `DELETE /api/v1/tickets/{id}/assignments/{user_id}` | engineers and admins; technicians only themselves |
| `PATCH /api/v1/tickets/{id}` `{priority}` | engineers (own hospital) and admins; not on closed or cancelled tickets |
| `DELETE /api/v1/tickets/{id}` | admins: soft delete, idempotent `204`. The ticket stays readable for admins and becomes read-only |

**Transitions** (`app/core/ticket_workflow.py`):

| From | To | Who |
|---|---|---|
| `open` | `cancelled` | engineer, admin, or the reporter while open and unassigned |
| `assigned` | `in_progress`, `cancelled` | assignee, engineer, admin (cancel: engineer, admin) |
| `in_progress` | `waiting_for_parts`, `resolved`, `cancelled` | assignee, engineer, admin (cancel: engineer, admin) |
| `waiting_for_parts` | `in_progress`, `resolved`, `cancelled` | assignee, engineer, admin (cancel: engineer, admin) |
| `resolved` | `closed`, `in_progress` (reopen) | engineer, admin |
| `closed`, `cancelled` | — | terminal |

- **Automatic status changes:** the first assignment moves `open` → `assigned`, and removing the last assignee moves `assigned` → `open`. A ticket in progress must keep at least one assignee.
- **Resolving** needs a maintenance record linked to the ticket (409 `maintenance_record_required`). Reopening needs an active assignee.
- **Assignees** must be active technicians or biomedical engineers of the ticket's hospital. Assignments stay active after resolution, as history; finished tickets and tickets of inactive hospitals take no new assignments.
- **Device status** is never changed by the ticket workflow.
- **Locking:** every change locks the ticket row, so concurrent changes run one after the other.
- **Audit:** every change is audited in the same transaction.
- **Errors:**
  - not visible → 404;
  - visible but not allowed → 403;
  - transition not in the table → 409 `invalid_status_transition`, with `details: [{from, to, allowed}]`;
  - deleted ticket → 409.

### Maintenance (B4 CP3)

Staff only: technicians, biomedical engineers, administrators. Department users get 403; they see the work done on their own tickets in the ticket timeline. Everything is scoped to the caller's hospital (admins: the organization), and out of scope is 404.

| Endpoint | Who | Notes |
|---|---|---|
| `GET /api/v1/maintenance-types` | staff | e.g. `preventive`, `corrective` (global reference data) |
| `POST /api/v1/maintenance-types` `{name}` | admin | Trimmed and lower-cased. **Migrations create no types, so a new production database needs at least one before records or schedules can be created** |
| `POST /api/v1/maintenance-records` | staff | `{device_id, maintenance_type_id, description, performed_at?, ticket_id?, schedule_id?}`; the performer is the caller |
| `GET /api/v1/maintenance-records`, `GET …/{id}` | staff | Filters: `device_id`, `hospital_id`, `department_id`, `maintenance_type_id`, `performed_by`, `ticket_id`, `schedule_id`, `performed_from`, `performed_to` |
| `PATCH /api/v1/maintenance-records/{id}` | engineer (own hospital), admin | Corrections: `description`, and `performed_at` unless a schedule depends on it. Records are never deleted |
| `GET /api/v1/devices/{id}/maintenance-records` | staff | A device's history, newest first; archived devices included |
| `POST /api/v1/maintenance-schedules` | engineer (own hospital), admin | `{device_id, maintenance_type_id, frequency_days (1–3650), next_due_date}`; one per device and type |
| `PATCH /api/v1/maintenance-schedules/{id}` | engineer (own hospital), admin | `frequency_days`, `next_due_date`, `is_active`. Schedules are deactivated, never deleted |
| `GET /api/v1/maintenance-schedules`, `GET …/{id}` | staff | Due list: active schedules of non-archived devices, soonest first. Filters: `due_before`, `overdue=true`, `department_id`, `maintenance_type_id`, `include_inactive` |
| `GET /api/v1/devices/{id}/maintenance-schedules` | staff | All of a device's schedules |

**Record rules:**
- No new records or schedules on archived devices or in inactive hospitals.
- `performed_at` cannot be in the future.
- **Linked to a ticket** (`ticket_id`):
  - the ticket must be on the same device, and not deleted, closed or cancelled;
  - technicians must be assigned to it;
  - the work cannot be dated before the ticket was reported.
  - This record is what allows the ticket to be **resolved**, and it appears in the ticket timeline as `work_performed`.
- **Linked to a schedule** (`schedule_id`, same device and type, active):
  - it sets `last_performed_date` to the work date and `next_due_date` to the work date + `frequency_days`;
  - a backdated record never moves a schedule backwards.

**`devices.next_maintenance_due_date`:**
- It is the earliest `next_due_date` of the device's **active** schedules, or empty when there are none.
- It is recomputed in the same transaction as every schedule change, and audited when it changes.
- The device row is locked while this happens, so concurrent changes cannot leave a stale date.
- Dates come from the database's time zone.

## Spare parts and stock (B5 CP1–CP2)

Staff only (technicians, biomedical engineers, administrators); department users get 403. Stock is per hospital and scoped like maintenance data: own hospital, administrators the organization; out of scope is 404.

| Endpoint | Who | Notes |
|---|---|---|
| `GET /api/v1/parts`, `GET …/{id}` | staff | Global catalog (like the device catalog). `q` searches name and part number |
| `POST /api/v1/parts`, `PATCH …/{id}` | engineer, admin | `{name, part_number, unit?, description?}`; `part_number` is unique, stored upper-case, no spaces |
| `DELETE /api/v1/parts/{id}` | engineer, admin | Only while no hospital stocks it and it was never used (409 `in_use`) |
| `GET /api/v1/inventory`, `GET …/{id}` | staff | Filters: `hospital_id`, `part_id`, `low_stock=true` (at or below the reorder threshold), `q` |
| `POST /api/v1/inventory` | engineer (own hospital), admin | `{part_id, hospital_id?, quantity_on_hand?, reorder_threshold?, reason?}`: one stock row per hospital and part |
| `PATCH /api/v1/inventory/{id}` | engineer (own hospital), admin | `{reorder_threshold}` only. The quantity cannot be set directly |
| `POST /api/v1/inventory/{id}/adjustments` | engineer (own hospital), admin | `{kind: restock \| correction, quantity_change, reason}`. Restocks add; corrections take either sign |
| `GET /api/v1/inventory/{id}/movements` | staff | Stock history, oldest first: `opening`, `restock`, `correction`, `usage`, `usage_change`, `usage_return`, with reason, record and who. `untracked_change` shows stock written outside the API (seed data, imports) |
| `POST /api/v1/maintenance-records` with `parts: [{part_id, quantity}]` | staff (as for records) | The record and its parts are one transaction |
| `POST /api/v1/maintenance-records/{id}/parts` | the record's performer, engineer (own hospital), admin | `{part_id, quantity}` |
| `PATCH`, `DELETE /api/v1/maintenance-records/{id}/parts/{part_id}` | engineer (own hospital), admin | Correct the quantity (the stock moves by the difference) or remove the line (the stock is given back) |
| `GET /api/v1/part-usage` | staff | What was used where. Filters: `part_id`, `hospital_id`, `device_id`, `ticket_id`, `maintenance_record_id`, `performed_from`, `performed_to` |

**Stock rules:**
- Stock can never go below zero: **409 `insufficient_stock`** (with `available` / `requested`). A part the device's hospital does not stock: **409 `part_not_stocked`**.
- The database trigger on `maintenance_parts` does the stock arithmetic. The API locks the stock rows first (`SELECT … FOR UPDATE`, in part order), checks under the lock, and audits the usage line and the stock movement in the same transaction. Concurrent usage, restocks and corrections queue; none is lost or oversold.
- The database `CHECK` and the trigger's `RAISE EXCEPTION` remain the last line of defence and map to the same 409 errors.
- Usage on a closed, cancelled or deleted ticket is final (409). No new usage on archived devices. An inactive hospital's stock is read-only (400).

## Notifications (B5 CP3)

In-app only. Every role reads **only their own** notifications; another user's id is 404.

| Endpoint | Notes |
|---|---|
| `GET /api/v1/notifications` | Newest first; `unread_only`; the response also has `unread_count` |
| `PATCH /api/v1/notifications/{id}/read` | Idempotent; `read_at` comes from the database clock |
| `POST /api/v1/notifications/read-all` | `{updated: n}` |

The server creates them in the same transaction as the event, so a refused or failed change notifies nobody:

| `type` | Event | Recipients |
|---|---|---|
| `ticket_created` | a problem is reported | the reporter ("request received"), and the hospital's engineers and technicians |
| `ticket_assigned` | someone is assigned (including taking a ticket) | the assignee and the reporter |
| `ticket_status_changed` | in progress, waiting for parts, closed, cancelled, reopened, back to open | the reporter and the active assignees |
| `ticket_resolved` | resolved | the reporter, with the work description |
| `device_alert` | a device goes under maintenance / out of service / back to active | the device's department users |

Nobody is notified of their own action; inactive or deleted users are skipped; texts never name staff (department users see roles). Every notification and read change is audited.

## Ticket photos (B5 CP4)

| Endpoint | Who | Notes |
|---|---|---|
| `POST /api/v1/tickets/{id}/attachments` | the reporter, active assignees, engineer (own hospital), admin | `multipart/form-data`, one `file`. JPEG or PNG only, recognised from the content (415 `unsupported_file`); at most `MAX_UPLOAD_MB` (413 `file_too_large`); at most 3 per ticket (409 `attachment_limit_reached`) |
| `GET /api/v1/tickets/{id}/attachments` | anyone who can see the ticket | Also included in every ticket detail as `attachments` |
| `GET /api/v1/attachments/{id}` | anyone who can see the parent | The file itself (`nosniff`, `no-store`) |
| `DELETE /api/v1/attachments/{id}` | engineer (own hospital), admin: any photo of the ticket; the reporter and active assignees: their own photos | `204`. Removes the record and the stored file, is audited, and frees the photo's slot in the limit of 3. Not on closed, cancelled or deleted tickets (409) nor in inactive hospitals (400), except for administrators (e.g. removing a photo that should never have been uploaded). Not visible to the caller: 404 |

- **Privacy:** location (GPS) and all other EXIF / XMP / text metadata are removed by re-encoding; the photo's orientation is applied first. Files are private: `file_url` in the database is an internal storage key, never a public address, and files are served only through the API after the visibility check.
- **Storage:** `STORAGE_BACKEND=local`, `STORAGE_DIR` (default `<repo>/storage/attachments`, git-ignored). **Back this folder up together with the database.** Keys are random; names are kept only for display.
- **Consistency:** the file is written first, then the row and its audit row are committed; on any failure the file is deleted again. The count of 3 is checked with the ticket row locked.
- Oversized uploads are refused before their body is read when the request announces its size. In production, also cap the request size at the reverse proxy.
- Not on closed, cancelled or deleted tickets, nor in inactive hospitals. Rows written before B5 (seed data with an external URL) are listed, but their file is never fetched or redirected to (404).
- **Deleting:** the record and its audit row are committed first; the file is removed only afterwards. A failed commit changes nothing. A file that is already missing (or never stored by IMedora) does not block the deletion. If the file cannot be removed after the commit (disk error), the deletion stands and the now unreferenced file is logged at ERROR level with its storage key (`orphaned storage key …`) for manual cleanup; it can no longer be downloaded.

## Risk assessments (B6 CP1)

| Endpoint | Who | Notes |
|---|---|---|
| `POST /api/v1/risk-assessments` | engineer (own hospital), admin | `{device_id, risk_level, notes?, assessed_at?}`. Organization, hospital and assessor are set by the server and refused if sent (422) |
| `GET /api/v1/risk-assessments` | technician, engineer (own hospital), admin | Filters `device_id`, `hospital_id`, `risk_level`, `assessed_by`, `assessed_from` / `assessed_to`; sort `assessed_at` (default, newest first), `created_at`, `risk_level` |
| `GET /api/v1/risk-assessments/{id}` | same | |
| `GET /api/v1/devices/{id}/risk-assessments` | same | A device's history, newest first; archived devices included |
| `PATCH /api/v1/risk-assessments/{id}` | engineer (own hospital), admin | Corrections: `risk_level`, `notes` (null clears), `assessed_at`. The device and the ownership fields cannot change (422). Audited |

- **Order of checks:** the role first (technicians and department users get **403 on every write without any lookup**; department users get 403 on every read), then existence and scope (404), then the device's state (400).
- **`devices.current_risk_level` is written only by the database trigger** (latest `assessed_at` wins; a backdated assessment never overrides a newer one). The backend locks the device row before every risk write so concurrent writes cannot leave a stale level, and only *reads* the level before and after the write. Responses show it in `device.current_risk_level`.
- `assessed_at` defaults to now: the database time once the device lock is held, so assessments of one device saved without a time are ordered as they were saved (B6-L2); never in the future (400). A second assessment of the same device at exactly the same time is refused (409 `duplicate_assessment_time`): the trigger has no tie-breaker.
- No new assessments or corrections on archived devices or in inactive hospitals (400); their history stays readable. Decommissioned and out-of-service devices can be assessed.
- **Audit:** every create and correction, in the same transaction. When the trigger changes a device's level, a `devices` `update` row records `{"current_risk_level": before}` → `{"current_risk_level": after, "cause": {...}}` (team decision D17).
- No delete endpoint: assessments are history.

## QA records (B6 CP2)

Inspections, calibrations and compliance checks, in one table (`record_type`).

| Endpoint | Who | Notes |
|---|---|---|
| `POST /api/v1/qa-records` | engineer (own hospital), admin | `{device_id, record_type, status?, findings?, performed_at?, next_due_date?}`; `status` defaults to `pending` |
| `GET /api/v1/qa-records` | technician, engineer (own hospital), admin | Filters `device_id`, `hospital_id`, `record_type`, `status`, `performed_by`, `performed_from` / `performed_to`, `due_after` / `due_before`; sort `performed_at` (default), `next_due_date` (empty dates last), `created_at` |
| `GET /api/v1/qa-records/{id}` | same | |
| `GET /api/v1/devices/{id}/qa-records` | same | Newest first; optional `record_type` |
| `PATCH /api/v1/qa-records/{id}` | engineer (own hospital), admin | `status`, `findings`, `performed_at`, `next_due_date` (`null` clears findings / next due date). Device, type and ownership fields cannot change (422) |

- **Status:** only `pending` → `pass` or `fail`. A `pass` / `fail` result is final: any other change is 409 `invalid_qa_status_transition` (sending the current status again is fine). Findings and dates of a finalized record can still be corrected, audited.
- `next_due_date` must be on or after the **database's** date of `performed_at` (422 `constraint_violation`, from the pre-check or from `ck_qa_next_due_after_performed`). `performed_at` is never in the future (400).
- Same order of checks and the same archived / inactive-hospital rules as risk assessments. A failed check creates no ticket, changes no device status and sends no notification. No delete endpoint.

## Risk and QA summaries, QA due list (B6 CP3)

Technicians, engineers (own hospital) and administrators (organization); department users get 403. Archived devices are left out unless an administrator sets `include_archived=true` (403 for other roles), as in the device list.

| Endpoint | Returns |
|---|---|
| `GET /api/v1/risk-assessments/summary` | Devices per **current** risk level as kept by the database (`low`, `medium`, `high`, `critical`) plus `unassessed`; optional `hospital_id` |
| `GET /api/v1/qa-records/summary` | All QA records in scope: `total`, `by_status`, `by_type`; optional `hospital_id` |
| `GET /api/v1/qa-records/due` | Checks that are due: `within_days` (0–365, default 30), `include_overdue` (default `true`), `hospital_id`, `record_type`, `device_id`; soonest first; paged. Each item has `due_status` (`overdue` / `upcoming`) and `days_until_due`; the response echoes `today` (the database's date) |

**Due list rule:** for each device and record type only the **latest** record counts (by `performed_at`, then creation time, then id). An older record is superseded and never listed, even if its own due date is near. The latest record's `next_due_date` decides: before today = overdue (listed when `include_overdue`); today to today + `within_days` = upcoming. Records without a next due date are not listed.

## Device history (B6 CP4)

`GET /api/v1/devices/{id}/history`: one feed, newest first (equal times: by entry type name, alphabetically, then id), paged. Filters: `types` (comma-separated), `from` / `to` (inclusive).

| `type` | Time | Shows |
|---|---|---|
| `ticket_reported` | ticket created | number, priority, **current** status, reporter |
| `ticket_resolved` | `resolved_at` | number, priority, current status |
| `maintenance_record` | `performed_at` | type, performer, linked ticket, number of parts used |
| `risk_assessment` | `assessed_at` | level, assessor |
| `qa_record` | `performed_at` | type, status, next due date, performer |

- **Administrators** (organization), **engineers and technicians** (own hospital): every type; ticket entries follow exactly the rules of `GET /devices/{id}/tickets` (soft-deleted tickets excluded).
- **Department users** (devices of their own department only; other departments 404): only `ticket_reported` / `ticket_resolved` entries of tickets **they reported**, staff shown as roles. Asking for another type is 403 before any lookup.
- One consistent picture: the total, the page and the entries' details come from one database snapshot (REPEATABLE READ), even while other requests write (B6-L3).
- Archived devices keep a readable history. Closed and cancelled tickets have no time of their own and show as the ticket's current status; the step-by-step story stays in the ticket timeline. Built from existing tables only.

## Mobile contract (B8)

The Flutter app's requirements (Master Instructions section 5, `mobile/lib/features/*/domain`) mapped to this API. The full field-by-field contract is [`docs/api/mobile-contract.md`](../docs/api/mobile-contract.md), checked by `tests/test_mobile_contract.py`. The mobile app's base URL **includes `/api/v1`** (e.g. `http://10.0.2.2:8000/api/v1`; `--dart-define=API_BASE_URL=...`).

- **Login:** `POST /auth/login` `{identifier, password}` answers `{token, user, ...}`. `token` is the same JWT as `access_token` (kept for existing clients). Send it as `Authorization: Bearer <token>`; `GET /auth/me` restores a stored session (401 when it is no longer valid).
- **Forgot password:** `POST /auth/forgot-password` `{email}` (or `identifier`), no sign-in. Every well-formed request gets `202` with the same message; the request is processed **after** the answer is sent (own session), so neither the answer nor its timing shows whether the account exists. IMedora has no e-mail service: for an account that can sign in, the organization's admins get one in-app `password_reset_requested` notification (not repeated while unread) and set a new password with `POST /users/{id}/reset-password`. Unknown or blocked accounts: nothing is stored. Audited (no actor). The account row is locked `FOR NO KEY UPDATE` (requests for two admins at once cannot deadlock). Limits: an organization's only admin cannot be helped this way (nobody else to notify); not rate limited (limit it at the reverse proxy).
- **Device picker:** `GET /devices?q=` matches the device name, device code, serial number, QR identifier **and department name** (case-insensitive), inside the caller's scope.

## Read-only AI token (B9 CP1)

Decision 7: the AI service will read hospital data only by calling this API back **as the requesting user**, with a token the backend gives it for one chat request.

- **The token:** a normal token of that user plus `"scp": "read"`.
  - It lives `AI_TOKEN_EXPIRE_MINUTES` (default 5, at most 15).
  - It always carries the password stamp.
  - It stops working, like any token, after a password change or reset, or when the user, their hospital or their organization is deactivated.
  - Tokens from login carry no `scp`. Any other `scp` value is rejected (401).
- **The guard:** `get_current_user`, which every signed-in endpoint uses, refuses a read-only token on any method other than GET / HEAD / OPTIONS: `403 read_only_token`, before the endpoint runs.
  - A token that is invalid in any other way is still 401.
  - GET requests see exactly what the user sees (same scope).
- **Issued by** `create_ai_token()` (`app/core/security.py`), only for the AI service, by `/ai/chat` (below).

## AI assistant (B9 CP2)

`POST /ai/chat` `{question, device_id?, history?}` answers `{text, follow_ups, source_type, data_available}`.
- **Who:** every signed-in role (team decision 2026-11-26).
- **Contracts:**
  - `docs/api/mobile-contract.md` §4.5 (the app);
  - `docs/api/ai-service-contract.md` (the AI service, a proposal for the AI owner).

**How it works (Decision 7):**
1. A `device_id` must be a device the caller can see (403 `department_required` / 404), checked before anything is sent.
2. The backend issues the caller's read-only AI token (above) and releases its database connection.
3. It calls `POST {AI_SERVICE_URL}/v1/chat` with `X-API-Key: AI_SERVICE_API_KEY`, the question, the history, the caller's role and the token.
4. The AI service reads data only by calling this API back with that token: same scope as the user, no writes, no chat-in-chat.

**Errors:**
- `503 ai_unavailable`: `AI_SERVICE_URL` is unset (the assistant is off), or the AI service is unreachable, slower than `AI_SERVICE_TIMEOUT_SECONDS` (default 30) or answering 5xx.
- `502 ai_bad_response`: the AI service answered anything else.
- The AI service's own text never reaches the client.

**Limits (422 above them; each is a setting):** question `AI_QUESTION_MAX_CHARS` 2,000; history `AI_HISTORY_MAX_MESSAGES` 20 of `AI_HISTORY_MESSAGE_MAX_CHARS` 4,000.

**Client rules:**
- no redirects followed;
- no proxy settings taken from the environment;
- reply at most 256 KiB, checked field by field;
- `AI_SERVICE_API_KEY` is required whenever `AI_SERVICE_URL` is set.

**Logs:** metadata only (user, role, sizes, outcome, duration). Never the question, history, answer, token or key. No audit row (a chat changes no data).

## Planned API Domains

- Authentication
- Users
- Hospitals
- Departments
- Medical Devices
- Maintenance (preventive & corrective)
- Tickets
- Parts (B5)
- Notifications, attachments (B5)
- Reports / Analytics
- Risk Management (B6)
- Quality Assurance (B6)
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
- **B4 (tickets & maintenance) done** on `feature/backend-b4-jana` (`a2168d6`, `9d7031d`, `062ef46`; seed fix `7d5fa04`):
  - **Checkpoint 1 (ticket core):**
    - ORM mirrors of the five maintenance tables and the ticket enums.
    - Report a problem, including on another department's device scanned by QR.
    - Ticket lists, "my tickets", ticket detail with a derived timeline, and a device's ticket history.
    - Visibility rules in `app/core/access.py`.
  - **Checkpoint 2 (workflow):** status transitions, assignments, priority, admin soft delete, row locking, timeline v2.
  - **Checkpoint 3 (maintenance):** maintenance types, records and schedules; `next_maintenance_due_date`; work-performed events in the ticket timeline; tickets resolvable through the API alone.
  - `GET /devices/{id}/history` is deferred until the data it shows exists (parts are now available; risk/QA follow).
- **B5 (spare parts, notifications, attachments)** on `feature/backend-b5-jana`:
  - **Checkpoint 1:** parts catalog, per-hospital stock, adjustments and stock history; stock errors mapped.
  - **Checkpoint 2:** parts used on maintenance records, row-locked, through the database trigger; usage report.
  - **Checkpoint 3:** in-app notifications for ticket and device events; the mobile app's three notification endpoints.
  - **Checkpoint 4:** ticket photos (Decision 5): storage interface, local disk, content checks, metadata removal, limit of 3.
  - **Follow-up:** deleting ticket photos (`DELETE /attachments/{id}`), team decision 2026-11-24.
  - No schema change and no migration.
- **B6 (risk assessments, QA records)** on `feature/backend-b6-jana` (approved plan `B6_PLAN.md`, Revision 5):
  - **Checkpoint 1:** risk assessments; the trigger-maintained `current_risk_level` with the device row locked for every write; equal-time guard; audit of the device's level changes.
  - **Checkpoint 2:** QA records; status rules (a pass / fail result is final); the next-due-date rule checked with the database's date (422).
  - **Checkpoint 3:** risk and QA summaries; the QA due list (latest record per device and type only).
  - **Checkpoint 4:** device history `GET /devices/{id}/history` (deferred since B4), per-role visibility; seed smoke tests for the seeded risk / QA data.
  - No schema change and no migration.
- **B8 (mobile contract)** on `feature/backend-b8-jana`, with the four B6 review findings:
  - **B6-L1:** QA due-date regression test with a database time zone west of UTC.
  - **B6-L2:** a default `assessed_at` is read under the device lock, so it follows the save order. `created_at` stays the transaction start (column default), so for writers that queued on the lock the two orders can differ.
  - **B6-L3:** device history is read in one snapshot (total, page and details agree).
  - **B6-L4:** `PersonRef` and its builder live in `app/schemas/person.py`, shared by tickets and history.
  - **Checkpoint 1:** `token` in the login response; `POST /auth/forgot-password` (admins notified in-app).
  - **Checkpoint 2:** the device picker's `q` also matches the department name.
  - **Checkpoint 3:** `docs/api/mobile-contract.md` and `tests/test_mobile_contract.py`.
  - No schema change and no migration.
- **B9 (AI proxy)** on `feature/backend-b9-jana`, in progress (plan `B9_PLAN.md`):
  - **Checkpoint 1:** the read-only AI token and its guard (Decision 7, conditions 1 and 4; the guard deferred from B3.1).
  - **Checkpoint 2:** `POST /ai/chat` proxy, built against the proposed AI service contract (`docs/api/ai-service-contract.md`, team decisions 2026-11-26).
  - **Checkpoints 3–4** (the data endpoints for `BackendDataProvider`; cross-scope and prompt-injection tests against the real AI service) need the AI owner.
  - No schema change and no migration.
