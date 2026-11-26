"""QA record API schemas (B6 CP2).

Requests reject unknown fields (extra="forbid"). On CREATE the client names the target device
(`device_id`); the organization, hospital and performer are set by the server from the stored device
and the authenticated user, and are rejected if sent (D4b). On UPDATE the device, the record type and
every ownership / identity field are immutable: only status (pending -> pass / fail), findings,
performed_at and next_due_date may change. Responses show staff by name (only staff read QA records).
"""
import uuid
from datetime import date, datetime
from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.enums import QARecordType, QAStatus
from app.schemas.maintenance import Performer
from app.schemas.risk import RiskDevice

FINDINGS_MAX = 4000
Findings = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=FINDINGS_MAX)]


class QARecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: uuid.UUID = Field(description="The device checked (must be in your scope).")
    record_type: QARecordType
    status: QAStatus = Field(default=QAStatus.PENDING, description="`pending` (default) or the result: `pass` / `fail`. "
                                                                   "A pass or fail result is final.")
    findings: Optional[Findings] = None
    performed_at: Optional[datetime] = Field(default=None, description="Defaults to now. Not in the future. "
                                                                       "ISO 8601; UTC if no offset.")
    next_due_date: Optional[date] = Field(default=None, description="On or after the date the check was performed.")


class QARecordUpdate(BaseModel):
    """Status (pending -> pass / fail only) and corrections (engineers, admins).
    `findings: null` and `next_due_date: null` clear them."""
    model_config = ConfigDict(extra="forbid")
    status: Optional[QAStatus] = None
    findings: Optional[Findings] = None
    performed_at: Optional[datetime] = None
    next_due_date: Optional[date] = None

    @field_validator("status", "performed_at", mode="before")
    @classmethod
    def _no_explicit_null(cls, v):
        if v is None:
            raise ValueError("must not be null")
        return v

    @model_validator(mode="after")
    def _something(self):
        if not self.model_fields_set:
            raise ValueError("Nothing to change: give status, findings, performed_at and/or next_due_date.")
        return self


class QARecordResponse(BaseModel):
    id: uuid.UUID
    device: RiskDevice
    hospital_id: uuid.UUID
    record_type: QARecordType
    status: QAStatus
    findings: Optional[str] = None
    performed_at: datetime
    next_due_date: Optional[date] = None
    performed_by: Performer
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, r) -> "QARecordResponse":
        d = r.device
        return cls(
            id=r.id,
            device=RiskDevice(id=d.id, device_code=d.device_code, name=d.name, department_id=d.department_id,
                              department_name=d.department.name, is_archived=d.deleted_at is not None,
                              current_risk_level=d.current_risk_level),
            hospital_id=r.hospital_id, record_type=r.record_type, status=r.status, findings=r.findings,
            performed_at=r.performed_at, next_due_date=r.next_due_date,
            performed_by=Performer(id=r.performer.id, name=r.performer.full_name, role=r.performer.role.name),
            created_at=r.created_at, updated_at=r.updated_at,
        )


# ---- CP3 ----------------------------------------------------------------------------------------------
class QASummaryResponse(BaseModel):
    total: int
    by_status: Dict[str, int] = Field(description="pass, fail and pending, always all three.")
    by_type: Dict[str, int] = Field(description="inspection, calibration and compliance, always all three.")
    hospital_id: Optional[uuid.UUID] = None
    include_archived: bool


class QADueItem(QARecordResponse):
    due_status: Literal["overdue", "upcoming"]
    days_until_due: int = Field(description="Negative when overdue.")

    @classmethod
    def build_due(cls, r, today: date) -> "QADueItem":
        base = QARecordResponse.build(r).model_dump()
        days = (r.next_due_date - today).days
        return cls(**base, due_status="overdue" if days < 0 else "upcoming", days_until_due=days)


class QADueList(BaseModel):
    """The latest record per device and record type whose next due date is overdue or within
    `within_days` of `today` (the database's date). Superseded records are never listed."""
    items: List[QADueItem]
    total: int
    page: int
    page_size: int
    today: date
    within_days: int
    include_overdue: bool
