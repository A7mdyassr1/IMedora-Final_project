"""QA records (B6 CP2) - exact mirror of migration 0004 (qa_records).

One table for inspections, calibrations and compliance checks (record_type), as decided in the
original review. Database rules this mirror declares (enforced by PostgreSQL, NOT re-implemented):
- ck_qa_next_due_after_performed: next_due_date is NULL or on/after the date of performed_at
  (performed_at::date, in the database's time zone). The service pre-checks the same rule with the
  database's own date conversion; the constraint stays the last line of defence (HTTP 422).
- status defaults to 'pending'; every foreign key is ON DELETE RESTRICT (records are history).
- No trigger touches devices: QA records do not change any cached device column.
"""
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, FetchedValue, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import QARecordType, QAStatus
from app.models.base import Base
from app.models.device import Device
from app.models.user import User


def _pg_enum(enum_cls, name: str):
    # create_type=False: the types already exist (migrations own them).
    return PG_ENUM(enum_cls, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


class QARecord(Base):
    __tablename__ = "qa_records"
    __table_args__ = (
        CheckConstraint("next_due_date IS NULL OR next_due_date >= performed_at::date",
                        name="ck_qa_next_due_after_performed"),
        Index("ix_qa_records_organization_id", "organization_id"),
        Index("ix_qa_records_hospital_id", "hospital_id"),
        Index("ix_qa_records_device_id", "device_id"),
        Index("ix_qa_records_performed_by", "performed_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="RESTRICT"))
    device_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"))
    performed_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    record_type: Mapped[QARecordType] = mapped_column(_pg_enum(QARecordType, "qa_record_type"))
    status: Mapped[QAStatus] = mapped_column(_pg_enum(QAStatus, "qa_status"), server_default=text("'pending'"))
    findings: Mapped[Optional[str]] = mapped_column(Text)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    next_due_date: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())

    # selectin (never joined) so paged queries stay one row per record
    device: Mapped[Device] = relationship(lazy="selectin")
    performer: Mapped[User] = relationship(lazy="selectin")
