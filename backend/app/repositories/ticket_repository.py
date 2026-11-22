"""Maintenance-ticket queries (B4). Every read is limited to the caller's ticket scope
(AccessScope.ticket_access); out-of-scope tickets are simply not found (the API answers 404).

    ORGANIZATION  admin                      organization
    HOSPITAL      engineer / technician      organization AND (own hospital OR reported by them)
    OWN_REPORTS   department_user            organization AND reported by them

Soft-deleted tickets (deleted_at, Decision 6) are excluded unless the caller asks for them;
only admins may (checked by TicketService).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.access import AccessScope, TicketAccess
from app.core.enums import TicketPriority, TicketStatus
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.ticket import MaintenanceTicket, TicketAssignment
from app.models.user import User
from app.repositories.pagination import paginate

TICKET_TABLE = MaintenanceTicket.__tablename__

SORT_COLUMNS = {
    "created_at": MaintenanceTicket.created_at,
    "updated_at": MaintenanceTicket.updated_at,
    "priority": MaintenanceTicket.priority,  # enum order: low < medium < high < critical
    "status": MaintenanceTicket.status,      # enum order: open ... cancelled (workflow order)
}


@dataclass
class TicketFilters:
    status: List[TicketStatus] = field(default_factory=list)
    priority: List[TicketPriority] = field(default_factory=list)
    device_id: Optional[uuid.UUID] = None
    hospital_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None   # the DEVICE's department (tickets have none)
    reported_by: Optional[uuid.UUID] = None
    assigned_to: Optional[uuid.UUID] = None     # has an ACTIVE assignment for this user
    created_from: Optional[datetime] = None     # inclusive
    created_to: Optional[datetime] = None       # exclusive
    q: Optional[str] = None
    include_deleted: bool = False


def scope_conditions(scope: AccessScope) -> list:
    conditions = [MaintenanceTicket.organization_id == scope.organization_id]
    access = scope.ticket_access
    if access is TicketAccess.HOSPITAL:
        conditions.append(or_(MaintenanceTicket.hospital_id == scope.hospital_id,
                              MaintenanceTicket.reported_by == scope.user_id))
    elif access is TicketAccess.OWN_REPORTS:
        conditions.append(MaintenanceTicket.reported_by == scope.user_id)
    return conditions


class TicketRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, ticket: MaintenanceTicket) -> MaintenanceTicket:
        self.db.add(ticket)
        self.db.flush()
        return ticket

    def get(self, scope: AccessScope, ticket_id: uuid.UUID, include_deleted: bool = False) -> Optional[MaintenanceTicket]:
        stmt = select(MaintenanceTicket).where(MaintenanceTicket.id == ticket_id, *scope_conditions(scope))
        if not include_deleted:
            stmt = stmt.where(MaintenanceTicket.deleted_at.is_(None))
        return self.db.scalars(stmt.execution_options(populate_existing=True)).unique().first()

    def list(self, scope: AccessScope, f: TicketFilters, sort: str, descending: bool, page: int,
             page_size: int) -> Tuple[List[MaintenanceTicket], int]:
        # Scope first; filters can only narrow it (a hospital outside the scope yields an empty page).
        stmt = select(MaintenanceTicket).where(*scope_conditions(scope))
        if not f.include_deleted:
            stmt = stmt.where(MaintenanceTicket.deleted_at.is_(None))
        if f.status:
            stmt = stmt.where(MaintenanceTicket.status.in_(f.status))
        if f.priority:
            stmt = stmt.where(MaintenanceTicket.priority.in_(f.priority))
        if f.device_id:
            stmt = stmt.where(MaintenanceTicket.device_id == f.device_id)
        if f.hospital_id:
            stmt = stmt.where(MaintenanceTicket.hospital_id == f.hospital_id)
        if f.department_id:
            stmt = stmt.where(MaintenanceTicket.device_id.in_(
                select(Device.id).where(Device.department_id == f.department_id)))
        if f.reported_by:
            stmt = stmt.where(MaintenanceTicket.reported_by == f.reported_by)
        if f.assigned_to:
            stmt = stmt.where(MaintenanceTicket.id.in_(
                select(TicketAssignment.ticket_id).where(TicketAssignment.user_id == f.assigned_to,
                                                         TicketAssignment.unassigned_at.is_(None))))
        if f.created_from:
            stmt = stmt.where(MaintenanceTicket.created_at >= f.created_from)
        if f.created_to:
            stmt = stmt.where(MaintenanceTicket.created_at < f.created_to)
        if f.q and f.q.strip():
            term = f.q.strip()  # matched literally: %, _ and \\ in the search text are escaped
            matching_devices = select(Device.id).where(
                Device.organization_id == scope.organization_id,
                or_(Device.name.icontains(term, autoescape=True), Device.device_code.icontains(term, autoescape=True)),
            )
            stmt = stmt.where(or_(MaintenanceTicket.problem_description.icontains(term, autoescape=True),
                                  MaintenanceTicket.device_id.in_(matching_devices)))
        column = SORT_COLUMNS[sort]
        stmt = stmt.order_by(column.desc() if descending else column.asc(), MaintenanceTicket.created_at.desc(),
                             MaintenanceTicket.id)
        return paginate(self.db, stmt, page, page_size)

    # ---- timeline sources -------------------------------------------------------------------
    def audit_rows(self, ticket: MaintenanceTicket) -> List[AuditLog]:
        """The ticket's audit rows, oldest first (index ix_audit_logs_table_record)."""
        return list(self.db.scalars(
            select(AuditLog).where(AuditLog.table_name == TICKET_TABLE, AuditLog.record_id == ticket.id,
                                   AuditLog.organization_id == ticket.organization_id)
            .order_by(AuditLog.created_at, AuditLog.id)
        ))

    def users_by_id(self, organization_id: uuid.UUID, ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, User]:
        wanted = {i for i in ids if i is not None}
        if not wanted:
            return {}
        rows = self.db.scalars(select(User).where(User.id.in_(wanted), User.organization_id == organization_id)).unique()
        return {u.id: u for u in rows}
