"""
Phase 6 seed data - rounds out the demo dataset with a second device that
has a fuller history (multiple maintenance records over time, a rising
risk trend, a corrective ticket), so a dashboard or report built on this
data has more than one data point to show.

Depends on seed_phase1.py through seed_phase5.py having run.
Pure psycopg2, idempotent.

Run with:
    python database/seeds/seed_phase6.py
"""
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")


def run():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM organizations WHERE code = 'CAIRO-MED'")
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Run seed_phase1.py through seed_phase5.py first.")
        org_id = row[0]

        cur.execute("SELECT id FROM hospitals WHERE organization_id = %s AND code = 'CMC-MAIN'", (org_id,))
        hospital_id = cur.fetchone()[0]

        cur.execute("SELECT id FROM departments WHERE hospital_id = %s AND name = 'Radiology'", (hospital_id,))
        dept_row = cur.fetchone()
        if dept_row is None:
            raise RuntimeError("No Radiology department found - run seed_phase1.py first.")
        department_id = dept_row[0]

        cur.execute("SELECT id FROM users WHERE email = 'mostafa.tech@cairomed.example'")
        user_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO manufacturers (name) VALUES ('GE Healthcare')
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id
            """
        )
        manufacturer_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO device_categories (name) VALUES ('CT Scanner')
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id
            """
        )
        category_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO device_models (manufacturer_id, device_category_id, name)
            VALUES (%s, %s, 'Revolution CT')
            ON CONFLICT (manufacturer_id, name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (manufacturer_id, category_id),
        )
        model_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id,
                                  device_code, name, qr_identifier, status, criticality,
                                  installation_date, warranty_expiry)
            VALUES (%s, %s, %s, %s, 'DEV-002', 'CT Scanner Unit', 'QR-CMC-DEV-002', 'active', 'high',
                    '2023-01-15', '2028-01-15')
            ON CONFLICT (hospital_id, device_code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (org_id, hospital_id, department_id, model_id),
        )
        device_id = cur.fetchone()[0]

        cur.execute(
            "SELECT id FROM maintenance_types WHERE name = 'preventive'"
        )
        preventive_type_id = cur.fetchone()[0]
        cur.execute(
            "SELECT id FROM maintenance_types WHERE name = 'corrective'"
        )
        corrective_type_id = cur.fetchone()[0]

        # A short maintenance history: two preventive visits, one corrective fix.
        history = [
            (preventive_type_id, "2025-06-01", "Routine annual calibration check"),
            (preventive_type_id, "2026-01-01", "Routine annual calibration check"),
            (corrective_type_id, "2026-02-15", "Replaced cooling fan after overheating alarm"),
        ]
        for type_id, performed_at, description in history:
            cur.execute(
                "SELECT id FROM maintenance_records WHERE device_id = %s AND performed_at = %s::timestamptz",
                (device_id, performed_at),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id,
                                                      performed_by, description, performed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (org_id, hospital_id, device_id, type_id, user_id, description, performed_at),
                )

        # A risk trend: low -> medium -> high over time, showing degradation.
        risk_history = [("low", "2025-01-01"), ("medium", "2025-09-01"), ("high", "2026-02-15")]
        for level, assessed_at in risk_history:
            cur.execute(
                "SELECT id FROM risk_assessments WHERE device_id = %s AND assessed_at = %s::timestamptz",
                (device_id, assessed_at),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """
                    INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by,
                                                   risk_level, assessed_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (org_id, hospital_id, device_id, user_id, level, assessed_at),
                )

        conn.commit()

        cur.execute("SELECT current_risk_level, next_maintenance_due_date FROM devices WHERE id = %s", (device_id,))
        risk, next_due = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM maintenance_records WHERE device_id = %s", (device_id,))
        record_count = cur.fetchone()[0]

        print("Seed complete:")
        print(f"  DEV-002 (CT Scanner Unit): {record_count} maintenance records, current_risk_level={risk}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
