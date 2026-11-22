import uuid
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditRepository:
    """Append-only data access for audit_logs: rows are added, never updated or deleted.

    `add` neither flushes nor commits. The row is written by the caller's own commit, in the
    same transaction as the change it describes, so the two succeed or fail together.
    """

    def __init__(self, db: Session):
        self.db = db

    def add(self, entry: AuditLog) -> AuditLog:
        self.db.add(entry)
        return entry

    def list_for_record(self, table_name: str, record_id: uuid.UUID) -> List[AuditLog]:
        """Oldest first. Used by tests now and by the B4 ticket timeline later."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.table_name == table_name, AuditLog.record_id == record_id)
            .order_by(AuditLog.created_at, AuditLog.id)
        )
        return list(self.db.scalars(stmt))
