"""Phase 5 - supporting tables: attachments, notifications, audit_logs

Design notes:
- attachments: exactly one of device_id/ticket_id/maintenance_record_id
  must be set - enforced with a CHECK that counts non-NULLs, not a
  polymorphic (entity_type, entity_id) pair, since Postgres can't put a
  real FK on a polymorphic reference. This was planned back in the
  original architecture review; implemented for real here.
- notifications: the ONE place in this schema where user_id is
  ON DELETE CASCADE instead of RESTRICT. Everywhere else preserves user
  references for accountability/history; a notification ("you were
  assigned a ticket") has no audit/legal value once the user is gone.
- audit_logs: NO updated_at, NO trigger - a log entry that can be edited
  after the fact isn't an audit log. record_id is a polymorphic pointer
  (it can reference a row in any table), so it can't carry a real FK -
  organization_id and user_id CAN and do have real FKs since they're
  not polymorphic. True immutability (REVOKE UPDATE, DELETE ON
  audit_logs FROM the app's DB role) is a deployment-time hardening
  step, deliberately not baked in here - a hard trigger would also block
  legitimate test/seed cleanup during development.

Revision ID: 0005_phase5_supporting
Revises: 0004_phase4_risk_qa
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0005_phase5_supporting"
down_revision = "0004_phase4_risk_qa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- attachments -----------------------------------------------------
    op.create_table(
        "attachments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("hospital_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("ticket_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("maintenance_record_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("uploaded_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("file_url", sa.String(500), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_id"], ["maintenance_tickets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["maintenance_record_id"], ["maintenance_records.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "(CASE WHEN device_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN ticket_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN maintenance_record_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_attachment_exactly_one_parent",
        ),
        sa.CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name="ck_attachment_size_non_negative"),
    )
    op.create_index("ix_attachments_organization_id", "attachments", ["organization_id"])
    op.create_index("ix_attachments_device_id", "attachments", ["device_id"])
    op.create_index("ix_attachments_ticket_id", "attachments", ["ticket_id"])
    op.create_index("ix_attachments_maintenance_record_id", "attachments", ["maintenance_record_id"])
    op.create_index("ix_attachments_uploaded_by", "attachments", ["uploaded_by"])
    op.execute(
        "CREATE TRIGGER trg_attachments_updated_at BEFORE UPDATE ON attachments "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- notifications -------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("related_ticket_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("notification_type", sa.String(50), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_ticket_id"], ["maintenance_tickets.id"], ondelete="SET NULL"),
        sa.CheckConstraint("NOT is_read OR read_at IS NOT NULL", name="ck_notification_read_has_timestamp"),
        sa.CheckConstraint(
            "read_at IS NULL OR read_at >= created_at", name="ck_notification_read_after_created"
        ),
    )
    op.create_index("ix_notifications_user_unread", "notifications", ["user_id", "is_read"])
    op.create_index("ix_notifications_organization_id", "notifications", ["organization_id"])
    op.execute(
        "CREATE TRIGGER trg_notifications_updated_at BEFORE UPDATE ON notifications "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- audit_logs (append-only, no updated_at, no trigger - see notes above) --
    audit_action = pg.ENUM("insert", "update", "delete", name="audit_action")
    op.create_table(
        "audit_logs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("table_name", sa.String(100), nullable=False),
        sa.Column("record_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("action", audit_action, nullable=False),
        sa.Column("old_values", pg.JSONB(), nullable=True),
        sa.Column("new_values", pg.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_audit_logs_organization_id", "audit_logs", ["organization_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_table_record", "audit_logs", ["table_name", "record_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.execute("DROP TYPE IF EXISTS audit_action;")
    op.drop_table("notifications")
    op.drop_table("attachments")
