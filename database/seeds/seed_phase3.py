"""
Phase 3 seed data - a spare part, initial stock at the Phase 1 seed
hospital, and one unit consumed against the Phase 2 seed maintenance
record (via the inventory-adjusting trigger, not a manual UPDATE).

Depends on database/seeds/seed_phase1.py and seed_phase2.py having run.
Pure psycopg2, idempotent.

Run with:
    python database/seeds/seed_phase3.py
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
            "SELECT id FROM maintenance_records WHERE device_id = %s ORDER BY performed_at DESC LIMIT 1",
            (device_id,),
        )
        record_row = cur.fetchone()
        if record_row is None:
            raise RuntimeError("No maintenance_records found for DEV-001 - run seed_phase2.py first.")
        record_id = record_row[0]

        cur.execute(
            """
            INSERT INTO parts (name, part_number, unit)
            VALUES ('Pressure Sensor Tubing', 'PN-TUBING-001', 'piece')
            ON CONFLICT (part_number) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        )
        part_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO part_inventory (organization_id, hospital_id, part_id, quantity_on_hand, reorder_threshold)
            VALUES (%s, %s, %s, 20, 5)
            ON CONFLICT (hospital_id, part_id) DO NOTHING
            RETURNING id
            """,
            (org_id, hospital_id, part_id),
        )
        conn.commit()

        # Only insert usage if it doesn't already exist (idempotency, since
        # the trigger has a real side effect on stock and we don't want to
        # double-decrement on re-runs).
        cur.execute(
            "SELECT id FROM maintenance_parts WHERE maintenance_record_id = %s AND part_id = %s",
            (record_id, part_id),
        )
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO maintenance_parts (maintenance_record_id, part_id, quantity) VALUES (%s, %s, 1)",
                (record_id, part_id),
            )
            conn.commit()

        cur.execute("SELECT quantity_on_hand FROM part_inventory WHERE hospital_id = %s AND part_id = %s",
                    (hospital_id, part_id))
        print("Seed complete:")
        print(f"  Part: Pressure Sensor Tubing - stock now {cur.fetchone()[0]} (started at 20, trigger decremented it)")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
