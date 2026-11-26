"""Risk assessment API schemas (B6 CP1).

Requests reject unknown fields (extra="forbid"). On CREATE the client names the target device
(`device_id`); the organization, hospital and assessor are set by the server from the stored
device and the authenticated user, and are rejected if sent (D4b). On CORRECTION the device and
every ownership / identity field are immutable: only risk_level, notes and assessed_at may change.
Responses show staff by name (only staff can read risk assessments).
"""
import uuid
from datetime import datetime
from typing import Annotated, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.enums import RiskLevel
from app.schemas.maintenance import Performer

NOTES_MAX = 4000
Notes = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTES_MAX)]


class RiskAssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: uuid.UUID = Field(description="The device being assessed (must be in your scope).")
    risk_level: RiskLevel
    notes: Optional[Notes] = None
    assessed_at: Optional[datetime] = Field(default=None, description="Defaults to now (the server time when the "
                                                                      "assessment is saved). Not in the future. "
                                                                      "ISO 8601; UTC if no offset.")


class RiskAssessmentUpdate(BaseModel):
    """Corrections (engineers, admins). `notes: null` clears the notes."""
    model_config = ConfigDict(extra="forbid")
    risk_level: Optional[RiskLevel] = None
    notes: Optional[Notes] = None
    assessed_at: Optional[datetime] = None

    @field_validator("risk_level", "assessed_at", mode="before")
    @classmethod
    def _no_explicit_null(cls, v):
        if v is None:
            raise ValueError("must not be null")
        return v

    @model_validator(mode="after")
    def _something(self):
        if not self.model_fields_set:
            raise ValueError("Nothing to change: give risk_level, notes and/or assessed_at.")
        return self


class RiskDevice(BaseModel):
    id: uuid.UUID
    device_code: str
    name: str
    department_id: uuid.UUID
    department_name: str
    is_archived: bool
    current_risk_level: Optional[RiskLevel] = Field(
        default=None, description="The device's current level, maintained by the database from its latest assessment.")


class RiskAssessmentResponse(BaseModel):
    id: uuid.UUID
    device: RiskDevice
    hospital_id: uuid.UUID
    risk_level: RiskLevel
    notes: Optional[str] = None
    assessed_at: datetime
    assessed_by: Performer
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, a) -> "RiskAssessmentResponse":
        d = a.device
        return cls(
            id=a.id,
            device=RiskDevice(id=d.id, device_code=d.device_code, name=d.name, department_id=d.department_id,
                              department_name=d.department.name, is_archived=d.deleted_at is not None,
                              current_risk_level=d.current_risk_level),
            hospital_id=a.hospital_id, risk_level=a.risk_level, notes=a.notes, assessed_at=a.assessed_at,
            assessed_by=Performer(id=a.assessor.id, name=a.assessor.full_name, role=a.assessor.role.name),
            created_at=a.created_at, updated_at=a.updated_at,
        )


class RiskSummaryResponse(BaseModel):
    """CP3. Devices counted by their current risk level as maintained by the database (latest
    assessment), plus `unassessed` (no assessment yet)."""
    total: int
    by_level: Dict[str, int] = Field(description="low, medium, high, critical and unassessed, always all five.")
    hospital_id: Optional[uuid.UUID] = None
    include_archived: bool
