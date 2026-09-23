"""
Phase 6 validation - raw psycopg2, no ORM. Run with:
    python database/tests/validate_phase6.py
"""
import os
import uuid

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")


def connect():
    return psycopg2.connect(DATABASE_URL)


def check(label, fn):
    try:
        fn()
        print(f"[PASS] {label}")
    except AssertionError as e:
        print(f"[FAIL] {label}: {e}")
        raise


EXPECTED_NEW_INDEXES = [
    ("attachments", "ix_attachments_hospital_id"),
    ("maintenance_schedules", "ix_maintenance_schedules_hospital_id"),
    ("notifications", "ix_notifications_related_ticket_id"),
    ("part_inventory", "ix_part_inventory_part_id"),
    ("ticket_assignments", "ix_ticket_assignments_ticket_id"),
]


def main():
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()
    s = {}

    try:
        def t_indexes_exist():
            for table, index_name in EXPECTED_NEW_INDEXES:
                cur.execute(
                    "SELECT COUNT(*) FROM pg_indexes WHERE tablename = %s AND indexname = %s",
                    (table, index_name),
                )
                assert cur.fetchone()[0] == 1, f"{index_name} on {table} is missing"

        check("all 5 Phase 6 indexes exist", t_indexes_exist)

        def t_setup():
            cur.execute("INSERT INTO organizations (name, code) VALUES (%s, %s) RETURNING id",
                        ("Phase6 Org", f"P6-{uuid.uuid4().hex[:8]}"))
            s["org"] = cur.fetchone()[0]
            cur.execute("INSERT INTO hospitals (organization_id, name, code) VALUES (%s, %s, %s) RETURNING id",
                        (s["org"], "Phase6 Hospital", "P6H"))
            s["hosp"] = cur.fetchone()[0]
            cur.execute("INSERT INTO departments (hospital_id, name) VALUES (%s, %s) RETURNING id",
                        (s["hosp"], "ICU"))
            s["dept"] = cur.fetchone()[0]
            cur.execute("INSERT INTO manufacturers (name) VALUES (%s) RETURNING id", (f"Mfr-{uuid.uuid4().hex[:6]}",))
            mfr = cur.fetchone()[0]
            cur.execute("INSERT INTO device_categories (name) VALUES (%s) RETURNING id", (f"Cat-{uuid.uuid4().hex[:6]}",))
            cat = cur.fetchone()[0]
            cur.execute("INSERT INTO device_models (manufacturer_id, device_category_id, name) VALUES (%s,%s,%s) RETURNING id",
                        (mfr, cat, "Model X"))
            model = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id, "
                "device_code, name, qr_identifier) VALUES (%s,%s,%s,%s,'DEV-P6-1','Device','QR-P6-1') RETURNING id",
                (s["org"], s["hosp"], s["dept"], model),
            )
            s["device"] = cur.fetchone()[0]
            cur.execute("INSERT INTO roles (name) VALUES (%s) RETURNING id", (f"engineer-{uuid.uuid4().hex[:6]}",))
            role = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO users (organization_id, hospital_id, role_id, full_name, email, password_hash) "
                "VALUES (%s,%s,%s,'Engineer','eng-{}@example.com','x') RETURNING id".format(uuid.uuid4().hex[:6]),
                (s["org"], s["hosp"], role),
            )
            s["user"] = cur.fetchone()[0]
            conn.commit()

        check("set up organization/hospital/device/user", t_setup)

        def t_resolved_without_timestamp_rejected():
            try:
                cur.execute(
                    "INSERT INTO maintenance_tickets (organization_id, hospital_id, device_id, reported_by, "
                    "problem_description, status) VALUES (%s,%s,%s,%s,'test','resolved')",
                    (s["org"], s["hosp"], s["device"], s["user"]),
                )
                conn.commit()
                raise AssertionError("a 'resolved' ticket with no resolved_at was allowed")
            except psycopg2.errors.CheckViolation:
                conn.rollback()

        check("CHECK constraint rejects a resolved/closed ticket with no resolved_at", t_resolved_without_timestamp_rejected)

        def t_resolved_with_timestamp_ok():
            cur.execute(
                "INSERT INTO maintenance_tickets (organization_id, hospital_id, device_id, reported_by, "
                "problem_description, status, resolved_at) VALUES (%s,%s,%s,%s,'test','resolved',now()) RETURNING id",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            s["ticket"] = cur.fetchone()[0]
            conn.commit()

        check("a resolved ticket WITH resolved_at is accepted", t_resolved_with_timestamp_ok)

        def t_open_ticket_without_timestamp_still_ok():
            cur.execute(
                "INSERT INTO maintenance_tickets (organization_id, hospital_id, device_id, reported_by, "
                "problem_description, status) VALUES (%s,%s,%s,%s,'still open','open') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            conn.commit()

        check("an 'open' ticket with no resolved_at is still accepted (constraint only applies to resolved/closed)", t_open_ticket_without_timestamp_still_ok)

        def t_teardown():
            cur.execute("DELETE FROM maintenance_tickets WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM devices WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM users WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM departments WHERE hospital_id = %s", (s["hosp"],))
            cur.execute("DELETE FROM hospitals WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM organizations WHERE id = %s", (s["org"],))
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM organizations WHERE id = %s", (s["org"],))
            assert cur.fetchone()[0] == 0

        check("test data cleaned up bottom-up (no leftover rows after validation)", t_teardown)

        print("\nAll Phase 6 validation checks passed.")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
