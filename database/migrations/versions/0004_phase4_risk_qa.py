"""Phase 4 - risk management and quality assurance

Creates: risk_assessments, qa_records. Also alters devices: adds
current_risk_level (cached, same convention as next_maintenance_due_date
from Phase 2).

Design notes:
- risk_factors / risk_mitigation_actions from the original ERD are
  DELIBERATELY not built here - they were classified as a Phase 2/future
  enrichment (not MVP) in the original architecture review, not
  forgotten. `risk_assessments.notes` covers this informally for now.
- qa_records is a single unified table for inspection/calibration/
  compliance (record_type column), not three separate tables - decided
  back in the original review specifically to avoid "calibration" having
  two possible homes (it also lives nowhere in maintenance_types, see
  Phase 2's migration notes).
- The current_risk_level cache uses a different trigger PATTERN than
  Phase 3's inventory trigger: inventory is a running total, so that
  trigger applies incremental deltas. Risk level is "whatever the most
  recent assessment says", so this trigger just recomputes it from
  scratch (ORDER BY assessed_at DESC LIMIT 1) on every INSERT/UPDATE/
  DELETE - simpler and correct for backdated inserts, corrections, and
  deletions alike, at the cost of one extra SELECT per write (risk
  assessments are low-frequency, so this is a good trade).

Revision ID: 0004_phase4_risk_qa
Revises: 0003_phase3_parts
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0004_phase4_risk_qa"
down_revision = "0003_phase3_parts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    risk_level = pg.ENUM("low", "medium", "high", "critical", name="risk_level")
    risk_level.create(op.get_bind(), checkfirst=True)

    # --- devices: add the cached column -------------------------------------
    op.add_column(
        "devices",
        sa.Column("current_risk_level", pg.ENUM(name="risk_level", create_type=False), nullable=True),
    )

    # --- risk_assessments ----------------------------------------------------
    op.create_table(
        "risk_assessments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("hospital_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("assessed_by", pg.UUID(as_uuid=True), nullable=False),
        # reuse the same enum type just created above - no second CREATE TYPE
        sa.Column("risk_level", pg.ENUM(name="risk_level", create_type=False), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessed_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_risk_assessments_organization_id", "risk_assessments", ["organization_id"])
    op.create_index("ix_risk_assessments_hospital_id", "risk_assessments", ["hospital_id"])
    op.create_index("ix_risk_assessments_device_id", "risk_assessments", ["device_id"])
    op.create_index("ix_risk_assessments_assessed_by", "risk_assessments", ["assessed_by"])
    op.execute(
        "CREATE TRIGGER trg_risk_assessments_updated_at BEFORE UPDATE ON risk_assessments "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- trigger: keep devices.current_risk_level in sync ---------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION refresh_device_current_risk_level()
        RETURNS TRIGGER AS $$
        DECLARE
            v_device_id UUID;
            v_latest_risk risk_level;
        BEGIN
            v_device_id := COALESCE(NEW.device_id, OLD.device_id);

            SELECT risk_level INTO v_latest_risk
            FROM risk_assessments
            WHERE device_id = v_device_id
            ORDER BY assessed_at DESC
            LIMIT 1;

            UPDATE devices SET current_risk_level = v_latest_risk WHERE id = v_device_id;

            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_risk_assessments_refresh_device
        AFTER INSERT OR UPDATE OR DELETE ON risk_assessments
        FOR EACH ROW EXECUTE FUNCTION refresh_device_current_risk_level();
        """
    )

    # --- qa_records ------------------------------------------------------------
    qa_record_type = pg.ENUM("inspection", "calibration", "compliance", name="qa_record_type")
    qa_status = pg.ENUM("pass", "fail", "pending", name="qa_status")

    op.create_table(
        "qa_records",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("hospital_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("performed_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("record_type", qa_record_type, nullable=False),
        sa.Column("status", qa_status, nullable=False, server_default="pending"),
        sa.Column("findings", sa.Text(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "next_due_date IS NULL OR next_due_date >= performed_at::date",
            name="ck_qa_next_due_after_performed",
        ),
    )
    op.create_index("ix_qa_records_organization_id", "qa_records", ["organization_id"])
    op.create_index("ix_qa_records_hospital_id", "qa_records", ["hospital_id"])
    op.create_index("ix_qa_records_device_id", "qa_records", ["device_id"])
    op.create_index("ix_qa_records_performed_by", "qa_records", ["performed_by"])
    op.execute(
        "CREATE TRIGGER trg_qa_records_updated_at BEFORE UPDATE ON qa_records "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.drop_table("qa_records")
    op.execute("DROP TYPE IF EXISTS qa_status;")
    op.execute("DROP TYPE IF EXISTS qa_record_type;")
    op.execute("DROP TRIGGER IF EXISTS trg_risk_assessments_refresh_device ON risk_assessments;")
    op.execute("DROP FUNCTION IF EXISTS refresh_device_current_risk_level();")
    op.drop_table("risk_assessments")
    op.drop_column("devices", "current_risk_level")
    op.execute("DROP TYPE IF EXISTS risk_level;")
