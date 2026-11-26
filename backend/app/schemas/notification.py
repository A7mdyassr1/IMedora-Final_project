"""Notification API schemas (B5 CP3) - the shape the mobile app's AppNotification expects:
id, type, title, body, related_ticket_id, is_read, created_at, read_at."""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import Page
from app.utils.ticket_number import ticket_number


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: Optional[str] = Field(description="ticket_created, ticket_assigned, ticket_status_changed, ticket_resolved, "
                                            "device_alert, or password_reset_requested for administrators (B8). "
                                            "Older rows may hold other values or none.")
    title: str
    body: Optional[str] = None
    related_ticket_id: Optional[uuid.UUID] = None
    ticket_number: Optional[str] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime

    @classmethod
    def build(cls, n) -> "NotificationResponse":
        return cls(id=n.id, type=n.notification_type, title=n.title, body=n.body, related_ticket_id=n.related_ticket_id,
                   ticket_number=ticket_number(n.related_ticket_id) if n.related_ticket_id else None,
                   is_read=n.is_read, read_at=n.read_at, created_at=n.created_at)


class NotificationPage(Page[NotificationResponse]):
    unread_count: int = Field(description="All of the caller's unread notifications (for the bell badge).")


class ReadAllResponse(BaseModel):
    updated: int = Field(description="How many notifications were marked as read.")
