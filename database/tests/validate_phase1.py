"""
Phase 1 validation - exercises the schema directly with psycopg2 (no ORM).

Run with:
    python database/tests/validate_phase1.py

Each check either passes or raises AssertionError with a clear message.
Re-run after every migration change in this phase.
"""
import os
import time
import uuid

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]
PSYCOPG2_DSN = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")


def connect():
    return psycopg2.connect(PSYCOPG2_DSN)


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

    state = {}

    try:
        # 1. Basic insert down the full hierarchy works.
        def t_insert_hierarchy():
            cur.execute(
                "INSERT INTO organizations (name, code) VALUES (%s, %s) RETURNING id",
                ("Validation Org", f"VAL-{uuid.uuid4().hex[:8]}"),
            )
            state["org_id"] = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO hospitals (organization_id, name, code) VALUES (%s, %s, %s) RETURNING id",
                (state["org_id"], "Validation Hospital", "VH1"),
            )
            state["hosp_id"] = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO departments (hospital_id, name) VALUES (%s, %s) RETURNING id",
                (state["hosp_id"], "ICU"),
            )
            state["dept_id"] = cur.fetchone()[0]

            cur.execute("INSERT INTO manufacturers (name) VALUES (%s) RETURNING id", (f"Philips-{uuid.uuid4().hex[:6]}",))
            manufacturer_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO device_categories (name) VALUES (%s) RETURNING id", (f"Ventilator-{uuid.uuid4().hex[:6]}",)
            )
            category_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO device_models (manufacturer_id, device_category_id, name) VALUES (%s, %s, %s) RETURNING id",
                (manufacturer_id, category_id, "Efficia CM10"),
            )
            state["model_id"] = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id,
                                      device_code, name, qr_identifier)
                VALUES (%s, %s, %s, %s, 'DEV-001', 'Test device', 'QR-1') RETURNING id
                """,
                (state["org_id"], state["hosp_id"], state["dept_id"], state["model_id"]),
            )
            state["device_id"] = cur.fetchone()[0]
            conn.commit()

        check("insert full organization -> hospital -> department -> device chain", t_insert_hierarchy)

        # 2. device_code unique PER HOSPITAL, not globally.
        def t_device_code_scoped_per_hospital():
            cur.execute(
                "INSERT INTO hospitals (organization_id, name, code) VALUES (%s, %s, %s) RETURNING id",
                (state["org_id"], "Second Hospital", "VH2"),
            )
            state["hosp2_id"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO departments (hospital_id, name) VALUES (%s, %s) RETURNING id",
                (state["hosp2_id"], "Radiology"),
            )
            state["dept2_id"] = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id,
                                      device_code, name, qr_identifier)
                VALUES (%s, %s, %s, %s, 'DEV-001', 'Test device 2', 'QR-2')
                """,
                (state["org_id"], state["hosp2_id"], state["dept2_id"], state["model_id"]),
            )
            conn.commit()

        check("device_code 'DEV-001' allowed in a second hospital", t_device_code_scoped_per_hospital)

        # 3. But NOT twice in the SAME hospital.
        def t_device_code_unique_within_hospital():
            try:
                cur.execute(
                    """
                    INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id,
                                          device_code, name, qr_identifier)
                    VALUES (%s, %s, %s, %s, 'DEV-001', 'Duplicate', 'QR-DUP')
                    """,
                    (state["org_id"], state["hosp_id"], state["dept_id"], state["model_id"]),
                )
                conn.commit()
                raise AssertionError("duplicate device_code in the same hospital was NOT rejected")
            except psycopg2.errors.UniqueViolation:
                conn.rollback()

        check("device_code rejected as duplicate within the SAME hospital", t_device_code_unique_within_hospital)

        # 4. qr_identifier globally unique, even across different hospitals.
        def t_qr_identifier_globally_unique():
            try:
                cur.execute(
                    """
                    INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id,
                                          device_code, name, qr_identifier)
                    VALUES (%s, %s, %s, %s, 'DEV-999', 'Different device', 'QR-1')
                    """,
                    (state["org_id"], state["hosp2_id"], state["dept2_id"], state["model_id"]),
                )
                conn.commit()
                raise AssertionError("duplicate qr_identifier across hospitals was NOT rejected")
            except psycopg2.errors.UniqueViolation:
                conn.rollback()

        check("qr_identifier rejected as duplicate even across different hospitals", t_qr_identifier_globally_unique)

        # 5. CHECK constraint: warranty_expiry must be >= installation_date.
        def t_warranty_check_constraint():
            try:
                cur.execute(
                    """
                    INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id,
                                          device_code, name, qr_identifier, installation_date, warranty_expiry)
                    VALUES (%s, %s, %s, %s, 'DEV-BAD-DATE', 'Bad date device', 'QR-BAD-DATE', '2026-01-01', '2020-01-01')
                    """,
                    (state["org_id"], state["hosp_id"], state["dept_id"], state["model_id"]),
                )
                conn.commit()
                raise AssertionError("warranty_expiry before installation_date was NOT rejected")
            except psycopg2.errors.CheckViolation:
                conn.rollback()

        check("CHECK constraint rejects warranty_expiry before installation_date", t_warranty_check_constraint)

        # 6. ON DELETE RESTRICT: can't delete a department that still has devices.
        def t_department_restrict():
            try:
                cur.execute("DELETE FROM departments WHERE id = %s", (state["dept_id"],))
                conn.commit()
                raise AssertionError("department with devices was deleted (should be RESTRICTed)")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check("ON DELETE RESTRICT blocks deleting a department that still has devices", t_department_restrict)

        # 7. ON DELETE RESTRICT: can't delete a hospital while its devices still
        #    point at it directly (the denormalized devices.hospital_id FK).
        def t_hospital_restrict_via_devices():
            try:
                cur.execute("DELETE FROM hospitals WHERE id = %s", (state["hosp_id"],))
                conn.commit()
                raise AssertionError("hospital with devices was deleted (should be RESTRICTed)")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check(
            "ON DELETE RESTRICT blocks deleting a hospital while devices reference it directly",
            t_hospital_restrict_via_devices,
        )

        # 8. ON DELETE RESTRICT: can't delete the organization while its devices
        #    still point at it directly (the denormalized devices.organization_id
        #    FK) - this is the exact bypass that used to be CASCADE.
        def t_organization_restrict_via_devices():
            try:
                cur.execute("DELETE FROM organizations WHERE id = %s", (state["org_id"],))
                conn.commit()
                raise AssertionError("organization with devices was deleted (should be RESTRICTed)")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check(
            "ON DELETE RESTRICT blocks deleting an organization while devices reference it directly",
            t_organization_restrict_via_devices,
        )

        # 9. ON DELETE RESTRICT: hospital -> department, isolated from devices.
        #    A hospital with a department but NO devices should still block
        #    hospital deletion, proving the hospital->department FK itself
        #    (not just the devices FK) is enforcing RESTRICT.
        def t_hospital_restrict_via_empty_department():
            cur.execute(
                "INSERT INTO hospitals (organization_id, name, code) VALUES (%s, %s, %s) RETURNING id",
                (state["org_id"], "Empty Hospital", "VH-EMPTY"),
            )
            empty_hosp_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO departments (hospital_id, name) VALUES (%s, 'Empty Dept')", (empty_hosp_id,)
            )
            conn.commit()
            try:
                cur.execute("DELETE FROM hospitals WHERE id = %s", (empty_hosp_id,))
                conn.commit()
                raise AssertionError("hospital with an (device-less) department was deleted")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()
            # clean up properly, bottom-up
            cur.execute("DELETE FROM departments WHERE hospital_id = %s", (empty_hosp_id,))
            cur.execute("DELETE FROM hospitals WHERE id = %s", (empty_hosp_id,))
            conn.commit()

        check(
            "ON DELETE RESTRICT blocks deleting a hospital with an empty department (isolated from devices)",
            t_hospital_restrict_via_empty_department,
        )

        # 10. SET NULL still works: deleting a location clears devices.location_id
        #     instead of deleting the device.
        def t_location_set_null():
            cur.execute(
                "INSERT INTO locations (hospital_id, building, floor, room) VALUES (%s, 'A', '1', '101') RETURNING id",
                (state["hosp_id"],),
            )
            loc_id = cur.fetchone()[0]
            cur.execute("UPDATE devices SET location_id = %s WHERE id = %s", (loc_id, state["device_id"]))
            conn.commit()
            cur.execute("DELETE FROM locations WHERE id = %s", (loc_id,))
            conn.commit()
            cur.execute("SELECT location_id FROM devices WHERE id = %s", (state["device_id"],))
            assert cur.fetchone()[0] is None, "device.location_id was not set NULL after location deletion"

        check("ON DELETE SET NULL clears devices.location_id without deleting the device", t_location_set_null)

        # 11. updated_at trigger actually fires on UPDATE.
        def t_updated_at_trigger():
            cur.execute(
                "INSERT INTO organizations (name, code) VALUES (%s, %s) RETURNING id, updated_at",
                ("Trigger Test Org", f"TRG-{uuid.uuid4().hex[:8]}"),
            )
            new_id, original_updated_at = cur.fetchone()
            conn.commit()
            time.sleep(1)
            cur.execute("UPDATE organizations SET name = 'Renamed' WHERE id = %s", (new_id,))
            conn.commit()
            cur.execute("SELECT updated_at FROM organizations WHERE id = %s", (new_id,))
            new_updated_at = cur.fetchone()[0]
            assert new_updated_at > original_updated_at, "updated_at did not change after UPDATE"
            cur.execute("DELETE FROM organizations WHERE id = %s", (new_id,))
            conn.commit()

        check("updated_at trigger fires automatically on UPDATE", t_updated_at_trigger)

        # 12. The correct decommission order actually works end to end:
        #     devices -> departments -> hospitals -> organization, bottom-up.
        def t_full_bottom_up_teardown_succeeds():
            cur.execute("DELETE FROM devices WHERE organization_id = %s", (state["org_id"],))
            cur.execute("DELETE FROM departments WHERE hospital_id IN (%s, %s)", (state["hosp_id"], state["hosp2_id"]))
            cur.execute("DELETE FROM hospitals WHERE organization_id = %s", (state["org_id"],))
            cur.execute("DELETE FROM organizations WHERE id = %s", (state["org_id"],))
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM organizations WHERE id = %s", (state["org_id"],))
            assert cur.fetchone()[0] == 0

        check(
            "explicit bottom-up teardown (devices -> departments -> hospitals -> org) succeeds",
            t_full_bottom_up_teardown_succeeds,
        )

        print("\nAll Phase 1 validation checks passed.")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
