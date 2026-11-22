"""Maintenance tickets (B4 CP1: reporting and reading).

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
"""
import logging
import uuid
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import TicketPriority, TicketStatus
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.models.ticket import MaintenanceTicket
from app.repositories.device_repository import DeviceRepository
from app.repositories.ticket_repository import TicketFilters, TicketRepository
from app.schemas.ticket import TicketCreate
from app.services.audit_service import AuditService
from app.services.ticket_timeline import AuditEntry, Person, TimelineItem, build_timeline
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
        users = self.tickets.users_by_id(ticket.organization_id, [ticket.reported_by, *(r.user_id for r in rows)])
        return build_timeline(
            ticket_created_at=ticket.created_at,
            reporter_id=ticket.reported_by,
            audit=[AuditEntry(r.created_at, r.action.value, r.user_id, r.old_values, r.new_values) for r in rows],
            people={u.id: Person(u.id, u.full_name, u.role.name) for u in users.values()},
            viewer_id=scope.user_id,
            viewer_sees_names=scope.sees_staff_names,
        )
