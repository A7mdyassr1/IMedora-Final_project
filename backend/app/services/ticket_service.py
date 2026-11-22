"""Maintenance tickets (B4 CP1: reporting and reading; CP2: workflow).

Approved rules implemented here (B4 plan, decisions Q3, Q9, Q11; B3.1 approval conditions):
- Reporting a problem (POST /tickets) is open to every role, on any device of the caller's
  REPORTING scope (AccessScope.reporting_scope): own hospital - including other departments, via
  QR, for department users - or the whole organization for admins. Out of scope = 404.
- A department user without a department cannot report (403 department_required).
- Archived devices (Decision 6: read-only) and devices of inactive hospitals ("nothing new is
  added") cannot receive new tickets: 400.
- Organization, hospital, reporter and status are set by the server, never by the client.
- Every new ticket writes its audit row in the same transaction (CP2 standard).
- Reads follow AccessScope.ticket_access. Soft-deleted tickets are visible to admins only;
  `include_deleted` asked for by anyone else is refused (403), never silently ignored.

Workflow (CP2; rules in app/core/ticket_workflow.py, decisions Q4-Q8):
- Every change LOCKS the ticket row first (SELECT ... FOR UPDATE), then checks, changes and
  audits, and commits once: concurrent changes to one ticket run one after the other.
- Order of checks: not visible -> 404; deleted -> 409; not a valid transition -> 409
  invalid_status_transition; not allowed for this user -> 403; preconditions -> 409.
- Ticket status never changes the device's status (Q8).
- Timestamps that the database CHECKs against created_at / assigned_at (resolved_at,
  unassigned_at) are set with the database clock (now()), never the application clock.
"""
import logging
import uuid
from typing import List, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import TicketPriority, TicketStatus
from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.roles import Role
from app.core.ticket_workflow import (
    ASSIGNABLE_ROLES, ASSIGNMENTS_FROZEN, NEEDS_AN_OWNER, SELF_ASSIGNABLE, TERMINAL, MaintenanceRecordRequiredError,
    TicketFacts, check_transition, may_assign, may_change_priority, may_set_status, may_unassign,
)
from app.models.hospital import Hospital
from app.models.ticket import MaintenanceTicket, TicketAssignment
from app.repositories.device_repository import DeviceRepository
from app.repositories.ticket_repository import TicketFilters, TicketRepository
from app.schemas.ticket import TicketCreate
from app.services.audit_service import AuditService, snapshot
from app.services.ticket_timeline import AssignmentEntry, AuditEntry, Person, TimelineItem, build_timeline
from app.utils.problem_category import compose

logger = logging.getLogger(__name__)


