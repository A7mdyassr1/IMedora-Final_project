"""
Phase 2 seed data - a technician user, a maintenance schedule for the
Phase 1 seed device (DEV-001), a ticket, and a record resolving it.

Depends on database/seeds/seed_phase1.py having been run first.
Pure psycopg2, idempotent (upserts on natural keys).

Run with:
    python database/seeds/seed_phase2.py
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
            raise RuntimeError("Run database/seeds/seed_phase1.py first - no CAIRO-MED organization found.")
        org_id = row[0]

        cur.execute("SELECT id FROM hospitals WHERE organization_id = %s AND code = 'CMC-MAIN'", (org_id,))
        hospital_id = cur.fetchone()[0]

        cur.execute("SELECT id FROM devices WHERE hospital_id = %s AND device_code = 'DEV-001'", (hospital_id,))
        device_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO roles (name) VALUES ('technician')
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        )
        technician_role_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO users (organization_id, hospital_id, role_id, full_name, email, password_hash)
            VALUES (%s, %s, %s, 'Mostafa the Technician', 'mostafa.tech@cairomed.example', 'not-a-real-hash')
            ON CONFLICT (email) DO UPDATE SET full_name = EXCLUDED.full_name
            RETURNING id
            """,
            (org_id, hospital_id, technician_role_id),
        )
        technician_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO maintenance_types (name) VALUES ('preventive')
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        )
        preventive_type_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO maintenance_types (name) VALUES ('corrective')
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        )
        corrective_type_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO maintenance_schedules (organization_id, hospital_id, device_id, maintenance_type_id,
                                                frequency_days, next_due_date)
            VALUES (%s, %s, %s, %s, 90, CURRENT_DATE + INTERVAL '90 days')
            ON CONFLICT (device_id, maintenance_type_id) DO UPDATE SET frequency_days = EXCLUDED.frequency_days
            RETURNING id
            """,
            (org_id, hospital_id, device_id, preventive_type_id),
        )
        schedule_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO maintenance_tickets (organization_id, hospital_id, device_id, reported_by,
                                              problem_description, priority, status)
            VALUES (%s, %s, %s, %s, 'Abnormal pressure reading', 'high', 'resolved')
            RETURNING id
            """,
            (org_id, hospital_id, device_id, technician_id),
        )
        ticket_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO ticket_assignments (ticket_id, user_id) VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (ticket_id, technician_id),
        )

        cur.execute(
            """
            INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id,
                                              ticket_id, performed_by, description)
            VALUES (%s, %s, %s, %s, %s, %s, 'Recalibrated pressure sensor and replaced tubing')
            """,
            (org_id, hospital_id, device_id, corrective_type_id, ticket_id, technician_id),
        )

        cur.execute(
            "UPDATE devices SET next_maintenance_due_date = CURRENT_DATE + INTERVAL '90 days' WHERE id = %s",
            (device_id,),
        )

        conn.commit()

        cur.execute(
            "SELECT problem_description, status, priority FROM maintenance_tickets WHERE id = %s", (ticket_id,)
        )
        print("Seed complete:")
        t = cur.fetchone()
        print(f"  Ticket: {t[0]} (status={t[1]}, priority={t[2]})")
        cur.execute("SELECT description FROM maintenance_records WHERE ticket_id = %s", (ticket_id,))
        print(f"  Record: {cur.fetchone()[0]}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
