"""
Phase 5 seed data - one attachment (on the Phase 2 seed ticket), one
notification, and one audit log entry.

Depends on database/seeds/seed_phase1.py and seed_phase2.py having run.
Pure psycopg2, idempotent.

Run with:
    python database/seeds/seed_phase5.py
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

        cur.execute(
            "SELECT id FROM users WHERE email = 'mostafa.tech@cairomed.example'"
        )
        user_row = cur.fetchone()
        if user_row is None:
            raise RuntimeError("No seed user found - run seed_phase2.py first.")
        user_id = user_row[0]

        cur.execute(
            "SELECT id FROM maintenance_tickets WHERE hospital_id = %s AND problem_description = %s",
            (hospital_id, "Abnormal pressure reading"),
        )
        ticket_row = cur.fetchone()
        if ticket_row is None:
            raise RuntimeError("No seed ticket found - run seed_phase2.py first.")
        ticket_id = ticket_row[0]

        cur.execute(
            "SELECT id FROM attachments WHERE ticket_id = %s AND file_url = %s",
            (ticket_id, "https://example.com/imedora-seed/pressure-gauge.jpg"),
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO attachments (organization_id, hospital_id, ticket_id, uploaded_by, file_url,
                                          file_name, mime_type)
                VALUES (%s, %s, %s, %s, 'https://example.com/imedora-seed/pressure-gauge.jpg',
                        'pressure-gauge.jpg', 'image/jpeg')
                """,
                (org_id, hospital_id, ticket_id, user_id),
            )

        cur.execute(
            "SELECT id FROM notifications WHERE user_id = %s AND related_ticket_id = %s",
            (user_id, ticket_id),
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO notifications (organization_id, user_id, related_ticket_id, title, body, notification_type)
                VALUES (%s, %s, %s, 'Ticket assigned to you', 'You were assigned: Abnormal pressure reading',
                        'ticket_assigned')
                """,
                (org_id, user_id, ticket_id),
            )

        cur.execute(
            "SELECT id FROM audit_logs WHERE table_name = 'maintenance_tickets' AND record_id = %s AND action = 'update'",
            (ticket_id,),
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                INSERT INTO audit_logs (organization_id, user_id, table_name, record_id, action, old_values, new_values)
                VALUES (%s, %s, 'maintenance_tickets', %s, 'update', '{"status": "open"}', '{"status": "resolved"}')
                """,
                (org_id, user_id, ticket_id),
            )

        conn.commit()

        print("Seed complete:")
        cur.execute("SELECT COUNT(*) FROM attachments WHERE ticket_id = %s", (ticket_id,))
        print(f"  Attachments on seed ticket: {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM notifications WHERE user_id = %s", (user_id,))
        print(f"  Notifications for seed user: {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM audit_logs")
        print(f"  Audit log rows total: {cur.fetchone()[0]}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
