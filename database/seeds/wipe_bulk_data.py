"""
Wipes ONLY the data created by generate_bulk_data.py (the "Egypt Health
Group" / EHG organization) - never touches the small deterministic
seed_phaseN.py data (CAIRO-MED), since that lives under a different
organization entirely.

Deletes bottom-up, in the ONE order that actually works given the
RESTRICT chains built throughout the schema:

  1. audit_logs           - RESTRICTs both organizations AND users
  2. attachments           - RESTRICTs devices/tickets/records
  3. maintenance_records   - RESTRICTs devices; composite-FKs to
                              tickets/schedules also block them until
                              records referencing them are gone.
                              (maintenance_parts cascades automatically -
                              its DELETE trigger restores part_inventory,
                              which is why part_inventory is deleted LATER,
                              not before this step)
  4. maintenance_tickets   - RESTRICTs devices (ticket_assignments
                              cascades automatically)
  5. maintenance_schedules - RESTRICTs devices
  6. risk_assessments      - RESTRICTs devices (its DELETE trigger
                              recomputes devices.current_risk_level,
                              harmless since devices are deleted next)
  7. qa_records            - RESTRICTs devices
  8. part_inventory        - RESTRICTs organizations (parts themselves
                              are a shared catalog and are NOT deleted -
                              see note below)
  9. devices               - now nothing references them
  10. notifications        - CASCADEs already when users/org go, deleted
                              explicitly here just for a clean rowcount
  11. users                - now nothing references them
  12. departments          - now nothing references them
  13. hospitals            - now nothing references them
  14. organizations        - now nothing references it

NOTE: shared/global catalog rows this data used (manufacturers, device
categories, device models, the "parts" catalog, roles, maintenance
types) are deliberately NOT deleted - they aren't organization-scoped,
other data might reference them, and leaving an unused catalog row
behind is harmless. Only organization-owned rows are removed.

Run with:
    python database/seeds/wipe_bulk_data.py
    python database/seeds/wipe_bulk_data.py --yes   # skip the confirmation prompt
"""
import argparse
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")

ORG_CODE = "EHG"

STEPS = [
    ("audit_logs", "organization_id = %s"),
    ("attachments", "organization_id = %s"),
    ("maintenance_records", "organization_id = %s"),
    ("maintenance_tickets", "organization_id = %s"),
    ("maintenance_schedules", "organization_id = %s"),
    ("risk_assessments", "organization_id = %s"),
    ("qa_records", "organization_id = %s"),
    ("part_inventory", "organization_id = %s"),
    ("devices", "organization_id = %s"),
    ("notifications", "organization_id = %s"),
    ("users", "organization_id = %s"),
    ("departments", "hospital_id IN (SELECT id FROM hospitals WHERE organization_id = %s)"),
    ("hospitals", "organization_id = %s"),
    ("organizations", "id = %s"),
]


def run(skip_confirm: bool):
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, name FROM organizations WHERE code = %s", (ORG_CODE,))
        row = cur.fetchone()
        if row is None:
            print(f"No organization with code '{ORG_CODE}' found - nothing to wipe.")
            return
        org_id, org_name = row

        cur.execute("SELECT COUNT(*) FROM devices WHERE organization_id = %s", (org_id,))
        device_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM maintenance_records WHERE organization_id = %s", (org_id,))
        record_count = cur.fetchone()[0]

        if not skip_confirm:
            answer = input(
                f"This will PERMANENTLY delete '{org_name}' - {device_count} devices, "
                f"{record_count} maintenance records, and everything under them.\n"
                f"Type 'yes' to continue: "
            )
            if answer.strip().lower() != "yes":
                print("Cancelled - nothing was deleted.")
                return

        for table, where in STEPS:
            cur.execute(f"DELETE FROM {table} WHERE {where}", (org_id,))
            print(f"  Deleted {cur.rowcount} rows from {table}")

        conn.commit()
        print(f"\n'{org_name}' fully removed. Other organizations (e.g. seed_phaseN.py's CAIRO-MED) were untouched.")
        print("You can now re-run generate_bulk_data.py for a fresh dataset.")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    run(skip_confirm=args.yes)
