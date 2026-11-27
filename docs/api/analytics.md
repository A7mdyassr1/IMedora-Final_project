# Dashboard & analytics API (B10)

Read-only aggregates for the web dashboard and the AI assistant, under `/api/v1/analytics`. Every number
is computed in PostgreSQL (GROUP BY / aggregate queries) inside the caller's scope. The OpenAPI page
(`/docs`) has the full field lists; this page holds the rules.

## Endpoints

| Endpoint | What it returns |
| --- | --- |
| `GET /analytics/overview` | The dashboard's first screen in one call: devices by status and risk, tickets open now, schedules overdue / due soon, low stock, QA results, and the period's activity (failures, resolutions, MTTR, maintenance, preventive compliance). |
| `GET /analytics/devices` | Devices by status, risk level (plus `unassessed`), criticality, department and category. |
| `GET /analytics/maintenance` | Records performed in the period by type; preventive compliance today, with the most overdue devices. |
| `GET /analytics/tickets` | Tickets created in the period by status, priority and department; failures; resolutions; tickets open now; MTTR. |
| `GET /analytics/problem-devices` | Devices ranked by failures in the period, then corrective maintenance, then device code. |
| `GET /analytics/inventory` | Spare-part stock: rows, parts, units, low stock, out of stock, the emptiest low-stock rows. |
| `GET /analytics/trends` | One metric per day, ISO week or month, every bucket of the period included. |

## Who may call them

| Role | Scope |
| --- | --- |
| `admin` | The whole organization. Only role that may set `include_archived=true`. |
| `biomedical_engineer`, `technician` | Their own hospital. |
| `department_user` | 403 `forbidden` on every endpoint (team decision 2026-11-27, as for the B6 risk and QA summaries). |

- No token: 401. The role is checked before anything is read.
- `include_archived=true` from a non-admin: 403 `forbidden`.
- `hospital_id` and `department_id` only **narrow** the caller's scope; they never widen it. A hospital or
  department outside the scope (another hospital, another organization) gives zeros and empty lists, never
  another hospital's data and never a 404 that would confirm it exists.
- Tickets, maintenance records, schedules and QA records are counted **through their device**: the device's
  organization, hospital, department and archive state decide. A ticket a technician reported on another
  hospital's device (QR) is counted in that device's hospital.
