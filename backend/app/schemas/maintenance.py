"""Maintenance API schemas (B4 CP3): types, records, schedules.

Requests reject unknown fields: organization, hospital, performer and schedule dates derived by
the server cannot be sent. Responses show staff by name (only staff can read maintenance data).
"""
import uuid
from datetime import date, datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.utils.ticket_number import ticket_number

RECORD_DESCRIPTION_MAX = 4000
MAX_FREQUENCY_DAYS = 3650  # ten years


# ---- types ---------------------------------------------------------------------------------------
class MaintenanceTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=50)]


class MaintenanceTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


# ---- shared response pieces ------------------------------------------------------------------------
class MaintenanceDevice(BaseModel):
    id: uuid.UUID
    device_code: str
    name: str
    department_id: uuid.UUID
    department_name: str
    is_archived: bool


class Performer(BaseModel):
    id: uuid.UUID
    name: str
    role: str


def _device(d) -> MaintenanceDevice:
    return MaintenanceDevice(id=d.id, device_code=d.device_code, name=d.name, department_id=d.department_id,
                             department_name=d.department.name, is_archived=d.deleted_at is not None)


# ---- records -------------------------------------------------------------------------------------
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=RECORD_DESCRIPTION_MAX)]


class MaintenanceRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: uuid.UUID
    maintenance_type_id: uuid.UUID
    description: Description
    performed_at: Optional[datetime] = Field(default=None, description="Defaults to now. ISO 8601; UTC if no offset.")
    ticket_id: Optional[uuid.UUID] = Field(default=None, description="Corrective work on this ticket (same device).")
    schedule_id: Optional[uuid.UUID] = Field(default=None, description="Preventive work for this schedule (same device and type).")


class MaintenanceRecordUpdate(BaseModel):
    """Corrections only (engineers, admins). Device, type, ticket, schedule and performer are history."""
    model_config = ConfigDict(extra="forbid")
    description: Optional[Description] = None
    performed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _something(self):
        if self.description is None and self.performed_at is None:
            raise ValueError("Nothing to change: give description and/or performed_at.")
        return self


class MaintenanceRecordResponse(BaseModel):
    id: uuid.UUID
    device: MaintenanceDevice
    hospital_id: uuid.UUID
    maintenance_type: MaintenanceTypeResponse
    ticket_id: Optional[uuid.UUID] = None
    ticket_number: Optional[str] = None
    schedule_id: Optional[uuid.UUID] = None
    performed_by: Performer
    description: str
    performed_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, r) -> "MaintenanceRecordResponse":
        return cls(
            id=r.id, device=_device(r.device), hospital_id=r.hospital_id,
            maintenance_type=MaintenanceTypeResponse.model_validate(r.maintenance_type),
            ticket_id=r.ticket_id, ticket_number=ticket_number(r.ticket_id) if r.ticket_id else None,
            schedule_id=r.schedule_id,
            performed_by=Performer(id=r.performer.id, name=r.performer.full_name, role=r.performer.role.name),
            description=r.description, performed_at=r.performed_at, created_at=r.created_at, updated_at=r.updated_at,
        )


# ---- schedules -----------------------------------------------------------------------------------
Frequency = Annotated[int, Field(ge=1, le=MAX_FREQUENCY_DAYS, description="Days between services.")]


class MaintenanceScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: uuid.UUID
    maintenance_type_id: uuid.UUID
    frequency_days: Frequency
    next_due_date: date


class MaintenanceScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency_days: Optional[Frequency] = None
    next_due_date: Optional[date] = None
    is_active: Optional[bool] = None

    @field_validator("frequency_days", "next_due_date", "is_active", mode="before")
    @classmethod
    def _no_explicit_null(cls, v):
        if v is None:
            raise ValueError("must not be null")
        return v

    @model_validator(mode="after")
    def _something(self):
        if not self.model_fields_set:
            raise ValueError("Nothing to change: give frequency_days, next_due_date and/or is_active.")
        return self


class MaintenanceScheduleResponse(BaseModel):
    id: uuid.UUID
    device: MaintenanceDevice
    hospital_id: uuid.UUID
    maintenance_type: MaintenanceTypeResponse
    frequency_days: int
    next_due_date: date
    last_performed_date: Optional[date] = None
    is_active: bool
    is_overdue: bool = Field(description="Active and due before today.")
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, s, today: date) -> "MaintenanceScheduleResponse":
        return cls(
            id=s.id, device=_device(s.device), hospital_id=s.hospital_id,
            maintenance_type=MaintenanceTypeResponse.model_validate(s.maintenance_type),
            frequency_days=s.frequency_days, next_due_date=s.next_due_date, last_performed_date=s.last_performed_date,
            is_active=s.is_active, is_overdue=bool(s.is_active and s.next_due_date < today),
            created_at=s.created_at, updated_at=s.updated_at,
        )
