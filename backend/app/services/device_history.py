"""A device's history (B6 CP4): GET /devices/{id}/history - tickets, maintenance records, risk
assessments and QA records of one device in one time-ordered feed, built from existing tables.

Visibility (approved B6 plan, Revision 5, section 9.3):

    role              ticket entries                       maintenance   risk / QA   staff shown as
    ----------------  -----------------------------------  ------------  ----------  --------------
    admin             as GET /devices/{id}/tickets         yes           yes         names
    engineer          as GET /devices/{id}/tickets         yes           yes         names
    technician        as GET /devices/{id}/tickets         yes           yes (D3)    names
    department user   only tickets they reported (Q3)      no            no (D3)     roles (Q9)

- The device must be visible through the normal device endpoint (department users: their own
  department; the QR exception does not open histories); otherwise 404. Archived devices are
  included (Decision 6: their history stays readable).
- Order of checks: a department user who explicitly asks for an entry type they may not see gets
  403 before any lookup; without `types`, those entries are simply absent. Then the device (404).
- Consistency (B6-L3): the whole read runs in one REPEATABLE READ snapshot, so `total`, the page
  and each entry's details agree even while other requests write.
- Ticket entries: `ticket_reported` (created_at) and `ticket_resolved` (resolved_at, when set).
  Closed and cancelled have no timestamp column: they show as the ticket's current status.
"""
import uuid
from datetime import datetime
from typing import FrozenSet, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.database import start_snapshot_read
from app.core.exceptions import AppError, ForbiddenError, NotFoundError
from app.core.roles import Role
from app.repositories.device_repository import DeviceRepository
from app.repositories.history_repository import (
    ENTRY_TYPES, MAINTENANCE_RECORD, QA_RECORD, RISK_ASSESSMENT, TICKET_REPORTED, TICKET_RESOLVED, HistoryRepository,
)
from app.schemas.history import (
    DeviceHistoryEntry, HistoryMaintenanceRecord, HistoryQARecord, HistoryRiskAssessment, HistoryTicket,
)
from app.schemas.maintenance import Performer
from app.schemas.ticket import _person
from app.services.risk_service import aware
from app.utils.ticket_number import ticket_number

TICKET_TYPES = frozenset({TICKET_REPORTED, TICKET_RESOLVED})


class HistoryTypesError(AppError):
    status_code = 422
    code = "validation_error"
    default_message = "Request validation failed."


def visible_types(scope: AccessScope) -> FrozenSet[str]:
    """Department users: their own tickets only (no maintenance records, no risk / QA - D3)."""
    if scope.role is Role.DEPARTMENT_USER:
        return TICKET_TYPES
    return frozenset(ENTRY_TYPES)


def parse_types(raw: Optional[str]) -> Optional[FrozenSet[str]]:
    if raw is None:
        return None
    requested = frozenset(t.strip() for t in raw.split(",") if t.strip())
    unknown = sorted(requested - set(ENTRY_TYPES))
    if not requested or unknown:
        raise HistoryTypesError(details=[{"field": "query.types",
                                          "message": f"Unknown entry type(s) {unknown}; use any of {list(ENTRY_TYPES)}."
                                          if unknown else "Give at least one entry type."}])
    return requested


def _performer(user) -> Performer:
    return Performer(id=user.id, name=user.full_name, role=user.role.name)


class DeviceHistoryService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = HistoryRepository(db)
        self.devices = DeviceRepository(db)

    def history(self, scope: AccessScope, device_id: uuid.UUID, types: Optional[FrozenSet[str]],
                at_from: Optional[datetime], at_to: Optional[datetime], page: int,
                page_size: int) -> Tuple[List[DeviceHistoryEntry], int]:
        allowed = visible_types(scope)
        if types is not None and not types <= allowed:              # role first, no lookup
            raise ForbiddenError("Department users can see only the tickets they reported in a device's history.")
        scope.require_device_access()                                # 403 department_required
        start_snapshot_read(self.db)  # B6-L3: device, total, page and details from ONE snapshot
        if self.devices.get(scope, device_id) is None:               # archived devices included
            raise NotFoundError("Device not found.")
        rows, total = self.repo.page(scope, device_id, types or allowed, aware(at_from), aware(at_to), page, page_size)
        return self._entries(scope, rows), total

    def _entries(self, scope: AccessScope, rows: Sequence) -> List[DeviceHistoryEntry]:
        ids = lambda kinds: {r.id for r in rows if r.type in kinds}  # noqa: E731
        tickets = self.repo.tickets(ids(TICKET_TYPES))
        records = self.repo.records(ids({MAINTENANCE_RECORD}))
        assessments = self.repo.assessments(ids({RISK_ASSESSMENT}))
        qa = self.repo.qa_records(ids({QA_RECORD}))
        entries = []
        for r in rows:
            entry = DeviceHistoryEntry(type=r.type, at=r.at)
            if r.type in TICKET_TYPES:
                t = tickets[r.id]
                entry.ticket = HistoryTicket(
                    id=t.id, number=ticket_number(t.id), priority=t.priority, status=t.status,
                    reported_by=_person(t.reporter, scope) if r.type == TICKET_REPORTED else None)
            elif r.type == MAINTENANCE_RECORD:
                m = records[r.id]
                entry.maintenance_record = HistoryMaintenanceRecord(
                    id=m.id, maintenance_type=m.maintenance_type.name, performed_by=_performer(m.performer),
                    ticket_id=m.ticket_id, ticket_number=ticket_number(m.ticket_id) if m.ticket_id else None,
                    parts_count=len(m.parts_used))
            elif r.type == RISK_ASSESSMENT:
                a = assessments[r.id]
                entry.risk_assessment = HistoryRiskAssessment(id=a.id, risk_level=a.risk_level,
                                                              assessed_by=_performer(a.assessor))
            else:
                q = qa[r.id]
                entry.qa_record = HistoryQARecord(id=q.id, record_type=q.record_type, status=q.status,
                                                  next_due_date=q.next_due_date, performed_by=_performer(q.performer))
            entries.append(entry)
        return entries
