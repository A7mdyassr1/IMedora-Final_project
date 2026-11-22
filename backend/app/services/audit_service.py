"""Audit logging for every data change made through the backend (B3.1 CP2).

How it stays consistent with the change it describes
-----------------------------------------------------
`AuditService` only ADDS an AuditLog row to the caller's SQLAlchemy session. It never
flushes or commits. The service that made the change then commits once: PostgreSQL writes
the business row and its audit row in the same transaction. If that commit fails, or the
request errors and `get_db` rolls back, neither row is kept.

What is never stored
--------------------
`password_hash` and any column whose name mentions a password, token or secret are dropped
from every snapshot. A password change is recorded only as {"password_changed": true}.
`created_at` / `updated_at` are left out too: PostgreSQL sets them, and the audit row has
its own `created_at`.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.enums import AuditAction
from app.models.audit_log import AuditLog
from app.repositories.audit_repository import AuditRepository

_SECRET_MARKERS = ("password", "token", "secret")
_ALWAYS_EXCLUDED = {"created_at", "updated_at"}

PASSWORD_CHANGED = {"password_changed": True}


def _is_secret(column: str) -> bool:
    name = column.lower()
    return any(marker in name for marker in _SECRET_MARKERS)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def snapshot(obj: Any, exclude: Iterable[str] = ()) -> Dict[str, Any]:
    """Column values of an ORM object, JSON-safe, with secrets and timestamps removed."""
    skip = _ALWAYS_EXCLUDED | set(exclude)
    values: Dict[str, Any] = {}
    for attr in inspect(obj).mapper.column_attrs:
        key = attr.key
        if key in skip or _is_secret(key):
            continue
        values[key] = _json_safe(getattr(obj, key))
    return values


def table_of(obj: Any) -> str:
    return obj.__table__.name


class AuditService:
    def __init__(self, db: Session):
        self.repo = AuditRepository(db)

    # -- the single writer ------------------------------------------------------------
    def record(
        self,
        *,
        actor_id: Optional[uuid.UUID],
        organization_id: uuid.UUID,
        table_name: str,
        record_id: uuid.UUID,
        action: AuditAction,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        for values in (old_values, new_values):  # last line of defence: never persist a secret
            if values:
                for key in list(values):
                    if _is_secret(key) and key not in PASSWORD_CHANGED:
                        del values[key]
        return self.repo.add(AuditLog(
            organization_id=organization_id,
            user_id=actor_id,
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_values=old_values or None,
            new_values=new_values or None,
        ))

    # -- convenience wrappers ---------------------------------------------------------
    @staticmethod
    def _org(obj: Any, organization_id: Optional[uuid.UUID]) -> uuid.UUID:
        org = organization_id or getattr(obj, "organization_id", None)
        if org is None:
            raise ValueError(f"Audit row for {table_of(obj)} needs an organization_id")
        return org

    def inserted(self, actor_id: Optional[uuid.UUID], obj: Any, organization_id: Optional[uuid.UUID] = None) -> AuditLog:
        """Call after the new row was flushed (its id must exist)."""
        return self.record(
            actor_id=actor_id, organization_id=self._org(obj, organization_id),
            table_name=table_of(obj), record_id=obj.id, action=AuditAction.INSERT,
            new_values=snapshot(obj),
        )

    def updated(
        self,
        actor_id: Optional[uuid.UUID],
        obj: Any,
        before: Dict[str, Any],
        organization_id: Optional[uuid.UUID] = None,
        extra_new: Optional[Dict[str, Any]] = None,
    ) -> Optional[AuditLog]:
        """`before` = snapshot(obj) taken before the change. Only changed fields are stored;
        nothing is written when nothing changed (unless `extra_new`, e.g. a password marker)."""
        after = snapshot(obj)
        changed = [k for k in after if before.get(k) != after[k]]
        old = {k: before.get(k) for k in changed}
        new = {k: after[k] for k in changed}
        if extra_new:
            new.update(extra_new)
        if not new:
            return None
        return self.record(
            actor_id=actor_id, organization_id=self._org(obj, organization_id),
            table_name=table_of(obj), record_id=obj.id, action=AuditAction.UPDATE,
            old_values=old, new_values=new,
        )

    def deleted(self, actor_id: Optional[uuid.UUID], obj: Any, organization_id: Optional[uuid.UUID] = None) -> AuditLog:
        """Call BEFORE session.delete(obj), while its values can still be read."""
        return self.record(
            actor_id=actor_id, organization_id=self._org(obj, organization_id),
            table_name=table_of(obj), record_id=obj.id, action=AuditAction.DELETE,
            old_values=snapshot(obj),
        )
