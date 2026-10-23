import uuid
from typing import List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.user import User


class UserRepository:
    """Data access only: flushes but never commits (services own the transaction)."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: uuid.UUID, organization_id: Optional[uuid.UUID] = None) -> Optional[User]:
        stmt = select(User).where(User.id == user_id).execution_options(populate_existing=True)
        if organization_id is not None:
            stmt = stmt.where(User.organization_id == organization_id)
        return self.db.scalars(stmt).first()

    def get_by_email(self, email: str) -> Optional[User]:
        # Case-insensitive: the DB unique index is case-sensitive, so older rows may be mixed-case.
        return self.db.scalars(select(User).where(func.lower(User.email) == email.strip().lower())).first()

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        return user

    def list_page(
        self,
        organization_id: uuid.UUID,
        page: int,
        page_size: int,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        hospital_id: Optional[uuid.UUID] = None,
        q: Optional[str] = None,
    ) -> Tuple[List[User], int]:
        conditions = [User.organization_id == organization_id, User.deleted_at.is_(None)]
        if is_active is not None:
            conditions.append(User.is_active == is_active)
        if hospital_id is not None:
            conditions.append(User.hospital_id == hospital_id)
        if q:
            like = f"%{q.strip()}%"
            conditions.append(or_(User.full_name.ilike(like), User.email.ilike(like)))

        count_stmt = select(func.count()).select_from(User).where(*conditions)
        items_stmt = select(User).where(*conditions)
        if role:
            count_stmt = count_stmt.join(Role, Role.id == User.role_id).where(Role.name == role)
            items_stmt = items_stmt.join(Role, Role.id == User.role_id, isouter=False).where(Role.name == role)

        total = self.db.scalar(count_stmt) or 0
        items = list(
            self.db.scalars(items_stmt.order_by(User.full_name, User.id).limit(page_size).offset((page - 1) * page_size))
            .unique()
            .all()
        )
        return items, total
