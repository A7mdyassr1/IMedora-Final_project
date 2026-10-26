"""Global device catalog queries (categories / manufacturers / models)."""
import uuid
from typing import List, Optional, Tuple, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import DeviceCategory, DeviceModel, Manufacturer
from app.repositories.pagination import paginate

T = TypeVar("T", DeviceCategory, Manufacturer, DeviceModel)


class CatalogRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, cls: Type[T], obj_id: uuid.UUID) -> Optional[T]:
        return self.db.scalars(select(cls).where(cls.id == obj_id).execution_options(populate_existing=True)).first()

    def add(self, obj):
        self.db.add(obj)
        self.db.flush()
        return obj

    def list(self, cls: Type[T], page, page_size, q: Optional[str] = None, **filters) -> Tuple[List[T], int]:
        stmt = select(cls)
        if q:
            stmt = stmt.where(cls.name.ilike(f"%{q.strip()}%"))
        for column, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(cls, column) == value)
        return paginate(self.db, stmt.order_by(cls.name, cls.id), page, page_size)
