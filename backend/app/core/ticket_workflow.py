"""Ticket status workflow and who may change a ticket (B4 CP2) - PURE rules, no database.

Approved in the B4 plan (decisions Q4-Q7) and its CP2 detail rules. The service loads the
ticket, locks its row, and asks these functions; every rule is unit-tested here without SQL.

Transitions set by hand (open / assigned are never set by hand - they follow the assignments):

    open               -> cancelled                                (-> assigned: first assignment)
    assigned           -> in_progress, cancelled                   (-> open: last assignee removed)
    in_progress        -> waiting_for_parts, resolved, cancelled
    waiting_for_parts  -> in_progress, resolved, cancelled
    resolved           -> closed, in_progress (reopen)
    closed, cancelled  -> terminal

Who may set a status:
- in_progress / waiting_for_parts / resolved: an ACTIVE assignee (Q5), an engineer of the
  ticket's hospital, or an admin. Reopening (resolved -> in_progress) is not included: see below.
- closed, and reopening resolved -> in_progress: engineers of the ticket's hospital and admins (Q6).
- cancelled: engineers of the ticket's hospital and admins; and the REPORTER, but only while the
  ticket is `open` with no active assignment (Q4).
- Department users have no other status power.
Extra conditions (service): resolving needs a linked maintenance record (Q7); reopening needs an
active assignee; deleted tickets cannot change at all.

Assignments:
- Assignees: active technicians / biomedical engineers of the ticket's hospital.
- Engineers (own hospital) and admins assign and unassign anyone eligible; technicians only
  themselves, and only take tickets that are `open` or `assigned` (Q5).
- Resolved, closed and cancelled tickets keep their assignments as history: no changes.
"""
from dataclasses import dataclass
from typing import FrozenSet, Mapping
import uuid

from app.core.access import AccessScope
from app.core.enums import TicketStatus
from app.core.exceptions import ConflictError
from app.core.roles import Role

S = TicketStatus

MANUAL_TRANSITIONS: Mapping[TicketStatus, FrozenSet[TicketStatus]] = {
    S.OPEN: frozenset({S.CANCELLED}),
    S.ASSIGNED: frozenset({S.IN_PROGRESS, S.CANCELLED}),
    S.IN_PROGRESS: frozenset({S.WAITING_FOR_PARTS, S.RESOLVED, S.CANCELLED}),
    S.WAITING_FOR_PARTS: frozenset({S.IN_PROGRESS, S.RESOLVED, S.CANCELLED}),
    S.RESOLVED: frozenset({S.CLOSED, S.IN_PROGRESS}),
    S.CLOSED: frozenset(),
    S.CANCELLED: frozenset(),
}
TERMINAL: FrozenSet[TicketStatus] = frozenset({S.CLOSED, S.CANCELLED})
ASSIGNMENTS_FROZEN: FrozenSet[TicketStatus] = frozenset({S.RESOLVED, S.CLOSED, S.CANCELLED})
SELF_ASSIGNABLE: FrozenSet[TicketStatus] = frozenset({S.OPEN, S.ASSIGNED})
NEEDS_AN_OWNER: FrozenSet[TicketStatus] = frozenset({S.IN_PROGRESS, S.WAITING_FOR_PARTS})
ASSIGNABLE_ROLES: FrozenSet[Role] = frozenset({Role.TECHNICIAN, Role.BIOMEDICAL_ENGINEER})


class InvalidStatusTransitionError(ConflictError):
    code = "invalid_status_transition"
    default_message = "This status change is not allowed."


class MaintenanceRecordRequiredError(ConflictError):
    code = "maintenance_record_required"
    default_message = "Add a maintenance record for this ticket before resolving it."


@dataclass(frozen=True)
class TicketFacts:
    """What the rules need to know about a ticket."""
    hospital_id: uuid.UUID
    reported_by: uuid.UUID
    status: TicketStatus
    active_assignee_ids: FrozenSet[uuid.UUID]


def check_transition(current: TicketStatus, target: TicketStatus) -> None:
    allowed = MANUAL_TRANSITIONS[current]
    if target not in allowed:
        raise InvalidStatusTransitionError(
            f"A ticket cannot go from {current.value} to {target.value}.",
            details=[{"from": current.value, "to": target.value, "allowed": sorted(s.value for s in allowed)}],
        )


def manages(scope: AccessScope, t: TicketFacts) -> bool:
    """Full workflow power over this ticket: admins (organization), engineers (own hospital)."""
    if scope.is_admin:
        return True
    return scope.role is Role.BIOMEDICAL_ENGINEER and t.hospital_id == scope.hospital_id


def is_active_assignee(scope: AccessScope, t: TicketFacts) -> bool:
    return (scope.role in ASSIGNABLE_ROLES and scope.user_id in t.active_assignee_ids
            and t.hospital_id == scope.hospital_id)


def may_set_status(scope: AccessScope, t: TicketFacts, target: TicketStatus) -> bool:
    if target is S.CANCELLED:
        if manages(scope, t):
            return True
        return t.reported_by == scope.user_id and t.status is S.OPEN and not t.active_assignee_ids  # Q4
    if target is S.CLOSED or (t.status is S.RESOLVED and target is S.IN_PROGRESS):  # close / reopen: Q6
        return manages(scope, t)
    if target in (S.IN_PROGRESS, S.WAITING_FOR_PARTS, S.RESOLVED):  # Q5
        return manages(scope, t) or is_active_assignee(scope, t)
    return False


def may_assign(scope: AccessScope, t: TicketFacts, assignee_id: uuid.UUID) -> bool:
    if manages(scope, t):
        return True
    return scope.role is Role.TECHNICIAN and assignee_id == scope.user_id and t.hospital_id == scope.hospital_id


def may_unassign(scope: AccessScope, t: TicketFacts, assignee_id: uuid.UUID) -> bool:
    return may_assign(scope, t, assignee_id)


def may_change_priority(scope: AccessScope, t: TicketFacts) -> bool:
    return manages(scope, t)
