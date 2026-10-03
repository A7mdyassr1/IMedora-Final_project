"""
Phase 3 validation - raw psycopg2, no ORM. Run with:
    python database/tests/validate_phase3.py
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

    def stock():
        cur.execute("SELECT quantity_on_hand FROM part_inventory WHERE id = %s", (s["inv"],))
        return cur.fetchone()[0]

    try:
        def t_setup():
            cur.execute("INSERT INTO organizations (name, code) VALUES (%s, %s) RETURNING id",
                        ("Phase3 Org", f"P3-{uuid.uuid4().hex[:8]}"))
            s["org"] = cur.fetchone()[0]
            cur.execute("INSERT INTO hospitals (organization_id, name, code) VALUES (%s, %s, %s) RETURNING id",
                        (s["org"], "Phase3 Hospital", "P3H"))
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
                "device_code, name, qr_identifier) VALUES (%s,%s,%s,%s,'DEV-P3-1','Device','QR-P3-1') RETURNING id",
                (s["org"], s["hosp"], s["dept"], model),
            )
            s["device"] = cur.fetchone()[0]
            cur.execute("INSERT INTO roles (name) VALUES (%s) RETURNING id", (f"technician-{uuid.uuid4().hex[:6]}",))
            role = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO users (organization_id, hospital_id, role_id, full_name, email, password_hash) "
                "VALUES (%s,%s,%s,'Tech','tech-{}@example.com','x') RETURNING id".format(uuid.uuid4().hex[:6]),
                (s["org"], s["hosp"], role),
            )
            s["user"] = cur.fetchone()[0]
            cur.execute("INSERT INTO maintenance_types (name) VALUES (%s) RETURNING id", (f"corrective-{uuid.uuid4().hex[:6]}",))
            s["mtype"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id, "
                "performed_by, description) VALUES (%s,%s,%s,%s,%s,'Replaced filter') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["mtype"], s["user"]),
            )
            s["record"] = cur.fetchone()[0]
            conn.commit()

        check("set up organization/hospital/device/user/maintenance_record", t_setup)

        def t_part_and_inventory():
            cur.execute(
                "INSERT INTO parts (name, part_number) VALUES ('HEPA Filter', %s) RETURNING id",
                (f"PN-{uuid.uuid4().hex[:8]}",),
            )
            s["part"] = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO part_inventory (organization_id, hospital_id, part_id, quantity_on_hand) "
                "VALUES (%s, %s, %s, 10) RETURNING id",
                (s["org"], s["hosp"], s["part"]),
            )
            s["inv"] = cur.fetchone()[0]
            conn.commit()

        check("insert a part and its initial inventory (10 in stock)", t_part_and_inventory)

        def t_duplicate_inventory_row_rejected():
            try:
                cur.execute(
                    "INSERT INTO part_inventory (organization_id, hospital_id, part_id, quantity_on_hand) "
                    "VALUES (%s, %s, %s, 5)",
                    (s["org"], s["hosp"], s["part"]),
                )
                conn.commit()
                raise AssertionError("a second inventory row for the same hospital+part was allowed")
            except psycopg2.errors.UniqueViolation:
                conn.rollback()

        check("UNIQUE(hospital_id, part_id) blocks a duplicate inventory row", t_duplicate_inventory_row_rejected)

        def t_negative_stock_rejected():
            try:
                cur.execute("UPDATE part_inventory SET quantity_on_hand = -1 WHERE id = %s", (s["inv"],))
                conn.commit()
                raise AssertionError("negative quantity_on_hand was allowed")
            except psycopg2.errors.CheckViolation:
                conn.rollback()

        check("CHECK constraint rejects negative quantity_on_hand", t_negative_stock_rejected)

        def t_trigger_decrements_on_insert():
            before = stock()
            cur.execute(
                "INSERT INTO maintenance_parts (maintenance_record_id, part_id, quantity) VALUES (%s, %s, 3) RETURNING id",
                (s["record"], s["part"]),
            )
            s["mp"] = cur.fetchone()[0]
            conn.commit()
            after = stock()
            assert after == before - 3, f"expected stock to drop by 3, was {before} -> {after}"

        check("trigger decrements part_inventory by quantity on INSERT into maintenance_parts", t_trigger_decrements_on_insert)

        def t_trigger_adjusts_on_update():
            before = stock()
            cur.execute("UPDATE maintenance_parts SET quantity = 5 WHERE id = %s", (s["mp"],))
            conn.commit()
            after = stock()
            assert after == before - 2, f"expected stock to drop by 2 more (3->5), was {before} -> {after}"

        check("trigger adjusts part_inventory by the delta on UPDATE of quantity", t_trigger_adjusts_on_update)

        def t_insufficient_stock_rejected():
            # stock is now 10 - 5 = 5. Use a SEPARATE record (same device) so
            # this doesn't collide with uq_record_part on the existing row.
            cur.execute(
                "INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id, "
                "performed_by, description) VALUES (%s,%s,%s,%s,%s,'Second record') RETURNING id",
                (s["org"], s["hosp"], s["device"], s["mtype"], s["user"]),
            )
            record2 = cur.fetchone()[0]
            conn.commit()
            try:
                cur.execute(
                    "INSERT INTO maintenance_parts (maintenance_record_id, part_id, quantity) VALUES (%s, %s, 999)",
                    (record2, s["part"]),
                )
                conn.commit()
                raise AssertionError("consuming more parts than are in stock was allowed")
            except psycopg2.errors.CheckViolation:
                conn.rollback()
            s["record2"] = record2

        check("insufficient stock is rejected (CHECK fires through the trigger's UPDATE)", t_insufficient_stock_rejected)

        def t_usage_at_unstocked_hospital_rejected():
            cur.execute("INSERT INTO hospitals (organization_id, name, code) VALUES (%s, %s, %s) RETURNING id",
                        (s["org"], "Second Hospital", "P3H2"))
            hosp2 = cur.fetchone()[0]
            cur.execute("INSERT INTO departments (hospital_id, name) VALUES (%s, 'Radiology') RETURNING id", (hosp2,))
            dept2 = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id, "
                "device_code, name, qr_identifier) SELECT organization_id, %s, %s, device_model_id, "
                "'DEV-P3-2', 'Device 2', 'QR-P3-2' FROM devices WHERE id = %s RETURNING id",
                (hosp2, dept2, s["device"]),
            )
            device2 = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id, "
                "performed_by, description) VALUES (%s,%s,%s,%s,%s,'Different hospital record') RETURNING id",
                (s["org"], hosp2, device2, s["mtype"], s["user"]),
            )
            record2 = cur.fetchone()[0]
            conn.commit()
            try:
                # this hospital never stocked this part - no part_inventory row exists for (hosp2, part)
                cur.execute(
                    "INSERT INTO maintenance_parts (maintenance_record_id, part_id, quantity) VALUES (%s, %s, 1)",
                    (record2, s["part"]),
                )
                conn.commit()
                raise AssertionError("using a part at a hospital with no inventory row for it was allowed")
            except psycopg2.errors.RaiseException:
                conn.rollback()
            # clean up this sub-scenario's rows so teardown below is simpler
            cur.execute("DELETE FROM maintenance_records WHERE id = %s", (record2,))
            cur.execute("DELETE FROM devices WHERE id = %s", (device2,))
            cur.execute("DELETE FROM departments WHERE id = %s", (dept2,))
            cur.execute("DELETE FROM hospitals WHERE id = %s", (hosp2,))
            conn.commit()

        check(
            "trigger rejects part usage at a hospital that never stocked that part",
            t_usage_at_unstocked_hospital_rejected,
        )

        def t_duplicate_part_in_same_record_rejected():
            try:
                cur.execute(
                    "INSERT INTO maintenance_parts (maintenance_record_id, part_id, quantity) VALUES (%s, %s, 1)",
                    (s["record"], s["part"]),
                )
                conn.commit()
                raise AssertionError("a second maintenance_parts row for the same record+part was allowed")
            except psycopg2.errors.UniqueViolation:
                conn.rollback()

        check("UNIQUE(maintenance_record_id, part_id) blocks a duplicate line item", t_duplicate_part_in_same_record_rejected)

        def t_trigger_restores_on_delete():
            before = stock()
            cur.execute("DELETE FROM maintenance_parts WHERE id = %s", (s["mp"],))
            conn.commit()
            after = stock()
            assert after == before + 5, f"expected stock to be restored by 5, was {before} -> {after}"

        check("trigger restores part_inventory on DELETE from maintenance_parts", t_trigger_restores_on_delete)

        def t_part_restrict():
            try:
                cur.execute("DELETE FROM parts WHERE id = %s", (s["part"],))
                conn.commit()
                raise AssertionError("a part with inventory history was deleted")
            except psycopg2.errors.ForeignKeyViolation:
                conn.rollback()

        check("ON DELETE RESTRICT blocks deleting a part with inventory records", t_part_restrict)

        def t_updated_at_trigger():
            import time
            cur.execute("SELECT updated_at FROM parts WHERE id = %s", (s["part"],))
            before = cur.fetchone()[0]
            time.sleep(1)
            cur.execute("UPDATE parts SET name = 'HEPA Filter v2' WHERE id = %s", (s["part"],))
            conn.commit()
            cur.execute("SELECT updated_at FROM parts WHERE id = %s", (s["part"],))
            after = cur.fetchone()[0]
            assert after > before

        check("updated_at trigger fires on the new Phase 3 tables too", t_updated_at_trigger)

        def t_teardown():
            cur.execute("DELETE FROM part_inventory WHERE hospital_id = %s", (s["hosp"],))
            cur.execute("DELETE FROM parts WHERE id = %s", (s["part"],))
            cur.execute("DELETE FROM maintenance_records WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM devices WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM users WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM departments WHERE hospital_id = %s", (s["hosp"],))
            cur.execute("DELETE FROM hospitals WHERE organization_id = %s", (s["org"],))
            cur.execute("DELETE FROM organizations WHERE id = %s", (s["org"],))
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM organizations WHERE id = %s", (s["org"],))
            assert cur.fetchone()[0] == 0

        check("test data cleaned up bottom-up (no leftover rows after validation)", t_teardown)

        print("\nAll Phase 3 validation checks passed.")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
