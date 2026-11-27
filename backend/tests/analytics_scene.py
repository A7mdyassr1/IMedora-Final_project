"""B10 test scene: a deterministic dataset for the dashboard & analytics endpoints, against REAL PostgreSQL.

The dataset is plain Python data (DEVICES, TICKETS, RECORDS, SCHEDULES, INVENTORY, QA) that is both
inserted into the database and handed to the tests, which compute every expected number from it with
an independent implementation of the AI package's rules (tests/analytics_oracle.py) - never from SQL.

- Two hospitals of one organization (H1: ICU + Lab, H2: Radiology), plus another organization whose
  rows must never appear.
- Devices in every status, risk level (plus never assessed), criticality, one archived device.
- Tickets with fixed times in March 2025, including database-day edges (the database time zone decides
  the day), cancelled, admin-deleted and archived-device tickets.
- Maintenance records of three types (`preventive`, `corrective`, a third one), schedules due relative
  to the database's today, inventory rows (low, out of stock, no threshold), QA records.

Skipped unless TEST_DATABASE_URL is set. Teardown removes exactly what the scene created, before the
`cat` and `world` fixtures remove devices, users and the organizations.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.database import get_session_factory
from app.core.security import hash_password
from tests.world import PW, auth

CAIRO = timezone(timedelta(hours=2))      # Africa/Cairo in March 2025 (no daylight saving then)


def at(day, hour=10, minute=0, tz=CAIRO):
    return datetime(2025, 3, day, hour, minute, tzinfo=tz) if isinstance(day, int) else day


PERIOD = ("2025-03-01", "2025-03-31")

# key: hospital, department, model, status, criticality, current risk level, archived
DEVICES = {
    "D1": ("h1", "icu", "a", "active", "high", "high", False),
    "D2": ("h1", "icu", "b", "under_maintenance", "medium", None, False),
    "D3": ("h1", "lab", "a", "out_of_service", "critical", "critical", False),
    "D4": ("h1", "lab", "b", "decommissioned", "low", "low", False),
    "D5": ("h1", "icu", "a", "decommissioned", "medium", "medium", True),    # archived
    "E1": ("h2", "rad", "a", "active", "medium", "low", False),
    "E2": ("h2", "rad", "b", "active", "low", None, False),
    "X1": ("oh", "odept", "a", "active", "high", "high", False),              # another organization
}

# key: device, created_at, status, priority, resolved_at, admin-deleted
TICKETS = {
    "T1": ("D1", at(2, 9), "resolved", "high", at(2, 21), False),                    # 12 h
    "T2": ("D1", at(5, 8), "closed", "critical", at(7, 8), False),                    # 48 h
    "T3": ("D1", at(20), "open", "medium", None, False),
    "T4": ("D2", at(10), "in_progress", "low", None, False),
    "T5": ("D3", at(12), "cancelled", "medium", None, False),                         # not a failure
    "T6": ("D3", datetime(2025, 2, 28, 23, 30, tzinfo=timezone.utc), "assigned", "high", None, False),  # 1 Mar in Cairo
    "T7": ("D2", datetime(2025, 3, 31, 22, 30, tzinfo=timezone.utc), "open", "medium", None, False),    # 1 Apr in Cairo
    "T8": ("D1", datetime(2025, 2, 10, 10, tzinfo=CAIRO), "resolved", "medium", at(3, 10), False),     # resolved in March
    "T9": ("D5", at(15), "resolved", "low", at(15, 16), False),                       # archived device (6 h)
    "T10": ("D1", at(16), "open", "high", None, True),                                # admin-deleted: never counted
    "T11": ("D4", at(18), "waiting_for_parts", "medium", None, False),
    "T12": ("D3", at(25, 8), "resolved", "high", at(25, 11, 30), False),              # 3.5 h
    "U1": ("E1", at(8, 8), "resolved", "medium", at(8, 14), False),                   # 6 h
    "U2": ("E2", at(9), "open", "high", None, False),
    "X1": ("X1", at(10), "resolved", "critical", at(10, 11), False),                  # another organization
}

# key: device, type ("preventive" / "corrective" / "other"), performed_at
RECORDS = {
    "R1": ("D1", "corrective", at(3, 9)),
    "R2": ("D1", "corrective", at(6)),
    "R3": ("D2", "preventive", at(11)),
    "R4": ("D3", "other", at(12)),
    "R5": ("D1", "preventive", datetime(2025, 2, 15, 10, tzinfo=CAIRO)),            # before the period
    "R6": ("E1", "corrective", at(8, 15)),
    "R7": ("D5", "preventive", at(15)),                                               # archived device
    "R8": ("D3", "corrective", datetime(2025, 3, 31, 22, 30, tzinfo=timezone.utc)),   # 1 Apr in Cairo
    "R9": ("D3", "corrective", datetime(2025, 2, 28, 22, 30, tzinfo=timezone.utc)),   # 1 Mar in Cairo
    "RX": ("X1", "corrective", at(10)),                                               # another organization
}

# (device, type, next_due_date as days from the database's today, active)
SCHEDULES = [
    ("D1", "preventive", -5, True),      # overdue 5 days
    ("D2", "preventive", 10, True),      # due soon
    ("D3", "preventive", 60, True),      # on track
    ("D3", "other", -3, True),           # overdue, but not preventive
    ("D4", "preventive", -100, True),    # decommissioned device: not evaluated
    ("D5", "preventive", -2, True),      # archived device
    ("E1", "preventive", -1, True),      # overdue 1 day
    ("E2", "preventive", 5, False),      # inactive: no schedule
    ("X1", "preventive", -30, True),     # another organization
]

# (hospital, part, quantity on hand, reorder threshold)
INVENTORY = [
    ("h1", "P1", 2, 5),        # low
    ("h1", "P2", 0, 1),        # low and out of stock
    ("h1", "P3", 10, None),    # no threshold: never low
    ("h2", "P1", 7, 3),
    ("h2", "P2", 3, 3),        # at the threshold: low
    ("oh", "P1", 0, 2),        # another organization
]

# (device, status)
QA = [("D1", "pass"), ("D2", "fail"), ("D3", "pending"), ("E1", "fail"), ("X1", "fail")]


@pytest.fixture
def ana(world, cat, client):
    factory = get_session_factory()
    sfx = world["sfx"]

    def sql(db, statement, **params):
        return db.execute(text(statement), params)

    with factory() as db:
        today = db.scalar(text("SELECT current_date"))
        db_tz = db.scalar(text("SHOW TimeZone"))
        roles = dict(sql(db, "SELECT name, id FROM roles").all())
        hosp = {"h1": world["h1"], "h2": world["h2"], "oh": world["oh"]}
        org_of = {"h1": world["org"], "h2": world["org"], "oh": world["other"]}
        dept = {"icu": world["icu"], "rad": world["rad"]}
        dept["lab"] = str(sql(db, "INSERT INTO departments (hospital_id, name) VALUES (:h, 'Lab') RETURNING id",
                              h=world["h1"]).scalar())
        dept["odept"] = str(sql(db, "INSERT INTO departments (hospital_id, name) VALUES (:h, 'Other Dept') RETURNING id",
                                h=world["oh"]).scalar())
        eng_h2_email = f"eng-h2-{sfx}@b2.test"
        eng_h2 = str(sql(db, "INSERT INTO users (organization_id, hospital_id, role_id, full_name, email, password_hash) "
                             "VALUES (:o, :h, :r, 'Engineer H2', :e, :p) RETURNING id",
                         o=world["org"], h=world["h2"], r=roles["biomedical_engineer"], e=eng_h2_email,
                         p=hash_password(PW)).scalar())
        reporter = {"h1": world["tech_id"], "h2": eng_h2, "oh": world["stranger_id"]}

        # maintenance types: the exact names "preventive" / "corrective" (created only if missing, and then
        # removed again), plus a third type of this run
        types, created_types = {}, []
        for key, name in (("preventive", "preventive"), ("corrective", "corrective"), ("other", f"inspection-{sfx}")):
            tid = sql(db, "SELECT id FROM maintenance_types WHERE name = :n", n=name).scalar()
            if tid is None:
                tid = sql(db, "INSERT INTO maintenance_types (name) VALUES (:n) RETURNING id", n=name).scalar()
                created_types.append(name)
            types[key] = str(tid)

        model = {"a": cat["model_a"], "b": cat["model_b"]}
        dev = {}
        for key, (h, d, m, status, crit, risk, archived) in DEVICES.items():
            dev[key] = str(sql(
                db, "INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id, device_code, name, "
                    "qr_identifier, status, criticality, current_risk_level, deleted_at) VALUES (:o, :h, :d, :m, :c, :n, :q, "
                    "CAST(:s AS device_status), CAST(:cr AS device_criticality), CAST(:r AS risk_level), "
                    "CASE WHEN :a THEN now() END) RETURNING id",
                o=org_of[h], h=hosp[h], d=dept[d], m=model[m], c=f"{key}-{sfx}", n=f"Device {key}",
                q=f"QR-{key}-{sfx}".upper(), s=status, cr=crit, r=risk, a=archived).scalar())
        dev_hosp = {k: v[0] for k, v in DEVICES.items()}

        for key, (d, created, status, priority, resolved, deleted) in TICKETS.items():
            h = dev_hosp[d]
            sql(db, "INSERT INTO maintenance_tickets (organization_id, hospital_id, device_id, reported_by, "
                    "problem_description, priority, status, created_at, resolved_at, deleted_at) VALUES (:o, :h, :d, :u, "
                    ":p, CAST(:pr AS ticket_priority), CAST(:s AS ticket_status), :c, :r, CASE WHEN :x THEN now() END)",
                o=org_of[h], h=hosp[h], d=dev[d], u=reporter[h], p=f"Problem {key}", pr=priority, s=status,
                c=created, r=resolved, x=deleted)
        for key, (d, kind, performed) in RECORDS.items():
            h = dev_hosp[d]
            sql(db, "INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id, "
                    "performed_by, description, performed_at) VALUES (:o, :h, :d, :t, :u, :ds, :pa)",
                o=org_of[h], h=hosp[h], d=dev[d], t=types[kind], u=reporter[h], ds=f"Work {key}", pa=performed)
        for d, kind, offset, active in SCHEDULES:
            h = dev_hosp[d]
            sql(db, "INSERT INTO maintenance_schedules (organization_id, hospital_id, device_id, maintenance_type_id, "
                    "frequency_days, next_due_date, is_active) VALUES (:o, :h, :d, :t, 90, :due, :a)",
                o=org_of[h], h=hosp[h], d=dev[d], t=types[kind], due=today + timedelta(days=offset), a=active)
        part = {}
        for p in ("P1", "P2", "P3"):
            part[p] = str(sql(db, "INSERT INTO parts (name, part_number) VALUES (:n, :pn) RETURNING id",
                              n=f"Part {p} {sfx}", pn=f"PN-{p}-{sfx}").scalar())
        for h, p, qty, threshold in INVENTORY:
            sql(db, "INSERT INTO part_inventory (organization_id, hospital_id, part_id, quantity_on_hand, reorder_threshold) "
                    "VALUES (:o, :h, :p, :q, :t)", o=org_of[h], h=hosp[h], p=part[p], q=qty, t=threshold)
        for d, status in QA:
            h = dev_hosp[d]
            sql(db, "INSERT INTO qa_records (organization_id, hospital_id, device_id, performed_by, record_type, status, "
                    "performed_at) VALUES (:o, :h, :d, :u, 'calibration', CAST(:s AS qa_status), :pa)",
                o=org_of[h], h=hosp[h], d=dev[d], u=reporter[h], s=status, pa=at(14))
        db.commit()

    headers = {"admin": auth(client, world["admin"]), "tech_h1": auth(client, world["tech"]),
               "eng_h2": auth(client, eng_h2_email), "staff": auth(client, world["staff"])}
    yield dict(world=world, today=today, db_tz=db_tz, dev=dev, part=part, dept=dept, types=types, h=headers,
               hosp=hosp, eng_h2=eng_h2, sfx=sfx)

    with factory() as db:
        orgs = [world["org"], world["other"]]
        for table in ("qa_records", "maintenance_records", "maintenance_schedules", "maintenance_tickets", "part_inventory"):
            sql(db, f"DELETE FROM {table} WHERE organization_id = ANY(CAST(:o AS uuid[]))", o=orgs)
        sql(db, "DELETE FROM parts WHERE part_number LIKE :p", p=f"PN-%-{sfx}")
        sql(db, "DELETE FROM maintenance_types WHERE name = :n", n=f"inspection-{sfx}")
        for name in created_types:   # only if nothing else uses them now
            sql(db, "DELETE FROM maintenance_types t WHERE t.name = :n AND NOT EXISTS (SELECT 1 FROM maintenance_records r "
                    "WHERE r.maintenance_type_id = t.id) AND NOT EXISTS (SELECT 1 FROM maintenance_schedules s "
                    "WHERE s.maintenance_type_id = t.id)", n=name)
        db.commit()
