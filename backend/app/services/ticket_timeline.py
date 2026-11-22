"""Ticket timeline (B4) - DERIVED, never stored.

There is no ticket-updates table (schema frozen). The history shown by GET /tickets/{id} is built
from the audit rows the backend writes for every ticket change (audit_logs, table_name =
'maintenance_tickets', record_id = ticket id) - and, from later B4 checkpoints, from
ticket_assignments (CP2) and linked maintenance records (CP3).

This module is PURE: no database access. The service loads the rows and the people involved and
passes them in, so every rule here is unit-tested without PostgreSQL.

Rules (B4 CP1):
- "created": the ticket's INSERT audit row. Tickets created outside the backend (seeds, legacy
  data) have no such row: the event is then taken from tickets.created_at, with the reporter as
  actor and status "open" (the only status a ticket is created with).
- "status_changed" / "priority_changed" / "deleted": UPDATE audit rows whose new values change
  that column. Other columns are not timeline events.
- Every item carries the ticket status AFTER that event (the mobile app colours items by it).
- Items are ordered by time; events of one audit row keep the order above.
- Actors: staff see names. Department users see other people as a role description
  ("Technician", ...), never a name (approved decision Q9); their own actions show their name.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Literal, Optional

from app.core.enums import TicketPriority, TicketStatus

STATUS_LABELS = {
    TicketStatus.OPEN: "Open",
    TicketStatus.ASSIGNED: "Assigned",
    TicketStatus.IN_PROGRESS: "In Progress",
    TicketStatus.WAITING_FOR_PARTS: "Waiting for Parts",
    TicketStatus.RESOLVED: "Resolved",
    TicketStatus.CLOSED: "Closed",
    TicketStatus.CANCELLED: "Cancelled",
}
PRIORITY_LABELS = {
    TicketPriority.LOW: "Low",
    TicketPriority.MEDIUM: "Medium",
    TicketPriority.HIGH: "High",
    TicketPriority.CRITICAL: "Critical",
}
ROLE_LABELS = {
    "admin": "Administrator",
    "biomedical_engineer": "Biomedical engineer",
    "technician": "Technician",
    "department_user": "Department staff",
}

TimelineKind = Literal["created", "status_changed", "priority_changed", "deleted"]


@dataclass(frozen=True)
class AuditEntry:
    at: datetime
    action: str                      # "insert" | "update" | "delete"
    user_id: Optional[uuid.UUID]
    old_values: Optional[Dict[str, Any]]
    new_values: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class Person:
    id: uuid.UUID
    full_name: str
    role: str


@dataclass(frozen=True)
class TimelineItem:
    at: datetime
    kind: TimelineKind
    status: TicketStatus
    message: str
    actor: Optional[str]


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, "Staff")


def person_display(person: Optional[Person], viewer_id: uuid.UUID, viewer_sees_names: bool) -> Optional[str]:
    """How a person is shown to the viewer: their name for staff viewers and for the viewer
    themself; otherwise their role description only."""
    if person is None:
        return None
    if viewer_sees_names or person.id == viewer_id:
        return person.full_name
    return role_label(person.role)


def _status(value: Any, fallback: TicketStatus) -> TicketStatus:
    try:
        return TicketStatus(value)
    except ValueError:
        return fallback


def _status_label(value: Any) -> str:
    try:
        return STATUS_LABELS[TicketStatus(value)]
    except ValueError:
        return str(value)


def _priority_label(value: Any) -> str:
    try:
        return PRIORITY_LABELS[TicketPriority(value)]
    except ValueError:
        return str(value)


def build_timeline(
    *,
    ticket_created_at: datetime,
    reporter_id: uuid.UUID,
    audit: Iterable[AuditEntry],
    people: Dict[uuid.UUID, Person],
    viewer_id: uuid.UUID,
    viewer_sees_names: bool,
) -> List[TimelineItem]:
    rows = sorted(audit, key=lambda e: e.at)  # stable: rows with equal times keep the given order

    def actor(user_id: Optional[uuid.UUID]) -> Optional[str]:
        return person_display(people.get(user_id) if user_id else None, viewer_id, viewer_sees_names)

    items: List[TimelineItem] = []
    insert = next((e for e in rows if e.action == "insert"), None)
    if insert is not None:
        status = _status((insert.new_values or {}).get("status"), TicketStatus.OPEN)
        items.append(TimelineItem(insert.at, "created", status, "Ticket created.", actor(insert.user_id)))
    else:  # created outside the backend (seed / legacy data): no INSERT audit row
        status = TicketStatus.OPEN
        items.append(TimelineItem(ticket_created_at, "created", status, "Ticket created.", actor(reporter_id)))

    for e in rows:
        if e.action != "update":
            continue
        new, old = e.new_values or {}, e.old_values or {}
        who = actor(e.user_id)
        if "status" in new:
            status = _status(new["status"], status)
            items.append(TimelineItem(e.at, "status_changed", status, f"Status changed to {_status_label(new['status'])}.", who))
        if "priority" in new:
            if old.get("priority") is not None:
                message = f"Priority changed from {_priority_label(old['priority'])} to {_priority_label(new['priority'])}."
            else:
                message = f"Priority changed to {_priority_label(new['priority'])}."
            items.append(TimelineItem(e.at, "priority_changed", status, message, who))
        if new.get("deleted_at"):
            items.append(TimelineItem(e.at, "deleted", status, "Ticket deleted.", who))
    return items
