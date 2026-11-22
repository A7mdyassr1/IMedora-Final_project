"""Maintenance-ticket API schemas (B4), built on `TicketNumberMixin` (B3.1 CP2).

Every ticket response schema inherits `TicketNumberMixin`, which adds a read-only `number`
field computed from `id`:

    class TicketResponse(TicketNumberMixin):
        id: uuid.UUID            # still the identifier used by every API call
        status: TicketStatus
        ...

    TicketResponse.model_validate(ticket_orm_row, from_attributes=True)
    # -> {"id": "3f9a1c2b-...", "number": "TKT-3F9A1C2B", "status": ...}

`number` is computed on serialization only: it cannot be sent by a client, is not stored,
and needs no database column or query.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field

from app.core.enums import TicketPriority, TicketStatus
from app.services.ticket_timeline import Person, TimelineItem, TimelineKind, person_display
from app.utils.problem_category import ProblemCategory, parse
from app.utils.ticket_number import ticket_number

if TYPE_CHECKING:  # pragma: no cover
    from app.core.access import AccessScope
    from app.models.ticket import MaintenanceTicket

DESCRIPTION_MAX_LENGTH = 2000


class TicketNumberMixin(BaseModel):
    id: uuid.UUID

    @computed_field(
        description="Short human-readable ticket number derived from the UUID, e.g. TKT-3F9A1C2B. "
                    "Display only; use `id` to address the ticket.",
        examples=["TKT-3F9A1C2B"],
    )
    @property
    def number(self) -> str:
        return ticket_number(self.id)


# ---- requests ---------------------------------------------------------------------------------

class TicketCreate(BaseModel):
    """POST /tickets - "report a problem" (mobile: NewTicketRequest).

    Organization, hospital and reporter come from the device and the token, status is always
    `open`: none of them can be sent (unknown fields are rejected)."""
    model_config = ConfigDict(extra="forbid")

    device_id: uuid.UUID
    category: ProblemCategory = Field(description="One of the six labels the mobile app shows.")
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=DESCRIPTION_MAX_LENGTH)]
    # Optional, and null is accepted: the mobile app sends null for "let the backend decide".
    priority: Optional[TicketPriority] = Field(default=None, description="Defaults to medium.")


# ---- responses --------------------------------------------------------------------------------

class TicketDevice(BaseModel):
    """Identifying device fields only - never serial number, risk, criticality or dates, so a
    ticket on another department's device reveals nothing beyond the limited QR view."""
    id: uuid.UUID
    device_code: str
    name: str
    department_id: uuid.UUID
    department_name: str


class PersonRef(BaseModel):
    """A person as the viewer may see them. For department users, staff appear as a role
    description only: `id` is null and `name` is e.g. "Technician" (decision Q9)."""
    id: Optional[uuid.UUID] = None
    name: str
    role: str


class TicketAssignee(PersonRef):
    assigned_at: datetime


class TicketTimelineItem(BaseModel):
    at: datetime
    kind: TimelineKind
    status: TicketStatus = Field(description="The ticket's status after this event.")
    message: str
    actor: Optional[str] = None


def _person(user, scope: "AccessScope") -> PersonRef:
    p = Person(user.id, user.full_name, user.role.name)
    visible = scope.sees_staff_names or user.id == scope.user_id
    return PersonRef(id=user.id if visible else None, name=person_display(p, scope.user_id, scope.sees_staff_names), role=p.role)


class TicketResponse(TicketNumberMixin):
    status: TicketStatus
    priority: TicketPriority
    category: ProblemCategory
    description: str
    device: TicketDevice
    hospital_id: uuid.UUID
    reported_by: PersonRef
    assignees: List[TicketAssignee] = Field(description="Currently assigned staff.")
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None

    @classmethod
    def build(cls, t: "MaintenanceTicket", scope: "AccessScope", **extra) -> "TicketResponse":
        category, description = parse(t.problem_description)
        d = t.device
        return cls(
            id=t.id, status=t.status, priority=t.priority, category=category, description=description,
            device=TicketDevice(id=d.id, device_code=d.device_code, name=d.name,
                                department_id=d.department_id, department_name=d.department.name),
            hospital_id=t.hospital_id,
            reported_by=_person(t.reporter, scope),
            assignees=[TicketAssignee(**_person(a.user, scope).model_dump(), assigned_at=a.assigned_at)
                       for a in t.active_assignments],
            is_deleted=t.is_deleted, created_at=t.created_at, updated_at=t.updated_at, resolved_at=t.resolved_at,
            **extra,
        )


class TicketDetailResponse(TicketResponse):
    timeline: List[TicketTimelineItem] = Field(description="Derived history, oldest first.")

    @classmethod
    def build_detail(cls, t: "MaintenanceTicket", scope: "AccessScope", timeline: List[TimelineItem]) -> "TicketDetailResponse":
        items = [TicketTimelineItem(at=i.at, kind=i.kind, status=i.status, message=i.message, actor=i.actor) for i in timeline]
        return cls.build(t, scope, timeline=items)
