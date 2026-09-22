"""
Phase 4 seed data - one risk assessment and one QA (calibration) record
for the Phase 1 seed device (DEV-001).

Depends on database/seeds/seed_phase1.py and seed_phase2.py having run.
Pure psycopg2, idempotent.

Run with:
    python database/seeds/seed_phase4.py
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
            raise RuntimeError("Run seed_phase1.py and seed_phase2.py first.")
        org_id = row[0]

        cur.execute("SELECT id FROM hospitals WHERE organization_id = %s AND code = 'CMC-MAIN'", (org_id,))
        hospital_id = cur.fetchone()[0]

        cur.execute("SELECT id FROM devices WHERE hospital_id = %s AND device_code = 'DEV-001'", (hospital_id,))
        device_id = cur.fetchone()[0]

        cur.execute(
            "SELECT id FROM users WHERE email = 'mostafa.tech@cairomed.example'"
        )
        user_row = cur.fetchone()
        if user_row is None:
            raise RuntimeError("No seed user found - run seed_phase2.py first.")
        user_id = user_row[0]

        cur.execute(
            "SELECT id FROM risk_assessments WHERE device_id = %s AND assessed_at = '2026-01-15'::timestamptz",
            (device_id,),
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level,
                                               notes, assessed_at)
                VALUES (%s, %s, %s, %s, 'critical', 'Life-support device - critical by default', '2026-01-15')
                """,
                (org_id, hospital_id, device_id, user_id),
            )

        cur.execute(
            "SELECT id FROM qa_records WHERE device_id = %s AND record_type = 'calibration' "
            "AND performed_at = '2026-01-10'::timestamptz",
            (device_id,),
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO qa_records (organization_id, hospital_id, device_id, performed_by, record_type,
                                         status, findings, performed_at, next_due_date)
                VALUES (%s, %s, %s, %s, 'calibration', 'pass', 'Pressure sensor within tolerance',
                        '2026-01-10', '2026-07-10')
                """,
                (org_id, hospital_id, device_id, user_id),
            )

        conn.commit()

        cur.execute("SELECT current_risk_level FROM devices WHERE id = %s", (device_id,))
        print("Seed complete:")
        print(f"  DEV-001 current_risk_level: {cur.fetchone()[0]}")
        cur.execute(
            "SELECT record_type, status, next_due_date FROM qa_records WHERE device_id = %s ORDER BY performed_at DESC LIMIT 1",
            (device_id,),
        )
        r = cur.fetchone()
        print(f"  Latest QA record: {r[0]} - {r[1]}, next due {r[2]}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
