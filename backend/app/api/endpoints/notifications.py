"""The caller's own in-app notifications (B5 CP3). Every role; nobody can read or change another
user's notifications (404). Notifications are created by the server when tickets and devices change."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Pagination, pagination_params
from app.core.access import scope_for
from app.core.database import get_db
from app.models.user import User
from app.schemas.notification import NotificationPage, NotificationResponse, ReadAllResponse
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage, summary="My notifications (newest first)")
def list_notifications(p: Pagination = Depends(pagination_params), unread_only: bool = False,
                       user: User = CurrentUser, db: Session = Depends(get_db)):
    items, total, unread = NotificationService(db).list(scope_for(user), unread_only, p.page, p.page_size)
    return NotificationPage(items=[NotificationResponse.build(n) for n in items], total=total, page=p.page,
                            page_size=p.page_size, unread_count=unread)


@router.patch("/{notification_id}/read", response_model=NotificationResponse, summary="Mark one notification as read",
              description="Idempotent: an already read notification keeps its first read time.")
def mark_read(notification_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return NotificationResponse.build(NotificationService(db).mark_read(scope_for(user), notification_id))


@router.post("/read-all", response_model=ReadAllResponse, summary="Mark all my notifications as read")
def mark_all_read(user: User = CurrentUser, db: Session = Depends(get_db)):
    return ReadAllResponse(updated=NotificationService(db).mark_all_read(scope_for(user)))
