"""Phase 3 - spare parts

Creates: parts, part_inventory, maintenance_parts.

Design notes:
- `parts` is global catalog data (no organization/hospital_id), same
  reasoning as manufacturers/device_categories/device_models in Phase 1:
  a "Philips M3001A sensor" is the same real-world part regardless of
  which hospital stocks it. `part_number` is IMedora's own catalog code
  (not a manufacturer serial), so - unlike devices.serial_number in
  Phase 1 - enforcing global uniqueness on it is legitimate here.
- `part_inventory` is the per-hospital stock level for a catalog part -
  UNIQUE(hospital_id, part_id) so there's exactly one stock row per part
  per hospital, matching the plan from the original architecture review.
- `maintenance_parts` has no organization_id/hospital_id of its own -
  same convention as ticket_assignments in Phase 2: it's a pure detail
  row with no independent meaning outside its parent maintenance_record,
  which already carries the full ancestry.
- A trigger keeps part_inventory in sync with maintenance_parts
  automatically (INSERT decrements stock, UPDATE of quantity adjusts by
  the delta, DELETE restores it) so stock accuracy doesn't depend on the
  backend remembering to do it in application code. The existing
  CHECK (quantity_on_hand >= 0) on part_inventory means the trigger's
  UPDATE - and therefore the whole maintenance_parts write - is rejected
  if there isn't enough stock. This also means a part can only be
  consumed at a hospital that already has an inventory row for it.

Revision ID: 0003_phase3_parts
Revises: 0002_phase2_maintenance
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0003_phase3_parts"
down_revision = "0002_phase2_maintenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- parts (global catalog) -----------------------------------------
    op.create_table(
        "parts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("part_number", sa.String(100), nullable=False, unique=True),
        sa.Column("unit", sa.String(20), nullable=False, server_default="piece"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute(
        "CREATE TRIGGER trg_parts_updated_at BEFORE UPDATE ON parts "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- part_inventory (per-hospital stock) --------------------------------
    op.create_table(
        "part_inventory",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("hospital_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("part_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reorder_threshold", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("hospital_id", "part_id", name="uq_inventory_hospital_part"),
        sa.CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_quantity_non_negative"),
        sa.CheckConstraint(
            "reorder_threshold IS NULL OR reorder_threshold >= 0", name="ck_inventory_reorder_non_negative"
        ),
    )
    op.create_index("ix_inventory_organization_id", "part_inventory", ["organization_id"])
    op.execute(
        "CREATE TRIGGER trg_part_inventory_updated_at BEFORE UPDATE ON part_inventory "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- maintenance_parts (parts consumed in a maintenance record) -----------
    # ON DELETE CASCADE from maintenance_record: a usage-detail row has no
    # meaning without its parent record (same reasoning as ticket_assignments
    # -> maintenance_tickets in Phase 2). RESTRICT on part_id: the historical
    # fact "this part was used" must survive even if the part is later
    # discontinued from the catalog.
    op.create_table(
        "maintenance_parts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("maintenance_record_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("part_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["maintenance_record_id"], ["maintenance_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("maintenance_record_id", "part_id", name="uq_record_part"),
        sa.CheckConstraint("quantity > 0", name="ck_maintenance_parts_quantity_positive"),
    )
    op.create_index("ix_maintenance_parts_part_id", "maintenance_parts", ["part_id"])
    op.execute(
        "CREATE TRIGGER trg_maintenance_parts_updated_at BEFORE UPDATE ON maintenance_parts "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- trigger: keep part_inventory in sync with maintenance_parts ---------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION adjust_part_inventory_on_usage()
        RETURNS TRIGGER AS $$
        DECLARE
            v_hospital_id UUID;
            v_rows_affected INT;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT hospital_id INTO v_hospital_id FROM maintenance_records WHERE id = NEW.maintenance_record_id;

                UPDATE part_inventory
                SET quantity_on_hand = quantity_on_hand - NEW.quantity
                WHERE hospital_id = v_hospital_id AND part_id = NEW.part_id;
                GET DIAGNOSTICS v_rows_affected = ROW_COUNT;

                IF v_rows_affected = 0 THEN
                    RAISE EXCEPTION
                        'No part_inventory row for part % at hospital % - cannot record usage of a part that was never stocked there',
                        NEW.part_id, v_hospital_id;
                END IF;
                RETURN NEW;

            ELSIF TG_OP = 'UPDATE' THEN
                IF NEW.quantity <> OLD.quantity THEN
                    SELECT hospital_id INTO v_hospital_id FROM maintenance_records WHERE id = NEW.maintenance_record_id;
                    UPDATE part_inventory
                    SET quantity_on_hand = quantity_on_hand - (NEW.quantity - OLD.quantity)
                    WHERE hospital_id = v_hospital_id AND part_id = NEW.part_id;
                END IF;
                RETURN NEW;

            ELSIF TG_OP = 'DELETE' THEN
                SELECT hospital_id INTO v_hospital_id FROM maintenance_records WHERE id = OLD.maintenance_record_id;
                UPDATE part_inventory
                SET quantity_on_hand = quantity_on_hand + OLD.quantity
                WHERE hospital_id = v_hospital_id AND part_id = OLD.part_id;
                RETURN OLD;
            END IF;

            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_maintenance_parts_adjust_inventory
        AFTER INSERT OR UPDATE OF quantity OR DELETE ON maintenance_parts
        FOR EACH ROW EXECUTE FUNCTION adjust_part_inventory_on_usage();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_maintenance_parts_adjust_inventory ON maintenance_parts;")
    op.execute("DROP FUNCTION IF EXISTS adjust_part_inventory_on_usage();")
    op.drop_table("maintenance_parts")
    op.drop_table("part_inventory")
    op.drop_table("parts")
