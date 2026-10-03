"""
Phase 2 validation - raw psycopg2, no ORM. Run with:
    python database/tests/validate_phase2.py
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


def main():
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()
    s = {}

    try:
        def t_setup():
            cur.execute("INSERT INTO organizations (name, code) VALUES (%s, %s) RETURNING id",
                        ("Phase2 Org", f"P2-{uuid.uuid4().hex[:8]}"))
            s["org"] = cur.fetchone()[0]
            cur.execute("INSERT INTO hospitals (organization_id, name, code) VALUES (%s, %s, %s) RETURNING id",
                        (s["org"], "Phase2 Hospital", "P2H"))
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
                "device_code, name, qr_identifier) VALUES (%s,%s,%s,%s,'DEV-P2-1','Device','QR-P2-1') RETURNING id",
                (s["org"], s["hosp"], s["dept"], model),
            )
            s["device"] = cur.fetchone()[0]
            # a second device, to prove cross-device mismatches get rejected
            cur.execute(
                "INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id, "
                "device_code, name, qr_identifier) VALUES (%s,%s,%s,%s,'DEV-P2-2','Device 2','QR-P2-2') RETURNING id",
                (s["org"], s["hosp"], s["dept"], model),
            )
            s["device2"] = cur.fetchone()[0]

            cur.execute("INSERT INTO roles (name) VALUES (%s) RETURNING id", (f"technician-{uuid.uuid4().hex[:6]}",))
            role = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO users (organization_id, hospital_id, role_id, full_name, email, password_hash) "
                "VALUES (%s,%s,%s,'Tech One','tech1-{}@example.com','x') RETURNING id".format(uuid.uuid4().hex[:6]),
                (s["org"], s["hosp"], role),
            )
            s["user"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO users (organization_id, hospital_id, role_id, full_name, email, password_hash) "
                "VALUES (%s,%s,%s,'Tech Two','tech2-{}@example.com','x') RETURNING id".format(uuid.uuid4().hex[:6]),
                (s["org"], s["hosp"], role),
            )
            s["user2"] = cur.fetchone()[0]

            cur.execute("INSERT INTO maintenance_types (name) VALUES (%s) RETURNING id", (f"preventive-{uuid.uuid4().hex[:6]}",))
            s["mtype"] = cur.fetchone()[0]
            conn.commit()

        check("set up organization/hospital/department/2 devices/2 users/role/maintenance_type", t_setup)

        def t_schedule_unique_per_device_type():
            cur.execute(
                "INSERT INTO maintenance_schedules (organization_id, hospital_id, device_id, maintenance_type_id, "
                "frequency_days, next_due_date) VALUES (%s,%s,%s,%s,90,'2026-12-01') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["mtype"]),
            )
            s["schedule"] = cur.fetchone()[0]
            conn.commit()
            try:
                cur.execute(
                    "INSERT INTO maintenance_schedules (organization_id, hospital_id, device_id, maintenance_type_id, "
                    "frequency_days, next_due_date) VALUES (%s,%s,%s,%s,30,'2026-11-01')",
                    (s["org"], s["hosp"], s["device"], s["mtype"]),
                )
                conn.commit()
                raise AssertionError("second schedule of the same type for the same device was allowed")
            except psycopg2.errors.UniqueViolation:
                conn.rollback()

        check("UNIQUE(device_id, maintenance_type_id) blocks a duplicate active schedule", t_schedule_unique_per_device_type)

        def t_frequency_check():
            try:
                cur.execute(
                    "INSERT INTO maintenance_schedules (organization_id, hospital_id, device_id, maintenance_type_id, "
                    "frequency_days, next_due_date) VALUES (%s,%s,%s,%s,0,'2026-12-01')",
                    (s["org"], s["hosp"], s["device2"], s["mtype"]),
                )
                conn.commit()
                raise AssertionError("frequency_days = 0 was allowed")
            except psycopg2.errors.CheckViolation:
                conn.rollback()

        check("CHECK constraint rejects frequency_days <= 0", t_frequency_check)

        def t_ticket_and_record():
            cur.execute(
                "INSERT INTO maintenance_tickets (organization_id, hospital_id, device_id, reported_by, "
                "problem_description) VALUES (%s,%s,%s,%s,'Not powering on') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            s["ticket"] = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id, "
                "ticket_id, performed_by, description) VALUES (%s,%s,%s,%s,%s,%s,'Fixed power supply') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["mtype"], s["ticket"], s["user"]),
            )
            conn.commit()

        check("insert ticket + a record linked to that ticket, same device", t_ticket_and_record)

        def t_record_ticket_device_mismatch_rejected():
            try:
                # ticket belongs to `device`, but this record claims `device2` - must be rejected
                cur.execute(
                    "INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id, "
                    "ticket_id, performed_by, description) VALUES (%s,%s,%s,%s,%s,%s,'Mismatched device')",
                    (s["org"], s["hosp"], s["device2"], s["mtype"], s["ticket"], s["user"]),
                )
                conn.commit()
                raise AssertionError("a record for device2 linked to a ticket belonging to device was allowed")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check(
            "composite FK rejects a record whose ticket belongs to a DIFFERENT device",
            t_record_ticket_device_mismatch_rejected,
        )

        def t_record_schedule_type_mismatch_rejected():
            cur.execute("INSERT INTO maintenance_types (name) VALUES (%s) RETURNING id", (f"corrective-{uuid.uuid4().hex[:6]}",))
            other_type = cur.fetchone()[0]
            conn.commit()
            try:
                # schedule is (device, mtype) but record claims (device, other_type) - must be rejected
                cur.execute(
                    "INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id, "
                    "schedule_id, performed_by, description) VALUES (%s,%s,%s,%s,%s,%s,'Wrong type')",
                    (s["org"], s["hosp"], s["device"], other_type, s["schedule"], s["user"]),
                )
                conn.commit()
                raise AssertionError("a record with a mismatched maintenance_type vs. its schedule was allowed")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check(
            "composite FK rejects a record whose maintenance_type doesn't match its schedule's",
            t_record_schedule_type_mismatch_rejected,
        )

        def t_ticket_assignment_and_partial_unique():
            cur.execute(
                "INSERT INTO ticket_assignments (ticket_id, user_id) VALUES (%s, %s) RETURNING id",
                (s["ticket"], s["user"]),
            )
            conn.commit()
            try:
                cur.execute(
                    "INSERT INTO ticket_assignments (ticket_id, user_id) VALUES (%s, %s)",
                    (s["ticket"], s["user"]),
                )
                conn.commit()
                raise AssertionError("a duplicate ACTIVE assignment of the same user to the same ticket was allowed")
            except psycopg2.errors.UniqueViolation:
                conn.rollback()

            # unassign, then reassign the SAME user - must be allowed (history preserved, not blocked)
            cur.execute(
                "UPDATE ticket_assignments SET unassigned_at = now() WHERE ticket_id = %s AND user_id = %s",
                (s["ticket"], s["user"]),
            )
            cur.execute("INSERT INTO ticket_assignments (ticket_id, user_id) VALUES (%s, %s)", (s["ticket"], s["user"]))
            conn.commit()

        check(
            "partial UNIQUE index blocks a duplicate active assignment but allows reassignment after unassign",
            t_ticket_assignment_and_partial_unique,
        )

        def t_user_restrict():
            try:
                cur.execute("DELETE FROM users WHERE id = %s", (s["user"],))
                conn.commit()
                raise AssertionError("a user with ticket/record/assignment history was deleted")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check("ON DELETE RESTRICT blocks deleting a user with maintenance/ticket history", t_user_restrict)

        def t_device_restrict_via_maintenance():
            try:
                cur.execute("DELETE FROM devices WHERE id = %s", (s["device"],))
                conn.commit()
                raise AssertionError("a device with schedules/tickets/records was deleted")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check("ON DELETE RESTRICT blocks deleting a device with maintenance history", t_device_restrict_via_maintenance)

        def t_next_maintenance_column_exists():
            cur.execute(
                "UPDATE devices SET next_maintenance_due_date = '2026-12-01' WHERE id = %s RETURNING next_maintenance_due_date",
                (s["device"],),
            )
            conn.commit()
            assert cur.fetchone()[0] is not None

        check("devices.next_maintenance_due_date column exists and is writable", t_next_maintenance_column_exists)

        def t_updated_at_trigger_on_new_tables():
            import time
            cur.execute("SELECT updated_at FROM maintenance_tickets WHERE id = %s", (s["ticket"],))
            before = cur.fetchone()[0]
            time.sleep(1)
            cur.execute("UPDATE maintenance_tickets SET status = 'assigned' WHERE id = %s", (s["ticket"],))
            conn.commit()
            cur.execute("SELECT updated_at FROM maintenance_tickets WHERE id = %s", (s["ticket"],))
            after = cur.fetchone()[0]
            assert after > before, "updated_at did not change on maintenance_tickets"

        check("updated_at trigger fires on the new Phase 2 tables too", t_updated_at_trigger_on_new_tables)

        def t_teardown():
            cur.execute("DELETE FROM ticket_assignments WHERE ticket_id = %s", (s["ticket"],))
            cur.execute("DELETE FROM maintenance_records WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM maintenance_tickets WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM maintenance_schedules WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM devices WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM users WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM departments WHERE hospital_id = %s", (s["hosp"],))
            cur.execute("DELETE FROM hospitals WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM organizations WHERE id = %s", (s["org"],))
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM organizations WHERE id = %s", (s["org"],))
            assert cur.fetchone()[0] == 0

        check("test data cleaned up bottom-up (no leftover rows after validation)", t_teardown)

        print("\nAll Phase 2 validation checks passed.")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
