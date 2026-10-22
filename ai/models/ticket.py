"""Ticket models - AI-facing view of `maintenance_tickets` + `ticket_assignments`."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

TicketPriority = Literal["low", "medium", "high", "critical"]
TicketStatus = Literal[
    "open", "assigned", "in_progress", "waiting_for_parts", "resolved", "closed", "cancelled"
]


class TicketContext(BaseModel):
    ticket_id: str
    device_id: str
    device_code: Optional[str] = None
    problem_description: str
    priority: TicketPriority
    status: TicketStatus
    reported_by: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    assigned_technicians: List[str] = Field(default_factory=list)
