import uuid
from typing import Type

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.catalog import DeviceCategory, DeviceModel, Manufacturer
from app.models.user import User
from app.repositories.catalog_repository import CatalogRepository, T
from app.services.audit_service import AuditService, snapshot


class CatalogService:
    """Global device catalog. Not organization-scoped: it is shared by every hospital in the database.

    audit_logs.organization_id is required but catalog rows belong to no organization, so each
    catalog audit row carries the ACTING user's organization.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = CatalogRepository(db)
        self.audit = AuditService(db)

    def get(self, cls: Type[T], obj_id: uuid.UUID, label: str) -> T:
        obj = self.repo.get(cls, obj_id)
        if obj is None:
            raise NotFoundError(f"{label} not found.")
        return obj

    def create_simple(self, cls: Type[T], name: str, *, actor: User) -> T:
        obj = self.repo.add(cls(name=name))
        self.audit.inserted(actor.id, obj, organization_id=actor.organization_id)
        self.db.commit()
        return self.repo.get(cls, obj.id)

    def rename(self, cls: Type[T], obj_id: uuid.UUID, name: str, label: str, *, actor: User) -> T:
        obj = self.get(cls, obj_id, label)
        before = snapshot(obj)
        obj.name = name
        self.audit.updated(actor.id, obj, before, organization_id=actor.organization_id)
        self.db.commit()
        return obj

    def delete(self, cls: Type[T], obj_id: uuid.UUID, label: str, *, actor: User) -> None:
        obj = self.get(cls, obj_id, label)
        self.audit.deleted(actor.id, obj, organization_id=actor.organization_id)
        self.db.delete(obj)
        # PostgreSQL blocks it while models/devices still reference the row; the audit row then rolls back too.
        self.db.commit()

    # -- models -------------------------------------------------------------------
    def _check_parents(self, manufacturer_id, category_id) -> None:
        if manufacturer_id is not None and self.repo.get(Manufacturer, manufacturer_id) is None:
            raise BadRequestError("Manufacturer does not exist.")
        if category_id is not None and self.repo.get(DeviceCategory, category_id) is None:
            raise BadRequestError("Device category does not exist.")

    def create_model(self, manufacturer_id, category_id, name: str, *, actor: User) -> DeviceModel:
        self._check_parents(manufacturer_id, category_id)
        obj = self.repo.add(DeviceModel(manufacturer_id=manufacturer_id, device_category_id=category_id, name=name))
        self.audit.inserted(actor.id, obj, organization_id=actor.organization_id)
        self.db.commit()
        return self.repo.get(DeviceModel, obj.id)

    def update_model(self, model_id, changes: dict, *, actor: User) -> DeviceModel:
        obj = self.get(DeviceModel, model_id, "Device model")
        self._check_parents(changes.get("manufacturer_id"), changes.get("device_category_id"))
        before = snapshot(obj)
        for field, value in changes.items():
            setattr(obj, field, value)
        self.audit.updated(actor.id, obj, before, organization_id=actor.organization_id)
        self.db.commit()
        return self.repo.get(DeviceModel, obj.id)
