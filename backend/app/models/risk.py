"""Risk assessments (B6 CP1) - exact mirror of migration 0004 (risk_assessments).

Database rules this mirror relies on (enforced by PostgreSQL, NOT re-implemented here):
- trg_risk_assessments_refresh_device (AFTER INSERT/UPDATE/DELETE) recomputes
  devices.current_risk_level from the latest assessed_at. It is the ONLY writer of that column;
  the backend never computes or writes it (Master Instructions section 4).
- Every foreign key is ON DELETE RESTRICT: assessments are history.
- risk_factors / risk_mitigation_actions were deliberately not built (migration 0004 notes).
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, FetchedValue, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RiskLevel
from app.models.base import Base
from app.models.device import Device
from app.models.user import User


def _pg_enum(enum_cls, name: str):
    # create_type=False: the types already exist (migrations own them).
    return PG_ENUM(enum_cls, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        Index("ix_risk_assessments_organization_id", "organization_id"),
        Index("ix_risk_assessments_hospital_id", "hospital_id"),
        Index("ix_risk_assessments_device_id", "device_id"),
        Index("ix_risk_assessments_assessed_by", "assessed_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="RESTRICT"))
    device_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"))
    assessed_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    risk_level: Mapped[RiskLevel] = mapped_column(_pg_enum(RiskLevel, "risk_level"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())

    # selectin (never joined) so paged queries stay one row per assessment
    device: Mapped[Device] = relationship(lazy="selectin")
    assessor: Mapped[User] = relationship(lazy="selectin")
