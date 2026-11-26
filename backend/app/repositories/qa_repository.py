"""QA records (B6 CP2).

Scope: records carry organization_id and hospital_id (copied from the device when they are created),
so the caller's DEVICE scope (own hospital for engineers and technicians, organization for admins)
becomes plain WHERE clauses. Department users have no access (the service refuses them before any
lookup). Out of scope = 404.
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple

from sqlalchemy import Date, cast, func, select
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
