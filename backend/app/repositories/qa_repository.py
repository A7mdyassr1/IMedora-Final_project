"""QA records (B6 CP2).

Scope: records carry organization_id and hospital_id (copied from the device when they are created),
so the caller's DEVICE scope (own hospital for engineers and technicians, organization for admins)
becomes plain WHERE clauses. Department users have no access (the service refuses them before any
lookup). Out of scope = 404.
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import Date, cast, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import QARecordType, QAStatus
from app.models.device import Device
from app.models.qa import QARecord
from app.repositories.pagination import paginate

SORT = {"performed_at": QARecord.performed_at, "next_due_date": QARecord.next_due_date,
        "created_at": QARecord.created_at}


@dataclass
class QAFilters:
    device_id: Optional[uuid.UUID] = None
    hospital_id: Optional[uuid.UUID] = None
    record_type: Optional[QARecordType] = None
    status: Optional[QAStatus] = None
    performed_by: Optional[uuid.UUID] = None
    performed_from: Optional[datetime] = None   # inclusive
    performed_to: Optional[datetime] = None     # exclusive
    due_after: Optional[date] = None            # next_due_date on or after (inclusive)
    due_before: Optional[date] = None           # next_due_date on or before (inclusive)


@dataclass
class DueFilters:
    within_days: int = 30
    include_overdue: bool = True
    hospital_id: Optional[uuid.UUID] = None
    record_type: Optional[QARecordType] = None
    device_id: Optional[uuid.UUID] = None
    include_archived: bool = False


def _scoped(scope: AccessScope) -> list:
    conditions = [QARecord.organization_id == scope.organization_id]
    if scope.device_hospital_id is not None:
        conditions.append(QARecord.hospital_id == scope.device_hospital_id)
    return conditions


class QARepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, record: QARecord) -> QARecord:
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, scope: AccessScope, record_id: uuid.UUID, for_update: bool = False) -> Optional[QARecord]:
        stmt = select(QARecord).where(QARecord.id == record_id, *_scoped(scope))
        if for_update:
            stmt = stmt.with_for_update(of=QARecord)
        return self.db.scalars(stmt.execution_options(populate_existing=True)).first()

    def list(self, scope: AccessScope, f: QAFilters, sort: str, descending: bool, page: int,
             page_size: int) -> Tuple[List[QARecord], int]:
        stmt = select(QARecord).where(*_scoped(scope))
        for column, value in ((QARecord.device_id, f.device_id), (QARecord.hospital_id, f.hospital_id),
                              (QARecord.record_type, f.record_type), (QARecord.status, f.status),
                              (QARecord.performed_by, f.performed_by)):
            if value is not None:
                stmt = stmt.where(column == value)
        if f.performed_from:
            stmt = stmt.where(QARecord.performed_at >= f.performed_from)
        if f.performed_to:
            stmt = stmt.where(QARecord.performed_at < f.performed_to)
        if f.due_after:
            stmt = stmt.where(QARecord.next_due_date >= f.due_after)
        if f.due_before:
            stmt = stmt.where(QARecord.next_due_date <= f.due_before)
        column = SORT[sort]
        ordered = column.desc() if descending else column.asc()
        tie = (QARecord.created_at.desc(), QARecord.id.desc()) if descending else \
            (QARecord.created_at.asc(), QARecord.id.asc())
        stmt = stmt.order_by(ordered.nulls_last(), *tie)
        return paginate(self.db, stmt, page, page_size)

    def now(self) -> datetime:
        """The database's now() (transaction start): what the performed_at default would give."""
        return self.db.scalar(select(func.now()))

    def date_of(self, value: datetime) -> date:
        """The calendar date of a timestamp as the DATABASE sees it (its TimeZone setting): exactly
        the conversion ck_qa_next_due_after_performed applies (`performed_at::date`)."""
        return self.db.scalar(select(cast(value, Date)))

    def lock_device(self, device_id: uuid.UUID) -> None:
        """Row lock on the device (only the devices row), held until commit: the same lock every risk
        and maintenance writer of the device takes first, so lock order stays device -> record."""
        self.db.execute(select(Device.id).where(Device.id == device_id).with_for_update())

    # ---- CP3: summary and due list -------------------------------------------------------------------
    @staticmethod
    def _live_devices(include_archived: bool) -> list:
        """Decision 6: archived devices leave summaries and due lists unless an admin asks for them."""
        if include_archived:
            return []
        return [QARecord.device_id.in_(select(Device.id).where(Device.deleted_at.is_(None)))]

    def counts(self, scope: AccessScope, hospital_id: Optional[uuid.UUID],
               include_archived: bool) -> Tuple[Dict[QAStatus, int], Dict[QARecordType, int]]:
        conditions = [*_scoped(scope), *self._live_devices(include_archived)]
        if hospital_id is not None:
            conditions.append(QARecord.hospital_id == hospital_id)
        by_status = dict(self.db.execute(select(QARecord.status, func.count()).where(*conditions)
                                         .group_by(QARecord.status)).all())
        by_type = dict(self.db.execute(select(QARecord.record_type, func.count()).where(*conditions)
                                       .group_by(QARecord.record_type)).all())
        return by_status, by_type

    def due(self, scope: AccessScope, f: DueFilters, page: int, page_size: int) -> Tuple[List[QARecord], int]:
        """D15: per (device, record type) only the LATEST record counts (performed_at, then created_at,
        then id - deterministic); older ones are superseded and never due. Its next_due_date decides:
        overdue = before today, upcoming = today .. today + within_days (the database's current_date).
        Records without a next due date are never due."""
        latest = select(QARecord.id).where(*_scoped(scope), *self._live_devices(f.include_archived))
        for column, value in ((QARecord.hospital_id, f.hospital_id), (QARecord.record_type, f.record_type),
                              (QARecord.device_id, f.device_id)):
            if value is not None:
                latest = latest.where(column == value)
        latest = latest.ext(distinct_on(QARecord.device_id, QARecord.record_type)).order_by(
            QARecord.device_id, QARecord.record_type, QARecord.performed_at.desc(), QARecord.created_at.desc(),
            QARecord.id.desc())
        today = func.current_date()
        stmt = select(QARecord).where(QARecord.id.in_(latest), QARecord.next_due_date.is_not(None),
                                      QARecord.next_due_date <= today + f.within_days)
        if not f.include_overdue:
            stmt = stmt.where(QARecord.next_due_date >= today)
        stmt = stmt.order_by(QARecord.next_due_date.asc(), QARecord.id.asc())
        return paginate(self.db, stmt, page, page_size)

    def today(self) -> date:
        return self.db.scalar(select(func.current_date()))