- Stock belongs to a hospital, so `/inventory` (and the overview's `inventory` block) use the B5 inventory
  scope and only `hospital_id` narrows them; `department_id` and `include_archived` do not apply there.

## Common query parameters

| Parameter | Endpoints | Rule |
| --- | --- | --- |
| `hospital_id`, `department_id` | all but `/inventory` (which takes `hospital_id` only) | UUID; narrow the scope. Not a UUID: 422. |
| `include_archived` | all but `/inventory` | Default `false`: archived devices, and their tickets, records, schedules and QA records, are left out. Admins only. |
| `date_from`, `date_to` | overview, maintenance, tickets, problem-devices, trends | Inclusive **database dates** (`YYYY-MM-DD`). Default: the 30 days ending today. `date_from` after `date_to`, or a date outside 1900-01-01 – 2999-12-31: 422 with `details: [{"field": "query.date_from", ...}]`. |
| `due_soon_days` | overview, maintenance | 0–365, default 30. |
| `limit` | maintenance (overdue list, default 20), problem-devices (default 10), inventory (low-stock list, default 20) | 1–100. |
| `min_tickets` | problem-devices | 0–1000, default 0. `min_tickets=2` gives repeated failures. |
| `metric`, `interval` | trends | See below. Other values: 422. |

Errors use the standard envelope (`{"error": {"code", "message", "details"}}`); every validation error is 422
`validation_error`.

### Days and time zones

"A day" is the database's day (its `TimeZone` setting), as for the B6 QA due-date rule. A date filter
becomes the range [`date_from` 00:00, `date_to` + 1 day 00:00) in that time zone, so a ticket created at
23:30 UTC on 28 February counts on 1 March in Africa/Cairo. "Today" is the database's `current_date`.

## Metric rules

The rules are those of the AI package (`ai/services/analytics/metrics.py` on `main`), so the dashboard
and the AI assistant give the same numbers.

- **Failure:** a ticket that is not cancelled. Tickets are counted by `created_at`. Admin-deleted tickets
  never count.
- **MTTR:** hours from `created_at` to `resolved_at` of tickets that are `resolved` or `closed`, bucketed
  by **resolution** date (a ticket reported in February and resolved in March is March's). Mean, median,
  min and max, 2 decimals; `null` when no ticket was resolved.
- **Maintenance:** records counted by `performed_at`. `preventive` / `corrective` work is the maintenance
  type of that name, case-insensitive (the seeds, the bulk data and the AI package use these names); every
  type is also listed by name in `by_type`.
- **Preventive compliance** (today): devices that are not decommissioned, by the due date of their
  **active** preventive schedule: `overdue` (before today), `due_soon` (today to today + `due_soon_days`),
  `on_track` (later), `no_schedule`. `unknown_due_date` is kept for the AI shape and is always 0
  (`next_due_date` is NOT NULL). Rate = (`due_soon` + `on_track`) / scheduled devices, 1 decimal; `null`
  when nothing is scheduled.
- **Schedules due** (overview): active schedules of every type, of devices that are not decommissioned.
- **Problem devices:** devices with a failure or a corrective record in the period, ranked by failures,
  then corrective records, then device code. `total_devices` counts all that qualify, before `limit`.
- **Low stock:** `reorder_threshold` is set and `quantity_on_hand <= reorder_threshold` (B5 rule).
- **Distributions:** every possible value is present (zeros included); percentages of the total, 1
  decimal, `null` when the total is 0. Risk level `unassessed` = no current assessment.

## Trends

`GET /analytics/trends?metric=…&interval=…`

- `metric`: `tickets` (failures, default), `corrective_maintenance`, `preventive_maintenance`,
  `total_maintenance`, `mttr_hours`.
- `interval`: `day` (default), `week` (ISO, from Monday), `month`.
- Default period, ending on `date_to` (default today): 30 days (`day`), 12 weeks from a Monday (`week`),
  12 months from the 1st (`month`).
- Limits (team decision 2026-11-27): at most 366 days for `day`, at most 24 calendar months for `week` and
  `month`; otherwise 422.
- `points`: every bucket of the period, oldest first, empty ones included. A bucket's `start` / `end` are
  cut to the period (the first week of March 2025 is 1–2 March). `value` is the count, or the mean hours
  for `mttr_hours` (`null` when nothing was resolved); `sample_size` is the number of tickets or records
  behind it.

```json
{
  "filters": {"hospital_id": null, "department_id": null, "include_archived": false},
  "metric": "tickets", "interval": "week",
  "period": {"date_from": "2025-03-01", "date_to": "2025-03-31"},
  "points": [
    {"start": "2025-03-01", "end": "2025-03-02", "value": 2, "sample_size": 2},
    {"start": "2025-03-03", "end": "2025-03-09", "value": 3, "sample_size": 3}
  ]
}
```

## Overview example (shortened)

Values from the test dataset (`backend/tests/analytics_scene.py`), administrator, March 2025.

```json
{
  "filters": {"hospital_id": null, "department_id": null, "include_archived": false},
  "period": {"date_from": "2025-03-01", "date_to": "2025-03-31"},
  "devices": {"total": 6, "by_status": {"total": 6, "counts": {"active": 3, "...": 0}, "percentages": {"active": 50.0, "...": 0.0}},
              "by_risk_level": {"...": "..."}},
  "open_tickets": {"by_status": {"...": "..."}, "by_priority": {"...": "..."}},
  "schedules": {"as_of": "2026-11-27", "due_soon_days": 30, "overdue": 3, "due_soon": 1},
  "inventory": {"items_tracked": 5, "low_stock_count": 3, "out_of_stock_count": 1},
  "qa": {"total": 4, "counts": {"pass": 1, "fail": 2, "pending": 1}, "percentages": {"...": "..."}},
  "activity": {"failures": 9, "tickets_resolved": 5, "mttr_hours": 114.7, "maintenance_performed": 6,
               "preventive": 1, "corrective": 4, "preventive_compliance_rate_pct": 50.0}
}
```

## AI assistant mapping

These endpoints cover the statistics the AI package's `BackendDataProvider` needs that B9 listed as
missing: maintenance statistics (`/maintenance`), ticket statistics and MTTR (`/tickets`), inventory
statistics (`/inventory`), problem devices and repeated failures (`/problem-devices`), and trends
(`/trends`). Risk and QA summaries stay on the B6 endpoints (`/risk-assessments/summary`,
`/qa-records/summary`). All of them are GET, so a read-only AI token (B9) may call them, with its user's
role and scope.

## Not in B10

- A device-location filter, period-over-period comparison (the AI package computes it from two calls),
  CSV export.
- No schema change and no migration: every number comes from the Phase 1–6 tables.
