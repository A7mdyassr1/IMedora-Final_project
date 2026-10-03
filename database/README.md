# IMedora Database — Local Setup

Scope: **database only**. This folder has no dependency on `backend/` -
migrations are hand-written SQL/Alembic, not generated from any ORM.

One deployment = one organization's own PostgreSQL instance (on-premise,
private cloud, or an isolated cloud instance). Nothing here assumes a
shared database.

## 1. Prerequisites

- PostgreSQL 14+ running somewhere you can reach
- Python 3.11+ (only needed to run Alembic/seeds/tests - no app code)

## 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r database/requirements.txt
```

## 3. Configure the connection

```bash
cp .env.example .env
# edit .env with your real DATABASE_URL
```

## 4. Create the database (once)

```bash
psql -U postgres -c "CREATE USER imedora WITH PASSWORD 'imedora' CREATEDB;"
psql -U postgres -c "CREATE DATABASE imedora OWNER imedora;"
```

## 5. Run migrations

```bash
alembic upgrade head
```

## 6. Load sample data (optional)

```bash
python database/seeds/seed_phase1.py
python database/seeds/seed_phase2.py    # depends on seed_phase1.py having run
python database/seeds/seed_phase3.py    # depends on seed_phase1.py and seed_phase2.py
python database/seeds/seed_phase4.py    # depends on seed_phase1.py and seed_phase2.py
python database/seeds/seed_phase5.py    # depends on seed_phase1.py and seed_phase2.py
python database/seeds/seed_phase6.py    # depends on seed_phase1.py through seed_phase5.py

# or, all at once, in the correct order:
python database/seeds/run_all.py
```

### Realistic bulk data (for demos / dashboards / load testing)

The `seed_phaseN.py` scripts above create a handful of deterministic rows -
enough to prove the schema works, not enough to look like a real hospital
group. For that, use the bulk generator separately:

```bash
python database/seeds/generate_bulk_data.py               # ~200 devices, 3 hospitals
python database/seeds/generate_bulk_data.py --scale 2      # roughly double the volume
python database/seeds/generate_bulk_data.py --seed 7       # different random data, same volume
```

It creates its own organization ("Egypt Health Group" / `EHG`) so it never
touches or duplicates the `seed_phaseN.py` data - safe to run either
before or after them, in any order. It's meant to run **once**; running it
again refuses on purpose (use `--force` to add more anyway, or drop and
recreate the database to start over). Uses `Faker` for names/emails and
respects every constraint and trigger in the schema - stock is tracked in
memory so `maintenance_parts` usage never oversells, and every generated
row goes through the exact same `INSERT` path as everything else, no
special-casing.

## 7. Validate

```bash
python database/tests/validate_phase1.py
python database/tests/validate_phase2.py
python database/tests/validate_phase3.py
python database/tests/validate_phase4.py
python database/tests/validate_phase5.py
python database/tests/validate_phase6.py

