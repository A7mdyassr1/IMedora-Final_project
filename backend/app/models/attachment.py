"""Attachments (B5 CP4, Decision 5) - exact mirror of the `attachments` table (migration 0005 + the
0006 index).

Database rules declared here: exactly one parent - device, ticket or maintenance record
(ck_attachment_exactly_one_parent); size never negative; every reference RESTRICT.
`file_url` holds an INTERNAL storage reference ("local:<key>", app/storage), never a public URL;
rows written before B5 (seed data) may hold other values - their files are reported as not
available instead of being fetched or redirected to.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, FetchedValue, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.user import User


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN device_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN ticket_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN maintenance_record_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_attachment_exactly_one_parent",
        ),
        CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name="ck_attachment_size_non_negative"),
        Index("ix_attachments_organization_id", "organization_id"),
        Index("ix_attachments_hospital_id", "hospital_id"),
        Index("ix_attachments_device_id", "device_id"),
        Index("ix_attachments_ticket_id", "ticket_id"),
        Index("ix_attachments_maintenance_record_id", "maintenance_record_id"),
        Index("ix_attachments_uploaded_by", "uploaded_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="RESTRICT"))
    device_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"))
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("maintenance_tickets.id", ondelete="RESTRICT"))
    maintenance_record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("maintenance_records.id", ondelete="RESTRICT"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    file_url: Mapped[str] = mapped_column(String(500))
    file_name: Mapped[Optional[str]] = mapped_column(String(255))
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())

    uploader: Mapped[User] = relationship(lazy="selectin", foreign_keys=[uploaded_by])
