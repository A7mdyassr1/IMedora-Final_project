"""Device history feed schemas (B6 CP4).

One entry per event, newest first. `type` says which of the detail objects is filled in; the others
are null. People are shown as the viewer may see them: department users see staff as a role
description, never a name (decision Q9, the same PersonRef as tickets: app/schemas/person.py).
"""
import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.enums import QARecordType, QAStatus, RiskLevel, TicketPriority, TicketStatus
from app.schemas.maintenance import Performer
from app.schemas.person import PersonRef

EntryType = Literal["ticket_reported", "ticket_resolved", "maintenance_record", "risk_assessment", "qa_record"]


class HistoryTicket(BaseModel):
    id: uuid.UUID
    number: str
    priority: TicketPriority
    status: TicketStatus = Field(description="The ticket's CURRENT status (closed / cancelled have no time of their own).")
    reported_by: Optional[PersonRef] = Field(default=None, description="On `ticket_reported` entries.")


class HistoryMaintenanceRecord(BaseModel):
    id: uuid.UUID
    maintenance_type: str
    performed_by: Performer
    ticket_id: Optional[uuid.UUID] = None
    ticket_number: Optional[str] = None
    parts_count: int = Field(description="Number of different spare parts used.")


class HistoryRiskAssessment(BaseModel):
    id: uuid.UUID
    risk_level: RiskLevel
    assessed_by: Performer


class HistoryQARecord(BaseModel):
    id: uuid.UUID
    record_type: QARecordType
    status: QAStatus
    next_due_date: Optional[date] = None
    performed_by: Performer


class DeviceHistoryEntry(BaseModel):
    type: EntryType
    at: datetime
    ticket: Optional[HistoryTicket] = None
    maintenance_record: Optional[HistoryMaintenanceRecord] = None
    risk_assessment: Optional[HistoryRiskAssessment] = None
    qa_record: Optional[HistoryQARecord] = None