# or, all at once:
python database/tests/run_all.py
```

Phase 1: 12 checks (hierarchy, per-hospital device_code scoping, qr_identifier
global uniqueness, warranty CHECK, the full RESTRICT chain, SET NULL on
location deletion, the updated_at trigger, and a correct bottom-up teardown).

Phase 2: 12 checks, including the two composite-FK guarantees this phase
was built around — a maintenance record's `ticket_id` must belong to the
same device as the record, and its `schedule_id` must match both the
device AND the maintenance type — plus the partial-unique-index behavior
on `ticket_assignments` (blocks a duplicate active assignment, but allows
reassigning the same user after they're unassigned).

Phase 3: 13 checks, centered on the inventory-adjusting trigger on
`maintenance_parts` — stock decrements on insert, adjusts by the delta on
an update, restores on delete, rejects usage that would take stock
negative, and rejects usage at a hospital that never stocked the part.

Phase 4: 13 checks, centered on the `devices.current_risk_level` cache
trigger — proves it's recomputed from the latest assessment by date (not
insert order: a backdated assessment doesn't override a newer one),
falls back correctly when the latest assessment is deleted, and clears
to NULL once no assessments remain — plus the `qa_records` CHECK
constraint and RESTRICT chain.

Phase 5: 10 checks — the exactly-one-parent CHECK on `attachments`
(rejects zero parents AND rejects two at once), the deliberate CASCADE
exception on `notifications.user_id`, the read/read_at consistency
CHECK, and confirms `audit_logs` genuinely has no trigger at all.

Phase 6: 6 checks confirming the 5 newly added indexes exist and the
tightened `maintenance_tickets` CHECK (a resolved/closed ticket must
have `resolved_at` set) behaves correctly in both directions.

**68 checks total**, all passing against a real local Postgres instance,
confirmed idempotent (seeding twice never duplicates a row).

## Everyday commands

| Task | Command |
|---|---|
| Apply all pending migrations | `alembic upgrade head` |
| Create a new migration by hand | add a file under `database/migrations/versions/`, following `0001_phase1_core.py` |
| Roll back one migration | `alembic downgrade -1` |
| See current migration state | `alembic current` |
| Refresh the schema snapshot | `pg_dump -d imedora --schema-only --no-owner --no-privileges > database/schemas/schema.sql` |

**Note:** migrations here are hand-written, not autogenerated — there's no
ORM model to diff against on purpose (see project notes). `alembic revision
--autogenerate` will not produce anything meaningful in this repo.

## Progress

- **Phase 1 (done):** `organizations`, `hospitals`, `departments`,
  `device_categories`, `manufacturers`, `device_models`, `locations`, `devices`.
- **Phase 2 (done):** `roles`, `users` (added out of necessity - every
  "who did this" column needed a real target), `maintenance_types`,
  `maintenance_schedules`, `maintenance_tickets`, `maintenance_records`,
  `ticket_assignments`. Also added `devices.next_maintenance_due_date`
  (promised back in Phase 1, now that the source table exists).
- **Phase 3 (done):** `parts` (global catalog), `part_inventory`
  (per-hospital stock), `maintenance_parts` (usage line items). A trigger
  keeps `part_inventory.quantity_on_hand` in sync automatically whenever
  `maintenance_parts` rows are inserted, updated, or deleted - stock
  accuracy doesn't depend on the backend remembering to update it.
- **Phase 4 (done):** `risk_assessments`, `qa_records` (unified
  inspection/calibration/compliance table). A trigger keeps
  `devices.current_risk_level` in sync with the most recent assessment
  by date (not insert order), correctly falling back or clearing to NULL
  as assessments are deleted. `risk_factors`/`risk_mitigation_actions`
  from the original ERD are deliberately deferred (classified as a
  future enrichment, not MVP, in the original architecture review).
- **Phase 5 (done):** `attachments` (exactly-one-parent CHECK, no
  polymorphic entity_type/entity_id), `notifications` (the one table
  where `user_id` is `ON DELETE CASCADE` instead of `RESTRICT` -
  notifications have no audit/legal value once the user is gone),
  `audit_logs` (append-only by convention - no `updated_at`, no
  trigger; true immutability via `REVOKE UPDATE, DELETE` is a
  deployment-time hardening step, not baked into the migration since it
  would also block legitimate test/seed cleanup).
- **Phase 6 (done):** a systematic audit of every FK column (58 across
  21 tables) against every index's leading column found and fixed 5
  columns with no usable index (`attachments.hospital_id`,
  `maintenance_schedules.hospital_id`, `notifications.related_ticket_id`,
  `part_inventory.part_id`, `ticket_assignments.ticket_id` - the last one
  had only a *partial* index, which doesn't serve general queries).
  Tightened `maintenance_tickets` with a CHECK that a resolved/closed
  ticket must have `resolved_at` set. Added `run_all.py` orchestrators
  for both seeds and validation, and a second seed device (`DEV-002`)
  with a multi-record maintenance/risk history for demo purposes.

**Database layer status: complete (Phases 1-6).** 22 tables, 6 triggers
(`updated_at` on every table except `audit_logs`, plus the inventory-
adjusting and risk-level-caching triggers), full RESTRICT-by-default
cascade behavior, composite-FK cross-consistency checks, and 68 passing
validation checks. Ready to hand off to the backend team.
