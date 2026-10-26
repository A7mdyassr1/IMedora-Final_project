import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.core.enums import DeviceStatus
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.catalog import DeviceModel
from app.models.device import Device
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.device_repository import DeviceFilters, DeviceRepository
from app.repositories.hospital_repository import HospitalRepository
from app.schemas.device import DeviceCreate, DeviceUpdate

logger = logging.getLogger(__name__)


def generate_qr_identifier() -> str:
    return f"IMD-{secrets.token_hex(6).upper()}"


class DeviceService:
    def __init__(self, db: Session):
        self.db = db
        self.devices = DeviceRepository(db)
        self.structure = HospitalRepository(db)
        self.catalog = CatalogRepository(db)

    # -- validation helpers ------------------------------------------------------
    def _check_placement(self, org_id, hospital_id, department_id=None, location_id=None) -> None:
        if self.structure.get_in_organization(org_id, hospital_id) is None:
            raise BadRequestError("Hospital does not exist in your organization.")
        if department_id is not None and self.structure.get_department_in_hospital(hospital_id, department_id) is None:
            raise BadRequestError("Department does not belong to this device's hospital.")
        if location_id is not None and self.structure.get_location_in_hospital(hospital_id, location_id) is None:
            raise BadRequestError("Location does not belong to this device's hospital.")

    def _check_model(self, model_id) -> None:
        if self.catalog.get(DeviceModel, model_id) is None:
            raise BadRequestError("Device model does not exist.")

    # -- operations ---------------------------------------------------------------
    def create(self, org_id: uuid.UUID, data: DeviceCreate) -> Device:
        self._check_placement(org_id, data.hospital_id, data.department_id, data.location_id)
        self._check_model(data.device_model_id)
        device = self.devices.add(
            Device(
                organization_id=org_id, hospital_id=data.hospital_id, department_id=data.department_id,
                location_id=data.location_id, device_model_id=data.device_model_id,
                device_code=data.device_code, name=data.name, serial_number=data.serial_number,
                qr_identifier=data.qr_identifier or generate_qr_identifier(),
                status=data.status, criticality=data.criticality,
                installation_date=data.installation_date, warranty_expiry=data.warranty_expiry,
            )
        )
        self.db.commit()  # duplicate code/QR and warranty-date rules are enforced (and explained) via PostgreSQL
        logger.info("Device created id=%s", device.id)
        return self.get(org_id, device.id)

    def get(self, org_id, device_id) -> Device:
        d = self.devices.get(org_id, device_id)
        if d is None:
            raise NotFoundError("Device not found.")
        return d

    def get_by_qr(self, org_id, qr_identifier: str) -> Device:
        d = self.devices.get_by_qr(org_id, qr_identifier)
        if d is None:
            raise NotFoundError("No device found for this QR code.")
        return d

    def list(self, org_id, filters: DeviceFilters, sort: str, descending: bool, page: int, page_size: int) -> Tuple[List[Device], int]:
        return self.devices.list(org_id, filters, sort, descending, page, page_size)

    def update(self, org_id, device_id, data: DeviceUpdate, acting_user_id) -> Device:
        d = self.get(org_id, device_id)
        if d.is_archived:
            raise BadRequestError("Archived devices cannot be modified.")
        changes = data.model_dump(exclude_unset=True)

        if "department_id" in changes or "location_id" in changes:
            self._check_placement(
                org_id, d.hospital_id, changes.get("department_id"), changes.get("location_id"),
            )
        if "device_model_id" in changes:
            self._check_model(changes["device_model_id"])
        for field, value in changes.items():
            setattr(d, field, value)
        self.db.commit()
        logger.info("Device updated id=%s fields=%s by=%s", d.id, sorted(changes), acting_user_id)
        return self.get(org_id, d.id)

    def archive(self, org_id, device_id, acting_user_id) -> Device:
        """Soft delete: devices with history can't be physically deleted (RESTRICT) and shouldn't be."""
        d = self.get(org_id, device_id)
        if not d.is_archived:
            d.deleted_at = datetime.now(timezone.utc)
            d.status = DeviceStatus.DECOMMISSIONED
            self.db.commit()
            logger.info("Device archived id=%s by=%s", d.id, acting_user_id)
        return self.get(org_id, d.id)
