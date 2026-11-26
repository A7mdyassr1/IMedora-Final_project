"""A device's history feed (B6 CP4): one time-ordered list built from existing tables only.

Each source keeps the scope rules of its own endpoint, as WHERE clauses:
- tickets: exactly the rules of GET /devices/{id}/tickets (app/repositories/ticket_repository.py
  `scope_conditions`: organization / own hospital or own reports / only own reports; soft-deleted
  tickets excluded);
- maintenance records, risk assessments, QA records: the caller's device scope (organization for
  admins, own hospital otherwise). Which of these sources a role may see at all is decided by the
  service before this runs.

The union is ordered and paged in the database: time (newest first), then entry type name
(alphabetical), then id - a stable order for entries with equal times.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import FrozenSet, List, Optional, Tuple

from sqlalchemy import Select, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.models.maintenance import MaintenanceRecord
from app.models.qa import QARecord
from app.models.risk import RiskAssessment
from app.models.ticket import MaintenanceTicket
from app.repositories.ticket_repository import scope_conditions as ticket_scope

TICKET_REPORTED = "ticket_reported"
TICKET_RESOLVED = "ticket_resolved"
MAINTENANCE_RECORD = "maintenance_record"
RISK_ASSESSMENT = "risk_assessment"
QA_RECORD = "qa_record"
ENTRY_TYPES = (TICKET_REPORTED, TICKET_RESOLVED, MAINTENANCE_RECORD, RISK_ASSESSMENT, QA_RECORD)


@dataclass(frozen=True)
class HistoryRow:
    type: str
    at: datetime
    id: uuid.UUID


def _device_scoped(model, scope: AccessScope) -> list:
    conditions = [model.organization_id == scope.organization_id]
    if scope.device_hospital_id is not None:
        conditions.append(model.hospital_id == scope.device_hospital_id)
    return conditions


class HistoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def _sources(self, scope: AccessScope, device_id: uuid.UUID, types: FrozenSet[str]) -> List[Select]:
        def source(kind: str, at_column, model, conditions: list) -> Select:
            return select(literal(kind).label("type"), at_column.label("at"), model.id.label("id")).where(
                model.device_id == device_id, *conditions)

        tickets = [*ticket_scope(scope), MaintenanceTicket.deleted_at.is_(None)]
        sources = []
        if TICKET_REPORTED in types:
            sources.append(source(TICKET_REPORTED, MaintenanceTicket.created_at, MaintenanceTicket, tickets))
        if TICKET_RESOLVED in types:
            sources.append(source(TICKET_RESOLVED, MaintenanceTicket.resolved_at, MaintenanceTicket,
                                  [*tickets, MaintenanceTicket.resolved_at.is_not(None)]))
        if MAINTENANCE_RECORD in types:
            sources.append(source(MAINTENANCE_RECORD, MaintenanceRecord.performed_at, MaintenanceRecord,
                                  _device_scoped(MaintenanceRecord, scope)))
        if RISK_ASSESSMENT in types:
            sources.append(source(RISK_ASSESSMENT, RiskAssessment.assessed_at, RiskAssessment,
                                  _device_scoped(RiskAssessment, scope)))
        if QA_RECORD in types:
            sources.append(source(QA_RECORD, QARecord.performed_at, QARecord, _device_scoped(QARecord, scope)))
        return sources

    def page(self, scope: AccessScope, device_id: uuid.UUID, types: FrozenSet[str], at_from: Optional[datetime],
             at_to: Optional[datetime], page: int, page_size: int) -> Tuple[List[HistoryRow], int]:
        sources = self._sources(scope, device_id, types)
        if not sources:
            return [], 0
        feed = union_all(*sources).subquery("feed")
        stmt = select(feed.c.type, feed.c.at, feed.c.id)
        if at_from is not None:
            stmt = stmt.where(feed.c.at >= at_from)
        if at_to is not None:
            stmt = stmt.where(feed.c.at <= at_to)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.execute(stmt.order_by(feed.c.at.desc(), feed.c.type.asc(), feed.c.id.asc())
                               .limit(page_size).offset((page - 1) * page_size)).all()
        return [HistoryRow(r.type, r.at, r.id) for r in rows], total

    # ---- details of one page, loaded by id (relationships are selectin) -------------------------------
    def tickets(self, ids) -> dict:
        return {t.id: t for t in self.db.scalars(select(MaintenanceTicket).where(MaintenanceTicket.id.in_(ids)))} if ids else {}

    def records(self, ids) -> dict:
        return {r.id: r for r in self.db.scalars(select(MaintenanceRecord).where(MaintenanceRecord.id.in_(ids)))} if ids else {}

    def assessments(self, ids) -> dict:
        return {a.id: a for a in self.db.scalars(select(RiskAssessment).where(RiskAssessment.id.in_(ids)))} if ids else {}

    def qa_records(self, ids) -> dict:
        return {q.id: q for q in self.db.scalars(select(QARecord).where(QARecord.id.in_(ids)))} if ids else {}