class TicketService:
    def __init__(self, db: Session):
        self.db = db
        self.tickets = TicketRepository(db)
        self.devices = DeviceRepository(db)
        self.audit = AuditService(db)

    # ---- report a problem -------------------------------------------------------------------
    def create(self, scope: AccessScope, data: TicketCreate) -> MaintenanceTicket:
        device = self.devices.get(scope.reporting_scope(), data.device_id)  # 403 department_required
        if device is None:
            raise NotFoundError("Device not found.")
        if device.is_archived:
            raise BadRequestError("Archived devices cannot receive new tickets.")
        if not device.hospital.is_active:  # Decision 6: nothing new is added to an inactive hospital
            raise BadRequestError("Hospital is inactive; tickets cannot be added to it.")
        ticket = self.tickets.add(MaintenanceTicket(
            organization_id=device.organization_id,
            hospital_id=device.hospital_id,
            device_id=device.id,
            reported_by=scope.user_id,
            problem_description=compose(data.category, data.description),
            priority=data.priority or TicketPriority.MEDIUM,
            status=TicketStatus.OPEN,
        ))
        self.audit.inserted(scope.user_id, ticket)
        self.db.commit()
        logger.info("Ticket created id=%s device=%s", ticket.id, device.id)
        return self.get(scope, ticket.id)

    # ---- reads ------------------------------------------------------------------------------
    def get(self, scope: AccessScope, ticket_id: uuid.UUID) -> MaintenanceTicket:
        """404 for unknown tickets and for tickets outside the caller's scope alike. Admins can
        open soft-deleted tickets by id (Decision 6: admin and audit views)."""
        ticket = self.tickets.get(scope, ticket_id, include_deleted=scope.is_admin)
        if ticket is None:
            raise NotFoundError("Ticket not found.")
        return ticket

    def list(self, scope: AccessScope, filters: TicketFilters, sort: str, descending: bool, page: int,
             page_size: int) -> Tuple[List[MaintenanceTicket], int]:
        if filters.include_deleted and not scope.is_admin:
            raise ForbiddenError("Only administrators can include deleted tickets.")
        return self.tickets.list(scope, filters, sort, descending, page, page_size)

    def mine(self, scope: AccessScope, page: int, page_size: int) -> Tuple[List[MaintenanceTicket], int]:
        """Tickets the caller reported, newest first. Works for every role, including a department
        user who no longer has a department (Q11)."""
        return self.tickets.list(scope, TicketFilters(reported_by=scope.user_id), "created_at", True, page, page_size)

    def for_device(self, scope: AccessScope, device_id: uuid.UUID, filters: TicketFilters, sort: str,
                   descending: bool, page: int, page_size: int) -> Tuple[List[MaintenanceTicket], int]:
        """A device's ticket history. The device must be in the caller's DEVICE scope (CP3 rules:
        a department user's own department; the limited QR view does not open it), then the ticket
        scope applies: department users see only their own tickets on it (Q3)."""
        scope.require_device_access()
        if self.devices.get(scope, device_id) is None:
            raise NotFoundError("Device not found.")
        filters.device_id = device_id
        return self.list(scope, filters, sort, descending, page, page_size)

    def timeline(self, scope: AccessScope, ticket: MaintenanceTicket) -> List[TimelineItem]:
        rows = self.tickets.audit_rows(ticket)
        assignment_rows = self.tickets.assignment_audit_rows(ticket)
        assigned_by, unassigned_by = {}, {}
        for r in assignment_rows:
            if r.action.value == "insert":
                assigned_by.setdefault(r.record_id, r.user_id)
            elif r.action.value == "update" and (r.new_values or {}).get("unassigned_at"):
                unassigned_by[r.record_id] = r.user_id
        assignments = [AssignmentEntry(a.user_id, a.assigned_at, a.unassigned_at, assigned_by.get(a.id), unassigned_by.get(a.id))
                       for a in ticket.assignments]
        people_ids = [ticket.reported_by, *(r.user_id for r in rows), *(a.user_id for a in ticket.assignments),
                      *assigned_by.values(), *unassigned_by.values()]
        users = self.tickets.users_by_id(ticket.organization_id, people_ids)
        return build_timeline(
            ticket_created_at=ticket.created_at,
            reporter_id=ticket.reported_by,
            audit=[AuditEntry(r.created_at, r.action.value, r.user_id, r.old_values, r.new_values) for r in rows],
            people={u.id: Person(u.id, u.full_name, u.role.name) for u in users.values()},
            viewer_id=scope.user_id,
            viewer_sees_names=scope.sees_staff_names,
            assignments=assignments,
        )

    # ---- workflow (CP2) ------------------------------------------------------------------------
    def _locked(self, scope: AccessScope, ticket_id: uuid.UUID) -> MaintenanceTicket:
        ticket = self.tickets.get_for_update(scope, ticket_id, include_deleted=scope.is_admin)
        if ticket is None:
            raise NotFoundError("Ticket not found.")
        if ticket.is_deleted:  # only admins can even see it
            raise ConflictError("Deleted tickets cannot be modified.")
        return ticket

    @staticmethod
    def _facts(ticket: MaintenanceTicket) -> TicketFacts:
        return TicketFacts(ticket.hospital_id, ticket.reported_by, ticket.status,
                           frozenset(a.user_id for a in ticket.active_assignments))

    def _set_status(self, actor_id: uuid.UUID, ticket: MaintenanceTicket, status: TicketStatus) -> None:
        before = snapshot(ticket)
        ticket.status = status
        if status is TicketStatus.RESOLVED:
            ticket.resolved_at = func.now()       # database clock: CHECK resolved_at >= created_at
        elif status is TicketStatus.IN_PROGRESS and ticket.resolved_at is not None:
            ticket.resolved_at = None             # reopened: the timeline keeps the earlier resolution
        self.db.flush()
        self.audit.updated(actor_id, ticket, before)

    def change_status(self, scope: AccessScope, ticket_id: uuid.UUID, target: TicketStatus) -> MaintenanceTicket:
        ticket = self._locked(scope, ticket_id)
        facts = self._facts(ticket)
        check_transition(ticket.status, target)
        if not may_set_status(scope, facts, target):
            raise ForbiddenError("You are not allowed to make this status change.")
        if target is TicketStatus.RESOLVED and not self.tickets.has_maintenance_record(ticket):  # Q7
            raise MaintenanceRecordRequiredError()
        if ticket.status is TicketStatus.RESOLVED and target is TicketStatus.IN_PROGRESS and not facts.active_assignee_ids:
            raise ConflictError("Assign someone before reopening the ticket.")
        old = ticket.status
        self._set_status(scope.user_id, ticket, target)
        self.db.commit()
        logger.info("Ticket status id=%s %s -> %s", ticket.id, old.value, target.value)
        return self.get(scope, ticket.id)

    def assign(self, scope: AccessScope, ticket_id: uuid.UUID, user_id: uuid.UUID) -> MaintenanceTicket:
        ticket = self._locked(scope, ticket_id)
        facts = self._facts(ticket)
        if ticket.status in ASSIGNMENTS_FROZEN:
            raise ConflictError("Resolved, closed or cancelled tickets cannot be assigned.")
        if not may_assign(scope, facts, user_id):
            raise ForbiddenError("Technicians can only assign themselves." if scope.role is Role.TECHNICIAN
                                 else "You are not allowed to assign this ticket.")
        if scope.role is Role.TECHNICIAN and ticket.status not in SELF_ASSIGNABLE:  # Q5
            raise ForbiddenError("Technicians can only take tickets that are open or assigned.")
        if not self.db.get(Hospital, ticket.hospital_id).is_active:  # Decision 6: nothing new is added
            raise BadRequestError("Hospital is inactive; tickets cannot be assigned in it.")
        assignee = self.tickets.users_by_id(ticket.organization_id, [user_id]).get(user_id)
        if (assignee is None or not assignee.is_active or assignee.deleted_at is not None
                or assignee.hospital_id != ticket.hospital_id or assignee.role.name not in {r.value for r in ASSIGNABLE_ROLES}):
            raise BadRequestError("Only active technicians and biomedical engineers of the ticket's hospital can be assigned.")
        if user_id in facts.active_assignee_ids:
            raise ConflictError("This user is already assigned to this ticket.")
        assignment = self.tickets.add_assignment(TicketAssignment(ticket_id=ticket.id, user_id=user_id))
        self.audit.inserted(scope.user_id, assignment, organization_id=ticket.organization_id)
        if ticket.status is TicketStatus.OPEN:
            self._set_status(scope.user_id, ticket, TicketStatus.ASSIGNED)
        self.db.commit()
        logger.info("Ticket assigned id=%s user=%s", ticket.id, user_id)
        return self.get(scope, ticket.id)

    def unassign(self, scope: AccessScope, ticket_id: uuid.UUID, user_id: uuid.UUID) -> MaintenanceTicket:
        ticket = self._locked(scope, ticket_id)
        facts = self._facts(ticket)
        if ticket.status in ASSIGNMENTS_FROZEN:
            raise ConflictError("Assignments of resolved, closed or cancelled tickets cannot be changed.")
        if not may_unassign(scope, facts, user_id):
            raise ForbiddenError("Technicians can only unassign themselves." if scope.role is Role.TECHNICIAN
                                 else "You are not allowed to change this ticket's assignments.")
        assignment = next((a for a in ticket.active_assignments if a.user_id == user_id), None)
        if assignment is None:
            raise NotFoundError("This user is not assigned to this ticket.")
        remaining = facts.active_assignee_ids - {user_id}
        if not remaining and ticket.status in NEEDS_AN_OWNER:
            raise ConflictError("A ticket that is in progress must keep at least one assignee.")
        before = snapshot(assignment)
        assignment.unassigned_at = func.now()     # database clock: CHECK unassigned_at >= assigned_at
        self.db.flush()
        self.audit.updated(scope.user_id, assignment, before, organization_id=ticket.organization_id)
        if not remaining and ticket.status is TicketStatus.ASSIGNED:
            self._set_status(scope.user_id, ticket, TicketStatus.OPEN)
        self.db.commit()
        logger.info("Ticket unassigned id=%s user=%s", ticket.id, user_id)
        return self.get(scope, ticket.id)

    def change_priority(self, scope: AccessScope, ticket_id: uuid.UUID, priority: TicketPriority) -> MaintenanceTicket:
        ticket = self._locked(scope, ticket_id)
        if not may_change_priority(scope, self._facts(ticket)):
            raise ForbiddenError("Only biomedical engineers and administrators can change a ticket's priority.")
        if ticket.status in TERMINAL:
            raise ConflictError("Closed or cancelled tickets cannot be changed.")
        if ticket.priority is not priority:
            before = snapshot(ticket)
            ticket.priority = priority
            self.db.flush()
            self.audit.updated(scope.user_id, ticket, before)
            self.db.commit()
        else:
            self.db.rollback()  # nothing to change: release the row lock
        return self.get(scope, ticket.id)

    def soft_delete(self, scope: AccessScope, ticket_id: uuid.UUID) -> None:
        """Admin only (Decision 6: mistaken or duplicate tickets). Idempotent. The ticket keeps its
        status and history and stays readable for admins (include_deleted / by id)."""
        if not scope.is_admin:
            raise ForbiddenError("Only administrators can delete tickets.")
        ticket = self.tickets.get_for_update(scope, ticket_id, include_deleted=True)
        if ticket is None:
            raise NotFoundError("Ticket not found.")
        if ticket.is_deleted:
            self.db.rollback()
            return
        before = snapshot(ticket)
        ticket.deleted_at = func.now()
        self.db.flush()
        self.audit.updated(scope.user_id, ticket, before)
        self.db.commit()
        logger.info("Ticket deleted id=%s", ticket.id)
