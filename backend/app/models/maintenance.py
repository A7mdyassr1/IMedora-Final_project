"""Maintenance types, schedules and records (B4) - exact mirrors of migration 0002.

Mapped in B4 CP1 together with the ticket tables so the whole maintenance schema is verified
against the live database at once; their services and endpoints arrive in B4 CP3.

Database rules these mirrors declare (enforced by PostgreSQL, not re-implemented here):
- A record's ticket must belong to the same device (fk_record_ticket_same_device).
- A record's schedule must match the same device AND maintenance type
  (fk_record_schedule_same_device_and_type).
- One schedule per (device, maintenance type) (uq_schedule_device_type).
- devices.next_maintenance_due_date is NOT maintained by a trigger: the backend keeps it in step
  with the active schedules (B4 CP3).
- maintenance_types has no organization_id: it is global reference data, like the catalog.
"""
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, FetchedValue, ForeignKey, ForeignKeyConstraint, Index, Integer,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MaintenanceType(Base):
    __tablename__ = "maintenance_types"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(50), unique=True)  # maintenance_types_name_key
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())


class MaintenanceSchedule(Base):
    __tablename__ = "maintenance_schedules"
    __table_args__ = (
        UniqueConstraint("device_id", "maintenance_type_id", name="uq_schedule_device_type"),
        # target of fk_record_schedule_same_device_and_type
        UniqueConstraint("id", "device_id", "maintenance_type_id", name="uq_schedule_id_device_type"),
        CheckConstraint("frequency_days > 0", name="ck_schedule_frequency_positive"),
        Index("ix_maintenance_schedules_organization_id", "organization_id"),
        Index("ix_maintenance_schedules_hospital_id", "hospital_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="RESTRICT"))
    device_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"))
    maintenance_type_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("maintenance_types.id", ondelete="RESTRICT"))
    frequency_days: Mapped[int] = mapped_column(Integer)
    next_due_date: Mapped[date] = mapped_column(Date)
    last_performed_date: Mapped[Optional[date]] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"
    __table_args__ = (
        # ticket_id and schedule_id have NO single-column foreign keys in the database: only these
        # composite ones, which also tie the ticket / schedule to the record's device (and type).
        ForeignKeyConstraint(
            ["ticket_id", "device_id"], ["maintenance_tickets.id", "maintenance_tickets.device_id"],
            name="fk_record_ticket_same_device", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["schedule_id", "device_id", "maintenance_type_id"],
            ["maintenance_schedules.id", "maintenance_schedules.device_id", "maintenance_schedules.maintenance_type_id"],
            name="fk_record_schedule_same_device_and_type", ondelete="RESTRICT",
        ),
        Index("ix_records_organization_id", "organization_id"),
        Index("ix_records_hospital_id", "hospital_id"),
        Index("ix_records_device_id", "device_id"),
        Index("ix_records_maintenance_type_id", "maintenance_type_id"),
        Index("ix_records_ticket_id", "ticket_id"),
        Index("ix_records_schedule_id", "schedule_id"),
        Index("ix_records_performed_by", "performed_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="RESTRICT"))
    device_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"))
    maintenance_type_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("maintenance_types.id", ondelete="RESTRICT"))
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    schedule_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    performed_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    description: Mapped[str] = mapped_column(Text)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())
