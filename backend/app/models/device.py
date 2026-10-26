import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, FetchedValue, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Criticality, DeviceStatus, RiskLevel
from app.models.base import Base
from app.models.catalog import DeviceModel
from app.models.department import Department
from app.models.hospital import Hospital
from app.models.location import Location


def _pg_enum(enum_cls, name: str):
    # create_type=False: the types already exist (migrations own them).
    return PG_ENUM(enum_cls, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="RESTRICT"))
    department_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"))
    location_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"))
    device_model_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("device_models.id", ondelete="RESTRICT"))
    device_code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    serial_number: Mapped[Optional[str]] = mapped_column(String(255))
    qr_identifier: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[DeviceStatus] = mapped_column(_pg_enum(DeviceStatus, "device_status"), server_default=text("'active'"))
    criticality: Mapped[Criticality] = mapped_column(_pg_enum(Criticality, "device_criticality"), server_default=text("'medium'"))
    installation_date: Mapped[Optional[date]] = mapped_column(Date)
    warranty_expiry: Mapped[Optional[date]] = mapped_column(Date)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())
    # Maintained by database triggers / later phases: READ-ONLY here.
    next_maintenance_due_date: Mapped[Optional[date]] = mapped_column(Date)
    current_risk_level: Mapped[Optional[RiskLevel]] = mapped_column(_pg_enum(RiskLevel, "risk_level"))

    model: Mapped[DeviceModel] = relationship(lazy="joined")
    hospital: Mapped[Hospital] = relationship(lazy="joined")
    department: Mapped[Department] = relationship(lazy="joined")
    location: Mapped[Optional[Location]] = relationship(lazy="joined")

    @property
    def is_archived(self) -> bool:
        return self.deleted_at is not None
