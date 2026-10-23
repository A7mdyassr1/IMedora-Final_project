from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.roles import Role as RoleName
from app.models.role import Role


class RoleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_name(self, name: str) -> Optional[Role]:
        return self.db.scalars(select(Role).where(Role.name == name)).first()

    def ensure_standard_roles(self) -> None:
        """Inserts any of the four standard roles that are missing (idempotent). Does not commit."""
        stmt = pg_insert(Role).values([{"name": r.value} for r in RoleName]).on_conflict_do_nothing(index_elements=["name"])
        self.db.execute(stmt)
