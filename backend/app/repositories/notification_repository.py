"""Notifications (B5 CP3): a user's own inbox, and the recipient lookups of the producers.

Every read is limited to the caller's own rows (user_id AND organization_id): there is no way to
read or change another user's notification, whatever the role - other users' ids are 404.
Unread counts and lists use ix_notifications_user_unread (user_id, is_read).
"""
import uuid
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.roles import Role
from app.models.notification import Notification
from app.models.role import Role as RoleRow
from app.models.user import User
from app.repositories.pagination import paginate


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- inbox ----------------------------------------------------------------------------------------
    def _own(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> list:
        return [Notification.user_id == user_id, Notification.organization_id == organization_id]

    def list_own(self, user_id: uuid.UUID, organization_id: uuid.UUID, unread_only: bool, page: int,
                 page_size: int) -> Tuple[List[Notification], int]:
        stmt = select(Notification).where(*self._own(user_id, organization_id))
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
        return paginate(self.db, stmt, page, page_size)

    def unread_count(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> int:
        return self.db.scalar(select(func.count()).select_from(Notification).where(
            *self._own(user_id, organization_id), Notification.is_read.is_(False))) or 0

    def get_own(self, user_id: uuid.UUID, organization_id: uuid.UUID, notification_id: uuid.UUID,
                for_update: bool = False) -> Optional[Notification]:
        stmt = select(Notification).where(Notification.id == notification_id, *self._own(user_id, organization_id))
        if for_update:
            stmt = stmt.with_for_update()
        return self.db.scalars(stmt.execution_options(populate_existing=True)).first()

    def mark_all_read(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> List[Tuple[uuid.UUID, datetime]]:
        """One UPDATE; read_at from the database clock (CHECK read_at >= created_at).
        Returns (id, read_at) of the rows it marked."""
        result = self.db.execute(
            update(Notification)
            .where(*self._own(user_id, organization_id), Notification.is_read.is_(False))
            .values(is_read=True, read_at=func.now())
            .returning(Notification.id, Notification.read_at)
            .execution_options(synchronize_session=False)
        )
        return [(row[0], row[1]) for row in result]

    def add_all(self, rows: List[Notification]) -> None:
        self.db.add_all(rows)
        self.db.flush()

    # ---- recipients -------------------------------------------------------------------------------------
    @staticmethod
    def _reachable(organization_id: uuid.UUID):
        """Users who can still sign in to read a notification: active and not deleted."""
        return (select(User.id).join(RoleRow, RoleRow.id == User.role_id)
                .where(User.organization_id == organization_id, User.is_active.is_(True), User.deleted_at.is_(None)))

    def reachable(self, organization_id: uuid.UUID, user_ids: Iterable[uuid.UUID]) -> List[uuid.UUID]:
        ids = {i for i in user_ids if i is not None}
        if not ids:
            return []
        return list(self.db.scalars(self._reachable(organization_id).where(User.id.in_(ids))))

    def hospital_staff(self, organization_id: uuid.UUID, hospital_id: uuid.UUID, roles: Iterable[str]) -> List[uuid.UUID]:
        return list(self.db.scalars(self._reachable(organization_id)
                                    .where(User.hospital_id == hospital_id, RoleRow.name.in_(list(roles)))))

    def department_users(self, organization_id: uuid.UUID, department_id: uuid.UUID, role: str) -> List[uuid.UUID]:
        return list(self.db.scalars(self._reachable(organization_id)
                                    .where(User.department_id == department_id, RoleRow.name == role)))

    def organization_admins(self, organization_id: uuid.UUID) -> List[uuid.UUID]:
        return list(self.db.scalars(self._reachable(organization_id).where(RoleRow.name == Role.ADMIN.value)))

    def unread_of(self, kind: str, body: str, user_ids: Iterable[uuid.UUID]) -> set:
        """Which of `user_ids` still have an UNREAD notification of this type and text."""
        ids = list(user_ids)
        if not ids:
            return set()
        return set(self.db.scalars(select(Notification.user_id).where(
            Notification.user_id.in_(ids), Notification.notification_type == kind, Notification.body == body,
            Notification.is_read.is_(False))))
