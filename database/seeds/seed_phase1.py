"""
Phase 1 seed data - one organization, one hospital, two departments, a
manufacturer/category/model, and two devices.

Pure psycopg2 - no ORM. Safe to re-run (upserts on natural keys).

Run with:
    python database/seeds/seed_phase1.py
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
        cur.execute(
            """
            INSERT INTO organizations (name, code)
            VALUES ('Cairo Medical Center', 'CAIRO-MED')
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        )
        org_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO hospitals (organization_id, name, code)
            VALUES (%s, 'Cairo Medical Center - Main Campus', 'CMC-MAIN')
            ON CONFLICT (organization_id, code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (org_id,),
        )
        hospital_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO departments (hospital_id, name) VALUES (%s, 'ICU')
            ON CONFLICT (hospital_id, name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (hospital_id,),
        )
        icu_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO departments (hospital_id, name) VALUES (%s, 'Radiology')
            ON CONFLICT (hospital_id, name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (hospital_id,),
        )
        radiology_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO manufacturers (name) VALUES ('Philips')
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        )
        philips_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO device_categories (name) VALUES ('Ventilator')
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        )
        ventilator_cat_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO device_models (manufacturer_id, device_category_id, name)
            VALUES (%s, %s, 'Efficia CM10')
            ON CONFLICT (manufacturer_id, name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (philips_id, ventilator_cat_id),
        )
        model_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO devices (organization_id, hospital_id, department_id, device_model_id,
                                  device_code, name, qr_identifier, status, criticality)
            VALUES (%s, %s, %s, %s, 'DEV-001', 'Philips Ventilator', 'QR-CMC-DEV-001', 'active', 'critical')
            ON CONFLICT (hospital_id, device_code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (org_id, hospital_id, icu_id, model_id),
        )

        conn.commit()

        cur.execute(
            "SELECT device_code, name, status, criticality FROM devices WHERE hospital_id = %s ORDER BY device_code",
            (hospital_id,),
        )
        print("Seed complete:")
        for row in cur.fetchall():
            print(f"  {row[0]} - {row[1]} ({row[2]}, {row[3]})")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
