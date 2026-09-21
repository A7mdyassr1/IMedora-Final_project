"""Phase 2 - maintenance workflow (+ users/roles foundation)

Creates: roles, users, maintenance_types, maintenance_schedules,
maintenance_tickets, maintenance_records, ticket_assignments.

Also alters devices: adds next_maintenance_due_date (a cached column,
kept up to date by whoever writes maintenance_schedules - promised back
in the original Phase 1 design notes, now that the source table exists).

users/roles were not in the original phase plan but are added here out
of necessity: maintenance_tickets.reported_by, maintenance_records.performed_by,
and ticket_assignments.user_id all need a real identity to point at.
There is deliberately no separate `technicians` table - a technician is
a user with role = 'technician' (decided in the earlier architecture
review); this keeps every "who did this" column pointing at one place.

Revision ID: 0002_phase2_maintenance
Revises: 0001_phase1_core
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0002_phase2_maintenance"
down_revision = "0001_phase1_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- roles -------------------------------------------------------------
    op.create_table(
        "roles",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute(
        "CREATE TRIGGER trg_roles_updated_at BEFORE UPDATE ON roles "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- users ---------------------------------------------------------------
    # organization_id/hospital_id are denormalized copies of the ancestry
    # reachable via department_id, same convention as devices in Phase 1
    # (see the migration notes above for why they aren't cross-checked with
    # a composite FK here). department_id is nullable - it only matters for
    # the department_user role.
    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("hospital_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("department_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("role_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_index("ix_users_hospital_id", "users", ["hospital_id"])
    op.create_index("ix_users_department_id", "users", ["department_id"])
    op.create_index("ix_users_role_id", "users", ["role_id"])
    op.execute(
        "CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- maintenance_types ---------------------------------------------------
    # A real lookup table, not a native enum (unlike device_status/criticality) -
    # matches the original design; new types can be added without a migration.
    # NOTE: "calibration" is deliberately NOT a value here - it lives only in
    # qa_records.record_type (Phase 4), to avoid the same real-world event
    # having two possible homes.
    op.create_table(
        "maintenance_types",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute(
        "CREATE TRIGGER trg_maintenance_types_updated_at BEFORE UPDATE ON maintenance_types "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- maintenance_schedules -------------------------------------------------
    # device_id is RESTRICT, matching the Phase 1 philosophy: a device with an
    # active maintenance plan can't be hard-deleted out from under it.
    # UNIQUE(device_id, maintenance_type_id) stops two overlapping schedules of
    # the same type existing for one device (which one would govern the due date?).
    # UNIQUE(id, device_id, maintenance_type_id) exists purely to let
    # maintenance_records enforce, at the database level, that a record's
    # schedule_id actually belongs to the same device AND maintenance type as
    # the record itself - see maintenance_records below.
    op.create_table(
        "maintenance_schedules",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("hospital_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("maintenance_type_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("frequency_days", sa.Integer(), nullable=False),
        sa.Column("next_due_date", sa.Date(), nullable=False),
        sa.Column("last_performed_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["maintenance_type_id"], ["maintenance_types.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("device_id", "maintenance_type_id", name="uq_schedule_device_type"),
        sa.UniqueConstraint("id", "device_id", "maintenance_type_id", name="uq_schedule_id_device_type"),
        sa.CheckConstraint("frequency_days > 0", name="ck_schedule_frequency_positive"),
    )
    op.create_index("ix_maintenance_schedules_organization_id", "maintenance_schedules", ["organization_id"])
    op.execute(
        "CREATE TRIGGER trg_maintenance_schedules_updated_at BEFORE UPDATE ON maintenance_schedules "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- maintenance_tickets ---------------------------------------------------
    ticket_priority = pg.ENUM("low", "medium", "high", "critical", name="ticket_priority")
    ticket_status = pg.ENUM(
        "open", "assigned", "in_progress", "waiting_for_parts", "resolved", "closed", "cancelled",
        name="ticket_status",
    )
    op.create_table(
        "maintenance_tickets",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("hospital_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("reported_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("problem_description", sa.Text(), nullable=False),
        sa.Column("priority", ticket_priority, nullable=False, server_default="medium"),
        sa.Column("status", ticket_status, nullable=False, server_default="open"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reported_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "device_id", name="uq_ticket_id_device"),
        sa.CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= created_at", name="ck_ticket_resolved_after_created"
        ),
    )
    op.create_index("ix_tickets_organization_id", "maintenance_tickets", ["organization_id"])
    op.create_index("ix_tickets_hospital_id", "maintenance_tickets", ["hospital_id"])
    op.create_index("ix_tickets_device_id", "maintenance_tickets", ["device_id"])
    op.create_index("ix_tickets_reported_by", "maintenance_tickets", ["reported_by"])
    op.create_index("ix_tickets_status", "maintenance_tickets", ["status"])
    op.execute(
        "CREATE TRIGGER trg_tickets_updated_at BEFORE UPDATE ON maintenance_tickets "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- maintenance_records -----------------------------------------------
    # ticket_id and schedule_id are both OPTIONAL and INDEPENDENT: a record
    # can carry a ticket_id (corrective), a schedule_id (preventive), both, or
    # neither (ad-hoc/historical entry) - see the earlier architecture review.
    # Both use composite FKs (nullable-safe: a NULL column simply isn't
    # checked) that force the referenced ticket/schedule to belong to the
    # SAME device as the record - and for schedule_id, the SAME maintenance
    # type too. Both are RESTRICT, not SET NULL: SET NULL isn't even possible
    # here since it would try to null out device_id/maintenance_type_id,
    # which are NOT NULL columns of the record itself, not just of the link.
    op.create_table(
        "maintenance_records",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("hospital_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("maintenance_type_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("schedule_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("performed_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hospital_id"], ["hospitals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["maintenance_type_id"], ["maintenance_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["ticket_id", "device_id"], ["maintenance_tickets.id", "maintenance_tickets.device_id"],
            ondelete="RESTRICT", name="fk_record_ticket_same_device",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id", "device_id", "maintenance_type_id"],
            ["maintenance_schedules.id", "maintenance_schedules.device_id", "maintenance_schedules.maintenance_type_id"],
            ondelete="RESTRICT", name="fk_record_schedule_same_device_and_type",
        ),
    )
    op.create_index("ix_records_organization_id", "maintenance_records", ["organization_id"])
    op.create_index("ix_records_hospital_id", "maintenance_records", ["hospital_id"])
    op.create_index("ix_records_device_id", "maintenance_records", ["device_id"])
    op.create_index("ix_records_maintenance_type_id", "maintenance_records", ["maintenance_type_id"])
    op.create_index("ix_records_ticket_id", "maintenance_records", ["ticket_id"])
    op.create_index("ix_records_schedule_id", "maintenance_records", ["schedule_id"])
    op.create_index("ix_records_performed_by", "maintenance_records", ["performed_by"])
    op.execute(
        "CREATE TRIGGER trg_records_updated_at BEFORE UPDATE ON maintenance_records "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- ticket_assignments ---------------------------------------------------
    # ticket_id CASCADEs (a pure join row has no meaning without its ticket,
    # same reasoning as locations under a deleted hospital); user_id is
    # RESTRICT (assignment history must survive even if a user leaves).
    # unassigned_at (nullable) records history instead of deleting the row
    # when someone is taken off a ticket. The partial unique index below
    # only blocks a duplicate ACTIVE assignment - a user can be reassigned
    # to the same ticket later, after being unassigned.
    op.create_table(
        "ticket_assignments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticket_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["ticket_id"], ["maintenance_tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "unassigned_at IS NULL OR unassigned_at >= assigned_at", name="ck_assignment_unassigned_after_assigned"
        ),
    )
    op.create_index("ix_ticket_assignments_user_id", "ticket_assignments", ["user_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_active_assignment ON ticket_assignments (ticket_id, user_id) "
        "WHERE unassigned_at IS NULL;"
    )
    op.execute(
        "CREATE TRIGGER trg_ticket_assignments_updated_at BEFORE UPDATE ON ticket_assignments "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    # --- devices: add the cached column promised back in Phase 1 -------------
    op.add_column("devices", sa.Column("next_maintenance_due_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "next_maintenance_due_date")
    op.drop_table("ticket_assignments")
    op.drop_table("maintenance_records")
    op.drop_table("maintenance_tickets")
    op.execute("DROP TYPE IF EXISTS ticket_status;")
    op.execute("DROP TYPE IF EXISTS ticket_priority;")
    op.drop_table("maintenance_schedules")
    op.drop_table("maintenance_types")
    op.drop_table("users")
    op.drop_table("roles")
