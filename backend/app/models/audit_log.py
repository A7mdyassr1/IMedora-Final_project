"""Mirror of the existing `audit_logs` table (database/migrations 0005_phase5_supporting).

The table is owned by the database layer; this model never creates or alters it.
Append-only by convention: the backend only ever INSERTs rows (no updated_at, no trigger).
`record_id` is polymorphic (the id of a row in `table_name`), so it has no foreign key.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AuditAction
from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    # NULL when the change was made outside an authenticated request (e.g. scripts/create_user.py).
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    table_name: Mapped[str] = mapped_column(String(100))
    record_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True))
    action: Mapped[AuditAction] = mapped_column(
        PG_ENUM(AuditAction, name="audit_action", create_type=False, values_callable=lambda e: [m.value for m in e])
    )
    old_values: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    new_values: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    # Set by PostgreSQL (now() = transaction start), so every row of one change shares the same time.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
