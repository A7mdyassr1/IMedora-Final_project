import logging
import secrets
from datetime import datetime, timezone
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import DeviceStatus
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.models.catalog import DeviceModel
from app.models.device import Device
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.device_repository import DeviceFilters, DeviceRepository
from app.repositories.hospital_repository import HospitalRepository
from app.schemas.device import DeviceCreate, DeviceUpdate
from app.services.audit_service import AuditService, snapshot
from app.services.notification_service import Notifier

logger = logging.getLogger(__name__)


def generate_qr_identifier() -> str:
    return f"IMD-{secrets.token_hex(6).upper()}"


class DeviceService:
    def __init__(self, db: Session):
        self.db = db
        self.devices = DeviceRepository(db)
        self.structure = HospitalRepository(db)
        self.catalog = CatalogRepository(db)
        self.audit = AuditService(db)

    # -- validation helpers ------------------------------------------------------
    def _check_placement(self, org_id, hospital_id, department_id=None, location_id=None, require_active: bool = False) -> None:
        hospital = self.structure.get_in_organization(org_id, hospital_id)
        if hospital is None:
            raise BadRequestError("Hospital does not exist in your organization.")
        if require_active and not hospital.is_active:  # Decision 6: nothing new is added to an inactive hospital
            raise BadRequestError("Hospital is inactive; devices cannot be added to it.")
        if department_id is not None and self.structure.get_department_in_hospital(hospital_id, department_id) is None:
            raise BadRequestError("Department does not belong to this device's hospital.")
        if location_id is not None and self.structure.get_location_in_hospital(hospital_id, location_id) is None:
            raise BadRequestError("Location does not belong to this device's hospital.")

    def _check_model(self, model_id) -> None:
        if self.catalog.get(DeviceModel, model_id) is None:
            raise BadRequestError("Device model does not exist.")

    # -- operations ---------------------------------------------------------------
    def create(self, scope: AccessScope, data: DeviceCreate) -> Device:
        org_id = scope.organization_id
        scope.require_device_access()
        # CP3: an engineer may only register devices in their own hospital. Another hospital gets
        # exactly the answer a non-existent hospital gets (existing 400 convention), so the API
        # does not reveal which hospital ids exist. Department and location are then checked
        # against that same hospital by _check_placement.
        if scope.device_hospital_id is not None and data.hospital_id != scope.device_hospital_id:
            raise BadRequestError("Hospital does not exist in your organization.")
        self._check_placement(org_id, data.hospital_id, data.department_id, data.location_id, require_active=True)
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
        self.audit.inserted(scope.user_id, device)
        # Duplicate code/QR and warranty-date rules are enforced (and explained) via PostgreSQL;
        # if the commit fails, the audit row is rolled back with it.
        self.db.commit()
        logger.info("Device created id=%s", device.id)
        return self.get(scope, device.id)

    def get(self, scope: AccessScope, device_id) -> Device:
        """404 both for unknown devices and for devices outside the caller's scope (never 403:
        the API must not reveal that a device exists in another hospital or department)."""
        scope.require_device_access()
        d = self.devices.get(scope, device_id)
        if d is None:
            raise NotFoundError("Device not found.")
        return d

    def get_by_qr(self, scope: AccessScope, qr_identifier: str) -> Device:
        d = self.devices.get_by_qr(scope.qr_lookup_scope(), qr_identifier)
        if d is None:
            raise NotFoundError("No device found for this QR code.")
        return d

    def list(self, scope: AccessScope, filters: DeviceFilters, sort: str, descending: bool, page: int, page_size: int) -> Tuple[List[Device], int]:
        scope.require_device_access()
        if filters.include_archived and not scope.is_admin:  # Decision 6 / CP3: admins only, never ignored silently
            raise ForbiddenError("Only administrators can include archived devices.")
        return self.devices.list(scope, filters, sort, descending, page, page_size)

    def update(self, scope: AccessScope, device_id, data: DeviceUpdate) -> Device:
        org_id = scope.organization_id
        d = self.get(scope, device_id)  # a device outside the caller's scope is a 404
        if d.is_archived:
            raise BadRequestError("Archived devices cannot be modified.")
        changes = data.model_dump(exclude_unset=True)

        if "department_id" in changes or "location_id" in changes:
            self._check_placement(
                org_id, d.hospital_id, changes.get("department_id"), changes.get("location_id"),
            )
        if "device_model_id" in changes:
            self._check_model(changes["device_model_id"])
        # Devices cannot move between hospitals here, so editing a device inside an inactive
        # hospital stays allowed (Decision 6 only blocks adding new records).
        before = snapshot(d)
        old_status = d.status
        for field, value in changes.items():
            setattr(d, field, value)
        self.audit.updated(scope.user_id, d, before)
        # B5: department users of the device hear when it goes out of / back into service
        Notifier(self.db, self.audit).device_status_changed(scope.user_id, d, old_status, d.status)
        self.db.commit()
        logger.info("Device updated id=%s fields=%s by=%s", d.id, sorted(changes), scope.user_id)
        return self.get(scope, d.id)

    def archive(self, scope: AccessScope, device_id) -> Device:
        """Soft delete: devices with history can't be physically deleted (RESTRICT) and shouldn't be."""
        d = self.get(scope, device_id)  # a device outside the caller's scope is a 404
        if not d.is_archived:
            before = snapshot(d)
            d.deleted_at = datetime.now(timezone.utc)
            d.status = DeviceStatus.DECOMMISSIONED
            self.audit.updated(scope.user_id, d, before)  # archive = UPDATE (soft delete), not DELETE
            self.db.commit()
            logger.info("Device archived id=%s by=%s", d.id, scope.user_id)
        return self.get(scope, d.id)
