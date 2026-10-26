import uuid
from typing import Type

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.catalog import DeviceCategory, DeviceModel, Manufacturer
from app.repositories.catalog_repository import CatalogRepository, T


class CatalogService:
    """Global device catalog. Not organization-scoped: it is shared by every hospital in the database."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = CatalogRepository(db)

    def get(self, cls: Type[T], obj_id: uuid.UUID, label: str) -> T:
        obj = self.repo.get(cls, obj_id)
        if obj is None:
            raise NotFoundError(f"{label} not found.")
        return obj

    def create_simple(self, cls: Type[T], name: str) -> T:
        obj = self.repo.add(cls(name=name))
        self.db.commit()
        return self.repo.get(cls, obj.id)

    def rename(self, cls: Type[T], obj_id: uuid.UUID, name: str, label: str) -> T:
        obj = self.get(cls, obj_id, label)
        obj.name = name
        self.db.commit()
        return obj

    def delete(self, cls: Type[T], obj_id: uuid.UUID, label: str) -> None:
        self.db.delete(self.get(cls, obj_id, label))
        self.db.commit()  # PostgreSQL blocks it while models/devices still reference the row

    # -- models -------------------------------------------------------------------
    def _check_parents(self, manufacturer_id, category_id) -> None:
        if manufacturer_id is not None and self.repo.get(Manufacturer, manufacturer_id) is None:
            raise BadRequestError("Manufacturer does not exist.")
        if category_id is not None and self.repo.get(DeviceCategory, category_id) is None:
            raise BadRequestError("Device category does not exist.")

    def create_model(self, manufacturer_id, category_id, name: str) -> DeviceModel:
        self._check_parents(manufacturer_id, category_id)
        obj = self.repo.add(DeviceModel(manufacturer_id=manufacturer_id, device_category_id=category_id, name=name))
        self.db.commit()
        return self.repo.get(DeviceModel, obj.id)

    def update_model(self, model_id, changes: dict) -> DeviceModel:
        obj = self.get(DeviceModel, model_id, "Device model")
        self._check_parents(changes.get("manufacturer_id"), changes.get("device_category_id"))
        for field, value in changes.items():
            setattr(obj, field, value)
        self.db.commit()
        return self.repo.get(DeviceModel, obj.id)
