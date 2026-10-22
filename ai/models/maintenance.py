"""Maintenance models - AI-facing view of `maintenance_records` (and the
`maintenance_schedules`/`maintenance_tickets` it may optionally link to)."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

MaintenanceType = Literal["preventive", "corrective"]


class MaintenanceEvent(BaseModel):
    """One completed maintenance record."""

    record_id: str
    device_id: str
    maintenance_type: MaintenanceType
    description: str
    performed_at: datetime
    performed_by: Optional[str] = None
    ticket_id: Optional[str] = None
    schedule_id: Optional[str] = None
    parts_used: List[str] = Field(default_factory=list, description="Part names consumed in this event.")


class MaintenanceSchedule(BaseModel):
    """A recurring preventive maintenance plan for a device."""

    schedule_id: str
    device_id: str
    maintenance_type: MaintenanceType
    frequency_days: int
    next_due_date: Optional[str] = None
    last_performed_date: Optional[str] = None
    is_active: bool = True
