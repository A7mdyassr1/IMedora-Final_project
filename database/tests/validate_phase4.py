"""
Phase 4 validation - raw psycopg2, no ORM. Run with:
    python database/tests/validate_phase4.py
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

    def current_risk():
        cur.execute("SELECT current_risk_level FROM devices WHERE id = %s", (s["device"],))
        return cur.fetchone()[0]

    try:
        def t_setup():
            cur.execute("INSERT INTO organizations (name, code) VALUES (%s, %s) RETURNING id",
                        ("Phase4 Org", f"P4-{uuid.uuid4().hex[:8]}"))
            s["org"] = cur.fetchone()[0]
            cur.execute("INSERT INTO hospitals (organization_id, name, code) VALUES (%s, %s, %s) RETURNING id",
                        (s["org"], "Phase4 Hospital", "P4H"))
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
                "device_code, name, qr_identifier) VALUES (%s,%s,%s,%s,'DEV-P4-1','Device','QR-P4-1') RETURNING id",
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

        def t_no_assessments_yet():
            assert current_risk() is None, "current_risk_level should start NULL with no assessments"

        check("devices.current_risk_level starts NULL before any assessment exists", t_no_assessments_yet)

        def t_first_assessment_sets_cache():
            cur.execute(
                "INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level, "
                "assessed_at) VALUES (%s,%s,%s,%s,'medium','2026-01-01') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            s["assess1"] = cur.fetchone()[0]
            conn.commit()
            assert current_risk() == "medium"

        check("first risk assessment sets devices.current_risk_level", t_first_assessment_sets_cache)

        def t_newer_assessment_updates_cache():
            cur.execute(
                "INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level, "
                "assessed_at) VALUES (%s,%s,%s,%s,'critical','2026-03-01') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            s["assess2"] = cur.fetchone()[0]
            conn.commit()
            assert current_risk() == "critical"

        check("a NEWER assessment (by date) updates the cache to its level", t_newer_assessment_updates_cache)

        def t_backdated_assessment_does_not_override():
            cur.execute(
                "INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level, "
                "assessed_at) VALUES (%s,%s,%s,%s,'low','2025-06-01')",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            conn.commit()
            assert current_risk() == "critical", "a backdated assessment incorrectly overrode the latest one"

        check(
            "a BACKDATED assessment does NOT override the cache (recompute-by-date, not by insert order)",
            t_backdated_assessment_does_not_override,
        )

        def t_delete_latest_falls_back():
            cur.execute("DELETE FROM risk_assessments WHERE id = %s", (s["assess2"],))
            conn.commit()
            assert current_risk() == "medium", "deleting the latest assessment should fall back to the next one"

        check("deleting the latest assessment falls back to the next most recent", t_delete_latest_falls_back)

        def t_delete_all_clears_cache():
            cur.execute("DELETE FROM risk_assessments WHERE device_id = %s", (s["device"],))
            conn.commit()
            assert current_risk() is None, "current_risk_level should be NULL once all assessments are gone"

        check("deleting ALL assessments clears the cache back to NULL", t_delete_all_clears_cache)

        def t_user_restrict_via_assessment():
            cur.execute(
                "INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level) "
                "VALUES (%s,%s,%s,%s,'high') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            s["assess3"] = cur.fetchone()[0]
            conn.commit()
            try:
                cur.execute("DELETE FROM users WHERE id = %s", (s["user"],))
                conn.commit()
                raise AssertionError("a user with a risk assessment on file was deleted")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check("ON DELETE RESTRICT blocks deleting a user who performed a risk assessment", t_user_restrict_via_assessment)

        def t_device_restrict_via_assessment():
            try:
                cur.execute("DELETE FROM devices WHERE id = %s", (s["device"],))
                conn.commit()
                raise AssertionError("a device with a risk assessment was deleted")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check("ON DELETE RESTRICT blocks deleting a device with a risk assessment", t_device_restrict_via_assessment)

        def t_qa_record_insert():
            cur.execute(
                "INSERT INTO qa_records (organization_id, hospital_id, device_id, performed_by, record_type, "
                "status, performed_at, next_due_date) "
                "VALUES (%s,%s,%s,%s,'calibration','pass','2026-01-01','2026-07-01') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["user"]),
            )
            s["qa"] = cur.fetchone()[0]
            conn.commit()

        check("insert a qa_records row (calibration, pass)", t_qa_record_insert)

        def t_qa_next_due_check():
            try:
                cur.execute(
                    "INSERT INTO qa_records (organization_id, hospital_id, device_id, performed_by, record_type, "
                    "status, performed_at, next_due_date) "
                    "VALUES (%s,%s,%s,%s,'inspection','pass','2026-01-01','2025-01-01')",
                    (s["org"], s["hosp"], s["device"], s["user"]),
                )
                conn.commit()
                raise AssertionError("next_due_date before performed_at was allowed")
            except psycopg2.errors.CheckViolation:
                conn.rollback()

        check("CHECK constraint rejects a qa_records next_due_date before performed_at", t_qa_next_due_check)

        def t_updated_at_on_qa():
            import time
            cur.execute("SELECT updated_at FROM qa_records WHERE id = %s", (s["qa"],))
            before = cur.fetchone()[0]
            time.sleep(1)
            cur.execute("UPDATE qa_records SET status = 'fail' WHERE id = %s", (s["qa"],))
            conn.commit()
            cur.execute("SELECT updated_at FROM qa_records WHERE id = %s", (s["qa"],))
            after = cur.fetchone()[0]
            assert after > before

        check("updated_at trigger fires on qa_records", t_updated_at_on_qa)

        def t_teardown():
            cur.execute("DELETE FROM qa_records WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM risk_assessments WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM devices WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM users WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM departments WHERE hospital_id = %s", (s["hosp"],))
            cur.execute("DELETE FROM hospitals WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM organizations WHERE id = %s", (s["org"],))
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM organizations WHERE id = %s", (s["org"],))
            assert cur.fetchone()[0] == 0

        check("test data cleaned up bottom-up (no leftover rows after validation)", t_teardown)

        print("\nAll Phase 4 validation checks passed.")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
