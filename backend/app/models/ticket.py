"""Maintenance tickets and their assignments (B4) - exact mirrors of migration 0002.

The schema is owned by database/migrations: never create_all(). Constraint and index names are
declared so the ORM matches the live database exactly (tests/test_schema_compat.py) and so
database errors can be mapped to clear messages by name.

Facts the backend relies on (see the B4 plan):
- There is no department_id on tickets: department-level filtering goes through the device.
- There is no category column: the category is a "[Label] " prefix of problem_description
  (app/utils/problem_category.py).
- There is no ticket number column: the display number is derived from the UUID (Decision 4,
  app/utils/ticket_number.py).
- There is no ticket-updates table: the timeline is derived from audit_logs and
  ticket_assignments (app/services/ticket_timeline.py).
"""
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint, DateTime, FetchedValue, ForeignKey, Index, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import TicketPriority, TicketStatus
from app.models.base import Base
from app.models.device import Device
from app.models.user import User


def _pg_enum(enum_cls, name: str):
    # create_type=False: the types already exist (migrations own them).
    return PG_ENUM(enum_cls, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


class TicketAssignment(Base):
    """One assignment of a user to a ticket. Rows are history: unassigning sets unassigned_at,
    a row is never deleted. At most one ACTIVE row per (ticket, user) (uq_active_assignment)."""
    __tablename__ = "ticket_assignments"
    __table_args__ = (
        CheckConstraint("unassigned_at IS NULL OR unassigned_at >= assigned_at", name="ck_assignment_unassigned_after_assigned"),
        Index("ix_ticket_assignments_ticket_id", "ticket_id"),
        Index("ix_ticket_assignments_user_id", "user_id"),
        Index("uq_active_assignment", "ticket_id", "user_id", unique=True, postgresql_where=text("unassigned_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    ticket_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("maintenance_tickets.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    unassigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())

    user: Mapped[User] = relationship(lazy="joined")

    @property
    def is_active(self) -> bool:
        return self.unassigned_at is None


class MaintenanceTicket(Base):
    __tablename__ = "maintenance_tickets"
    __table_args__ = (
        UniqueConstraint("id", "device_id", name="uq_ticket_id_device"),  # target of fk_record_ticket_same_device
        CheckConstraint("resolved_at IS NULL OR resolved_at >= created_at", name="ck_ticket_resolved_after_created"),
        CheckConstraint("status NOT IN ('resolved', 'closed') OR resolved_at IS NOT NULL",
                        name="ck_ticket_resolved_status_has_timestamp"),
        Index("ix_tickets_organization_id", "organization_id"),
        Index("ix_tickets_hospital_id", "hospital_id"),
        Index("ix_tickets_device_id", "device_id"),
        Index("ix_tickets_reported_by", "reported_by"),
        Index("ix_tickets_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="RESTRICT"))
    device_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"))
    reported_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    problem_description: Mapped[str] = mapped_column(Text)
    priority: Mapped[TicketPriority] = mapped_column(_pg_enum(TicketPriority, "ticket_priority"), server_default=text("'medium'"))
    status: Mapped[TicketStatus] = mapped_column(_pg_enum(TicketStatus, "ticket_status"), server_default=text("'open'"))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())

    # Always needed to build a response, so always eager - but with "selectin", NOT "joined": each
    # relation is one extra SELECT ... WHERE id IN (<the rows of this page>), never one per row, and
    # the paged ticket query itself stays a plain query on maintenance_tickets. With joined loading,
    # PostgreSQL joined EVERY matching ticket to devices/models/users/... before sorting and limiting
    # (measured in B4 CP1: ~38 ms vs ~4 ms per page at 12k tickets in scope).
    device: Mapped[Device] = relationship(lazy="selectin")
    reporter: Mapped[User] = relationship(lazy="selectin", foreign_keys=[reported_by])
    assignments: Mapped[List[TicketAssignment]] = relationship(
        lazy="selectin", order_by=lambda: (TicketAssignment.assigned_at, TicketAssignment.id),
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def active_assignments(self) -> List[TicketAssignment]:
        return [a for a in self.assignments if a.is_active]
