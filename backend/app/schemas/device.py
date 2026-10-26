import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import Criticality, DeviceStatus, RiskLevel
from app.models.device import Device
from app.schemas.common import Code50, Name255, reject_explicit_nulls


class DeviceCreate(BaseModel):
    hospital_id: uuid.UUID
    department_id: uuid.UUID
    location_id: Optional[uuid.UUID] = None
    device_model_id: uuid.UUID
    device_code: Code50
    name: Name255
    serial_number: Optional[str] = Field(default=None, max_length=255)
    # Optional: generated when omitted (QR stickers are printed after registration).
    qr_identifier: Optional[str] = Field(
    default=None,
    min_length=1,
    max_length=255,
    pattern=r"^[A-Za-z0-9._-]+$"
)
    status: DeviceStatus = DeviceStatus.ACTIVE
    criticality: Criticality = Criticality.MEDIUM
    installation_date: Optional[date] = None
    warranty_expiry: Optional[date] = None  # warranty >= installation is enforced by PostgreSQL

    @field_validator("qr_identifier")
    @classmethod
    def normalize_qr(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value is not None else None

    @field_validator("status")
    @classmethod
    def prevent_manual_decommission(cls, value):
        if value == DeviceStatus.DECOMMISSIONED:
            raise ValueError(
                "Use the archive endpoint to decommission a device."
            )
        return value


class DeviceUpdate(BaseModel):
    """PATCH. hospital_id is intentionally not changeable: moving a device between
    hospitals is not supported by this phase."""

    model_config = ConfigDict(extra="forbid")

    department_id: Optional[uuid.UUID] = None
    location_id: Optional[uuid.UUID] = None  # explicit null detaches the location
    device_model_id: Optional[uuid.UUID] = None
    device_code: Optional[Code50] = None
    name: Optional[Name255] = None
    serial_number: Optional[str] = Field(default=None, max_length=255)
    qr_identifier: Optional[str] = Field(
    default=None,
    min_length=1,
    max_length=255,
    pattern=r"^[A-Za-z0-9._-]+$"
)
    status: Optional[DeviceStatus] = None
    criticality: Optional[Criticality] = None
    installation_date: Optional[date] = None
    warranty_expiry: Optional[date] = None

    @field_validator("qr_identifier")
    @classmethod
    def normalize_qr(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value is not None else None


    @field_validator("status")
    @classmethod
    def prevent_manual_decommission(cls, value):
        if value == DeviceStatus.DECOMMISSIONED:
            raise ValueError(
                "Use the archive endpoint to decommission a device."
            )
        return value


    @model_validator(mode="after")
    def _nulls(self):
        reject_explicit_nulls(
            self, ("department_id", "device_model_id", "device_code", "name", "qr_identifier", "status", "criticality")
        )
        return self


class DeviceResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hospital_id: uuid.UUID
    hospital_name: str
    department_id: uuid.UUID
    department_name: str
    location_id: Optional[uuid.UUID] = None
    location: Optional[str] = None
    device_model_id: uuid.UUID
    model_name: str
    manufacturer_id: uuid.UUID
    manufacturer_name: str
    category_id: uuid.UUID
    category_name: str
    device_code: str
    name: str
    serial_number: Optional[str] = None
    qr_identifier: str
    status: DeviceStatus
    criticality: Criticality
    current_risk_level: Optional[RiskLevel] = None
    installation_date: Optional[date] = None
    warranty_expiry: Optional[date] = None
    next_maintenance_due_date: Optional[date] = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_device(cls, d: Device) -> "DeviceResponse":
        return cls(
            id=d.id, organization_id=d.organization_id,
            hospital_id=d.hospital_id, hospital_name=d.hospital.name,
            department_id=d.department_id, department_name=d.department.name,
            location_id=d.location_id, location=d.location.label if d.location else None,
            device_model_id=d.device_model_id, model_name=d.model.name,
            manufacturer_id=d.model.manufacturer_id, manufacturer_name=d.model.manufacturer.name,
            category_id=d.model.device_category_id, category_name=d.model.category.name,
            device_code=d.device_code, name=d.name, serial_number=d.serial_number,
            qr_identifier=d.qr_identifier, status=d.status, criticality=d.criticality,
            current_risk_level=d.current_risk_level, installation_date=d.installation_date,
            warranty_expiry=d.warranty_expiry, next_maintenance_due_date=d.next_maintenance_due_date,
            is_archived=d.is_archived, created_at=d.created_at, updated_at=d.updated_at,
        )
