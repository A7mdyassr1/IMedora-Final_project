"""
Phase 5 validation - raw psycopg2, no ORM. Run with:
    python database/tests/validate_phase5.py
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
                        ("Phase5 Org", f"P5-{uuid.uuid4().hex[:8]}"))
            s["org"] = cur.fetchone()[0]
            cur.execute("INSERT INTO hospitals (organization_id, name, code) VALUES (%s, %s, %s) RETURNING id",
                        (s["org"], "Phase5 Hospital", "P5H"))
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
                "device_code, name, qr_identifier) VALUES (%s,%s,%s,%s,'DEV-P5-1','Device','QR-P5-1') RETURNING id",
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

        def t_attachment_with_one_parent_ok():
            cur.execute(
                "INSERT INTO attachments (organization_id, hospital_id, device_id, uploaded_by, file_url) "
                "VALUES (%s,%s,%s,%s,'https://example.com/photo.jpg') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            s["attachment"] = cur.fetchone()[0]
            conn.commit()

        check("insert an attachment with exactly one parent (device) - allowed", t_attachment_with_one_parent_ok)

        def t_attachment_zero_parents_rejected():
            try:
                cur.execute(
                    "INSERT INTO attachments (organization_id, hospital_id, uploaded_by, file_url) "
                    "VALUES (%s,%s,%s,'https://example.com/orphan.jpg')",
                    (s["org"], s["hosp"], s["user"]),
                )
                conn.commit()
                raise AssertionError("an attachment with NO parent was allowed")
            except psycopg2.errors.CheckViolation:
                conn.rollback()

        check("CHECK constraint rejects an attachment with zero parents", t_attachment_zero_parents_rejected)

        def t_attachment_two_parents_rejected():
            cur.execute(
                "INSERT INTO maintenance_types (name) VALUES (%s) RETURNING id", (f"corrective-{uuid.uuid4().hex[:6]}",)
            )
            mtype = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO maintenance_tickets (organization_id, hospital_id, device_id, reported_by, "
                "problem_description) VALUES (%s,%s,%s,%s,'test') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            ticket = cur.fetchone()[0]
            conn.commit()
            try:
                cur.execute(
                    "INSERT INTO attachments (organization_id, hospital_id, device_id, ticket_id, uploaded_by, file_url) "
                    "VALUES (%s,%s,%s,%s,%s,'https://example.com/both.jpg')",
                    (s["org"], s["hosp"], s["device"], ticket, s["user"]),
                )
                conn.commit()
                raise AssertionError("an attachment with TWO parents was allowed")
            except psycopg2.errors.CheckViolation:
                conn.rollback()
            s["ticket"] = ticket
            s["mtype"] = mtype

        check("CHECK constraint rejects an attachment with two parents set at once", t_attachment_two_parents_rejected)

        def t_device_restrict_via_attachment():
            try:
                cur.execute("DELETE FROM devices WHERE id = %s", (s["device"],))
                conn.commit()
                raise AssertionError("a device with an attachment was deleted")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check("ON DELETE RESTRICT blocks deleting a device with an attachment", t_device_restrict_via_attachment)

        def t_notification_cascade_on_user_delete():
            cur.execute(
                "INSERT INTO users (organization_id, hospital_id, role_id, full_name, email, password_hash) "
                "VALUES (%s,%s,(SELECT role_id FROM users WHERE id = %s),'Throwaway','throwaway-{}@example.com','x') "
                "RETURNING id".format(uuid.uuid4().hex[:6]),
                (s["org"], s["hosp"], s["user"]),
            )
            throwaway_user = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO notifications (organization_id, user_id, title) VALUES (%s,%s,'Test notification') RETURNING id",
                (s["org"], throwaway_user),
            )
            notif_id = cur.fetchone()[0]
            conn.commit()
            cur.execute("DELETE FROM users WHERE id = %s", (throwaway_user,))
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM notifications WHERE id = %s", (notif_id,))
            assert cur.fetchone()[0] == 0, "notification survived its user being deleted - CASCADE isn't working"

        check(
            "notifications.user_id CASCADEs (the one deliberate exception to the RESTRICT-everywhere pattern)",
            t_notification_cascade_on_user_delete,
        )

        def t_notification_read_check():
            try:
                cur.execute(
                    "INSERT INTO notifications (organization_id, user_id, title, is_read) VALUES (%s,%s,'Bad',true)",
                    (s["org"], s["user"]),
                )
                conn.commit()
                raise AssertionError("is_read=true with no read_at was allowed")
            except psycopg2.errors.CheckViolation:
                conn.rollback()

        check("CHECK constraint rejects is_read=true without a read_at timestamp", t_notification_read_check)

        def t_audit_log_insert_and_restrict():
            cur.execute(
                "INSERT INTO audit_logs (organization_id, user_id, table_name, record_id, action, new_values) "
                "VALUES (%s,%s,'devices',%s,'update','{\"status\": \"active\"}') RETURNING id",
                (s["org"], s["user"], s["device"]),
            )
            s["audit"] = cur.fetchone()[0]
            conn.commit()
            try:
                cur.execute("DELETE FROM users WHERE id = %s", (s["user"],))
                conn.commit()
                raise AssertionError("a user with an audit log entry was deleted")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check("audit_logs insert works, and RESTRICT protects the acting user from deletion", t_audit_log_insert_and_restrict)

        def t_audit_log_has_no_update_trigger():
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.triggers WHERE event_object_table = 'audit_logs'"
            )
            assert cur.fetchone()[0] == 0, "audit_logs should have NO triggers (it's append-only by convention)"

        check("audit_logs has no updated_at trigger (append-only by convention)", t_audit_log_has_no_update_trigger)

        def t_teardown():
            cur.execute("DELETE FROM audit_logs WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM notifications WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM attachments WHERE organization_id = %s", (s["org"],))
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

        print("\nAll Phase 5 validation checks passed.")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
