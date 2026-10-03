"""Phase 6 - cross-cutting index and constraint review

This phase adds no new tables. It's a systematic audit: every foreign
key column in the schema (58 of them, across 21 tables) was cross-checked
against every index's leading column. Findings:

MISSING INDEXES (a FOREIGN KEY constraint does NOT auto-create an index
in Postgres - only PRIMARY KEY and UNIQUE constraints do; this is easy
to miss on a column added late or covered only by a composite UNIQUE on
a different column order):
  1. attachments.hospital_id       - no index at all
  2. maintenance_schedules.hospital_id - no index at all
  3. notifications.related_ticket_id   - no index at all
  4. part_inventory.part_id        - only present as the SECOND column of
     uq_inventory_hospital_part (hospital_id, part_id); a plain lookup by
     part_id alone can't use a composite index's non-leading column
  5. ticket_assignments.ticket_id  - only covered by the PARTIAL unique
     index uq_active_assignment (... WHERE unassigned_at IS NULL). A
     partial index can only serve queries whose WHERE clause implies its
     predicate, so "all assignments ever for this ticket" (no
     unassigned_at filter) gets no index benefit from it. Adding a plain
     index on ticket_id fixes general-purpose lookups without touching
     the partial index, which stays for its own job (enforcing the
     active-assignment uniqueness rule).

CONSTRAINT TIGHTENED:
  maintenance_tickets already CHECKs resolved_at >= created_at when set,
  but nothing enforced that a 'resolved' or 'closed' ticket actually HAS
  a resolved_at. Added.

Revision ID: 0006_phase6_hardening
Revises: 0005_phase5_supporting
Create Date: 2026-09-22
"""
from alembic import op

revision = "0006_phase6_hardening"
down_revision = "0005_phase5_supporting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_attachments_hospital_id", "attachments", ["hospital_id"])
    op.create_index("ix_maintenance_schedules_hospital_id", "maintenance_schedules", ["hospital_id"])
    op.create_index("ix_notifications_related_ticket_id", "notifications", ["related_ticket_id"])
    op.create_index("ix_part_inventory_part_id", "part_inventory", ["part_id"])
    op.create_index("ix_ticket_assignments_ticket_id", "ticket_assignments", ["ticket_id"])

    # Backfill first: any pre-existing 'resolved'/'closed' ticket seeded before
    # this constraint existed (e.g. by an earlier version of seed_phase2.py)
    # would otherwise fail ADD CONSTRAINT outright, since it validates every
    # existing row. updated_at is the best available proxy for when it was
    # actually resolved.
    op.execute(
        """
        UPDATE maintenance_tickets
        SET resolved_at = updated_at
        WHERE status IN ('resolved', 'closed') AND resolved_at IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE maintenance_tickets
        ADD CONSTRAINT ck_ticket_resolved_status_has_timestamp
        CHECK (status NOT IN ('resolved', 'closed') OR resolved_at IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE maintenance_tickets DROP CONSTRAINT ck_ticket_resolved_status_has_timestamp;")
    op.drop_index("ix_ticket_assignments_ticket_id", table_name="ticket_assignments")
    op.drop_index("ix_part_inventory_part_id", table_name="part_inventory")
    op.drop_index("ix_notifications_related_ticket_id", table_name="notifications")
    op.drop_index("ix_maintenance_schedules_hospital_id", table_name="maintenance_schedules")
    op.drop_index("ix_attachments_hospital_id", table_name="attachments")
