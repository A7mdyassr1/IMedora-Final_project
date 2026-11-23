"""Ticket timeline (B4) - DERIVED, never stored.

There is no ticket-updates table (schema frozen). The history shown by GET /tickets/{id} is built
from the audit rows the backend writes for every ticket change (audit_logs, table_name =
'maintenance_tickets', record_id = ticket id), from ticket_assignments (B4 CP2: who was assigned
when, and - through the assignments' own audit rows - by whom), and from the maintenance
records linked to the ticket (CP3: the work performed, by whom, when).

This module is PURE: no database access. The service loads the rows and the people involved and
passes them in, so every rule here is unit-tested without PostgreSQL.

Rules:
- "created": the ticket's INSERT audit row. Tickets created outside the backend (seeds, legacy
  data) have no such row: the event is then taken from tickets.created_at, with the reporter as
  actor and status "open" (the only status a ticket is created with).
- "status_changed" / "priority_changed" / "deleted": UPDATE audit rows whose new values change
  that column. Other columns are not timeline events.
- "assigned" / "unassigned" (CP2): from ticket_assignments.assigned_at / unassigned_at. The actor
  is taken from the assignment's audit row when there is one (seeded assignments have none).
- "work_performed" (CP3): each linked maintenance record, at its performed_at, with its
  description; the performer is the actor. Department users see the description on their own
  tickets (decision Q9) and the performer as a role.
- The automatic status change that an (un)assignment causes in the same transaction
  (open -> assigned, assigned -> open) is FOLDED into that assignment event: one entry
  "Assigned to Technician." with status "assigned", not two entries.
- Every item carries the ticket status AFTER that event (the mobile app colours items by it).
- Items are ordered by time; at the same instant: created, then (un)assignments, then work,
  then ticket changes; events of one audit row keep the order above.
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

TimelineKind = Literal["created", "assigned", "unassigned", "work_performed", "status_changed", "priority_changed", "deleted"]


@dataclass(frozen=True)
class AuditEntry:
    at: datetime
    action: str                      # "insert" | "update" | "delete"
    user_id: Optional[uuid.UUID]
    old_values: Optional[Dict[str, Any]]
    new_values: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class AssignmentEntry:
    user_id: uuid.UUID
    assigned_at: datetime
    unassigned_at: Optional[datetime] = None
    assigned_by: Optional[uuid.UUID] = None     # from the assignment's INSERT audit row
    unassigned_by: Optional[uuid.UUID] = None   # from its UPDATE (unassigned_at) audit row


@dataclass(frozen=True)
class WorkEntry:
    at: datetime                     # maintenance_records.performed_at
    user_id: uuid.UUID               # performed_by
    description: str


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


_FOLDED = {"assigned": TicketStatus.ASSIGNED, "unassigned": TicketStatus.OPEN}


def build_timeline(
    *,
    ticket_created_at: datetime,
    reporter_id: uuid.UUID,
    audit: Iterable[AuditEntry],
    people: Dict[uuid.UUID, Person],
    viewer_id: uuid.UUID,
    viewer_sees_names: bool,
    assignments: Iterable[AssignmentEntry] = (),
    work: Iterable[WorkEntry] = (),
) -> List[TimelineItem]:
    def actor(user_id: Optional[uuid.UUID]) -> Optional[str]:
        return person_display(people.get(user_id) if user_id else None, viewer_id, viewer_sees_names)

    def named(user_id: uuid.UUID) -> str:
        return actor(user_id) or "a staff member"

    rows = sorted(audit, key=lambda e: e.at)  # stable: rows with equal times keep the given order
    insert = next((e for e in rows if e.action == "insert"), None)
    if insert is not None:
        created_status = _status((insert.new_values or {}).get("status"), TicketStatus.OPEN)
        created = (insert.at, "created", insert.user_id)
    else:  # created outside the backend (seed / legacy data): no INSERT audit row
        created_status = TicketStatus.OPEN
        created = (ticket_created_at, "created", reporter_id)

    # (at, order at the same instant, kind, data)
    events: list = [(created[0], 0, "created", created)]
    for a in assignments:
        events.append((a.assigned_at, 1, "assigned", a))
        if a.unassigned_at is not None:
            events.append((a.unassigned_at, 1, "unassigned", a))
    for w in work:
        events.append((w.at, 2, "work", w))
    for e in rows:
        if e.action == "update":
            events.append((e.at, 3, "update", e))
    events.sort(key=lambda ev: (ev[0], ev[1]))  # stable

    items: List[TimelineItem] = []
    status = created_status
    for at, _, kind, data in events:
        if kind == "created":
            items.append(TimelineItem(at, "created", status, "Ticket created.", actor(data[2])))
        elif kind == "assigned":
            items.append(TimelineItem(at, "assigned", status, f"Assigned to {named(data.user_id)}.", actor(data.assigned_by)))
        elif kind == "unassigned":
            items.append(TimelineItem(at, "unassigned", status, f"{named(data.user_id)} unassigned.", actor(data.unassigned_by)))
        elif kind == "work":
            items.append(TimelineItem(at, "work_performed", status, f"Work performed: {data.description}", actor(data.user_id)))
        else:
            new, old, who = data.new_values or {}, data.old_values or {}, actor(data.user_id)
            if "status" in new:
                new_status = _status(new["status"], status)
                last = items[-1] if items else None
                if (last is not None and last.at == at and last.kind in _FOLDED
                        and _FOLDED[last.kind] is new_status):
                    # automatic open <-> assigned caused by that (un)assignment: one entry, not two
                    status = new_status
                    items[-1] = TimelineItem(last.at, last.kind, status, last.message, last.actor)
                else:
                    status = new_status
                    items.append(TimelineItem(at, "status_changed", status, f"Status changed to {_status_label(new['status'])}.", who))
            if "priority" in new:
                if old.get("priority") is not None:
                    message = f"Priority changed from {_priority_label(old['priority'])} to {_priority_label(new['priority'])}."
                else:
                    message = f"Priority changed to {_priority_label(new['priority'])}."
                items.append(TimelineItem(at, "priority_changed", status, message, who))
            if new.get("deleted_at"):
                items.append(TimelineItem(at, "deleted", status, "Ticket deleted.", who))
    return items
