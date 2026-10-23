import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, FetchedValue, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.department import Department
from app.models.hospital import Hospital
from app.models.base import Base
from app.models.role import Role


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="RESTRICT"))
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"))
    role_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"))
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())

    # Many-to-one, always needed to build a response -> joined load, no N+1.
    role: Mapped[Role] = relationship(lazy="joined")
    hospital: Mapped[Hospital] = relationship(lazy="joined")
    department: Mapped[Optional[Department]] = relationship(lazy="joined")

    @property
    def role_name(self) -> str:
        return self.role.name

    @property
    def hospital_name(self) -> str:
        return self.hospital.name

    @property
    def department_name(self) -> Optional[str]:
        return self.department.name if self.department else None
