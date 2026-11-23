"""Spare parts (B5) - exact mirrors of migration 0003_phase3_parts (+ the 0006 index).

Database rules these mirrors declare (enforced by PostgreSQL, not re-implemented here):
- `parts` is a GLOBAL catalog (no organization / hospital), like the device catalog;
  `part_number` is unique across the whole database (parts_part_number_key).
- `part_inventory` is one stock row per (hospital, part) (uq_inventory_hospital_part) and can
  never go below zero (ck_inventory_quantity_non_negative).
- `maintenance_parts` is the usage of a part in a maintenance record (one row per record and part,
  uq_record_part; quantity > 0). The trigger `trg_maintenance_parts_adjust_inventory` keeps
  `part_inventory.quantity_on_hand` in step with it: INSERT subtracts, UPDATE of quantity applies
  the difference, DELETE gives the quantity back. Using a part at a hospital that has no stock row
  for it raises P0001; using more than is on hand violates the CHECK above (23514).
  The backend NEVER writes quantity_on_hand for usage itself: it locks the stock row, checks, and
  lets the trigger do the arithmetic (B5 CP2).
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint, DateTime, FetchedValue, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.hospital import Hospital


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255))
    part_number: Mapped[str] = mapped_column(String(100), unique=True)  # parts_part_number_key
    unit: Mapped[str] = mapped_column(String(20), server_default=text("'piece'"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())


class PartInventory(Base):
    __tablename__ = "part_inventory"
    __table_args__ = (
        UniqueConstraint("hospital_id", "part_id", name="uq_inventory_hospital_part"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_quantity_non_negative"),
        CheckConstraint("reorder_threshold IS NULL OR reorder_threshold >= 0", name="ck_inventory_reorder_non_negative"),
        Index("ix_inventory_organization_id", "organization_id"),
        Index("ix_part_inventory_part_id", "part_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"))
    hospital_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="RESTRICT"))
    part_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("parts.id", ondelete="RESTRICT"))
    quantity_on_hand: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    reorder_threshold: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())

    # selectin, as everywhere in B4/B5: one extra SELECT per page, never one per row
    part: Mapped[Part] = relationship(lazy="selectin")
    hospital: Mapped[Hospital] = relationship(lazy="selectin")

    @property
    def is_low_stock(self) -> bool:
        """At or below the reorder threshold (no threshold = never low)."""
        return self.reorder_threshold is not None and self.quantity_on_hand <= self.reorder_threshold


class MaintenancePart(Base):
    __tablename__ = "maintenance_parts"
    __table_args__ = (
        UniqueConstraint("maintenance_record_id", "part_id", name="uq_record_part"),
        CheckConstraint("quantity > 0", name="ck_maintenance_parts_quantity_positive"),
        Index("ix_maintenance_parts_part_id", "part_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    maintenance_record_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("maintenance_records.id", ondelete="CASCADE"))
    part_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("parts.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue())

    part: Mapped[Part] = relationship(lazy="selectin")
