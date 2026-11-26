"""In-app notifications (B5 CP3) - exact mirror of the `notifications` table (migration 0005 + the
0006 index).

Database rules declared here (enforced by PostgreSQL):
- A notification belongs to ONE user (user_id, ON DELETE CASCADE - the one CASCADE to users in
  the schema: a notification has no audit value once its user is gone).
- is_read = true needs read_at (ck_notification_read_has_timestamp), and read_at >= created_at
  (ck_notification_read_after_created): the backend sets read_at with the DATABASE clock.
- related_ticket_id is SET NULL when the ticket row is deleted (tickets are only soft-deleted).
- notification_type is free text; the backend writes the five types the mobile app knows, plus
  `password_reset_requested` for administrators (B8).
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, FetchedValue, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("NOT is_read OR read_at IS NOT NULL", name="ck_notification_read_has_timestamp"),
        CheckConstraint("read_at IS NULL OR read_at >= created_at", name="ck_notification_read_after_created"),
        Index("ix_notifications_user_unread", "user_id", "is_read"),
        Index("ix_notifications_organization_id", "organization_id"),
        Index("ix_notifications_related_ticket_id", "related_ticket_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    related_ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("maintenance_tickets.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[Optional[str]] = mapped_column(Text)
    notification_type: Mapped[Optional[str]] = mapped_column(String(50))
    is_read: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())
