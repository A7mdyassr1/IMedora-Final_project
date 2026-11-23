"""Spare parts catalog, hospital stock and part usage (B5 CP1/CP2).

Scope: `part_inventory` carries organization_id and hospital_id, so the caller's DEVICE scope
(AccessScope.device_hospital_id: own hospital for engineers / technicians, None = organization for
admins) becomes plain WHERE clauses, exactly like maintenance records and schedules. Usage rows
(`maintenance_parts`) have no hospital of their own: they are scoped through their maintenance
record. The parts catalog is global (no scope), like the device catalog.

Stock rows are locked with SELECT ... FOR UPDATE (only the part_inventory row: no joins) by every
writer, always in part_id order when several are locked at once, so concurrent writers queue
instead of deadlocking.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.models.audit_log import AuditLog
from app.models.maintenance import MaintenanceRecord
from app.models.part import MaintenancePart, Part, PartInventory
from app.repositories.pagination import paginate

INVENTORY_SORT = {"part_name": Part.name, "part_number": Part.part_number,
                  "quantity_on_hand": PartInventory.quantity_on_hand, "updated_at": PartInventory.updated_at}
USAGE_SORT = {"performed_at": MaintenanceRecord.performed_at, "created_at": MaintenancePart.created_at}


@dataclass
class InventoryFilters:
    hospital_id: Optional[uuid.UUID] = None
    part_id: Optional[uuid.UUID] = None
    low_stock: bool = False          # at or below the reorder threshold
    q: Optional[str] = None          # part name or part number contains


@dataclass
class UsageFilters:
    part_id: Optional[uuid.UUID] = None
    hospital_id: Optional[uuid.UUID] = None
    device_id: Optional[uuid.UUID] = None
    ticket_id: Optional[uuid.UUID] = None
    maintenance_record_id: Optional[uuid.UUID] = None
    performed_from: Optional[datetime] = None   # inclusive, record's work time
    performed_to: Optional[datetime] = None     # exclusive


def _like(q: str) -> str:
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _inventory_scope(scope: AccessScope) -> list:
    conditions = [PartInventory.organization_id == scope.organization_id]
    if scope.device_hospital_id is not None:
        conditions.append(PartInventory.hospital_id == scope.device_hospital_id)
    return conditions


def _record_scope(scope: AccessScope) -> list:
    conditions = [MaintenanceRecord.organization_id == scope.organization_id]
    if scope.device_hospital_id is not None:
        conditions.append(MaintenanceRecord.hospital_id == scope.device_hospital_id)
    return conditions


class PartRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, obj):
        self.db.add(obj)
        self.db.flush()
        return obj

    # ---- catalog (global) ---------------------------------------------------------------------------
    def get_part(self, part_id: uuid.UUID) -> Optional[Part]:
        return self.db.scalars(select(Part).where(Part.id == part_id).execution_options(populate_existing=True)).first()

    def parts_by_id(self, part_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, Part]:
        ids = set(part_ids)
        if not ids:
            return {}
        return {p.id: p for p in self.db.scalars(select(Part).where(Part.id.in_(ids)))}

    def part_by_number(self, part_number: str) -> Optional[Part]:
        return self.db.scalar(select(Part).where(func.upper(Part.part_number) == part_number.upper()))

    def list_parts(self, q: Optional[str], page: int, page_size: int) -> Tuple[List[Part], int]:
        stmt = select(Part)
        if q and q.strip():
            pattern = _like(q)
            stmt = stmt.where(or_(Part.name.ilike(pattern, escape="\\"), Part.part_number.ilike(pattern, escape="\\")))
        return paginate(self.db, stmt.order_by(Part.name, Part.part_number, Part.id), page, page_size)

    # ---- stock --------------------------------------------------------------------------------------
    def get_inventory(self, scope: AccessScope, inventory_id: uuid.UUID, for_update: bool = False) -> Optional[PartInventory]:
        stmt = select(PartInventory).where(PartInventory.id == inventory_id, *_inventory_scope(scope))
        if for_update:
            stmt = stmt.with_for_update(of=PartInventory)
        return self.db.scalars(stmt.execution_options(populate_existing=True)).first()

    def stock_for(self, hospital_id: uuid.UUID, part_id: uuid.UUID) -> Optional[PartInventory]:
        return self.db.scalar(select(PartInventory).where(PartInventory.hospital_id == hospital_id,
                                                          PartInventory.part_id == part_id))

    def lock_stock(self, hospital_id: uuid.UUID, part_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, PartInventory]:
        """Lock the hospital's stock rows of these parts (in part_id order) and return them, freshly
        read, by part_id. Parts the hospital does not stock are simply absent from the result."""
        ids = sorted(set(part_ids))
        if not ids:
            return {}
        rows = self.db.scalars(
            select(PartInventory)
            .where(PartInventory.hospital_id == hospital_id, PartInventory.part_id.in_(ids))
            .order_by(PartInventory.part_id)
            .with_for_update(of=PartInventory)
            .execution_options(populate_existing=True)
        ).all()
        return {row.part_id: row for row in rows}

    def refresh(self, obj) -> None:
        """Re-read a row after a database trigger changed it in this transaction."""
        self.db.refresh(obj)

    def list_inventory(self, scope: AccessScope, f: InventoryFilters, sort: str, descending: bool, page: int,
                       page_size: int) -> Tuple[List[PartInventory], int]:
        stmt = select(PartInventory).join(Part, Part.id == PartInventory.part_id).where(*_inventory_scope(scope))
        if f.hospital_id is not None:
            stmt = stmt.where(PartInventory.hospital_id == f.hospital_id)
        if f.part_id is not None:
            stmt = stmt.where(PartInventory.part_id == f.part_id)
        if f.low_stock:
            stmt = stmt.where(PartInventory.reorder_threshold.is_not(None),
                              PartInventory.quantity_on_hand <= PartInventory.reorder_threshold)
        if f.q and f.q.strip():
            pattern = _like(f.q)
            stmt = stmt.where(or_(Part.name.ilike(pattern, escape="\\"), Part.part_number.ilike(pattern, escape="\\")))
        column = INVENTORY_SORT[sort]
        stmt = stmt.order_by(column.desc() if descending else column.asc(), PartInventory.id)
        return paginate(self.db, stmt, page, page_size)

    def movement_rows(self, inventory: PartInventory) -> List[AuditLog]:
        """Audit rows of one stock row, oldest first (index ix_audit_logs_table_record)."""
        return list(self.db.scalars(
            select(AuditLog)
            .where(AuditLog.table_name == PartInventory.__tablename__, AuditLog.record_id == inventory.id)
            .order_by(AuditLog.created_at, AuditLog.id)
        ))

    # ---- usage --------------------------------------------------------------------------------------
    def usage_for_record(self, record_id: uuid.UUID) -> List[MaintenancePart]:
        return list(self.db.scalars(
            select(MaintenancePart).where(MaintenancePart.maintenance_record_id == record_id)
            .order_by(MaintenancePart.created_at, MaintenancePart.id)
            .execution_options(populate_existing=True)
        ))

    def usage_line(self, record_id: uuid.UUID, part_id: uuid.UUID, for_update: bool = False) -> Optional[MaintenancePart]:
        stmt = select(MaintenancePart).where(MaintenancePart.maintenance_record_id == record_id,
                                             MaintenancePart.part_id == part_id)
        if for_update:
            stmt = stmt.with_for_update(of=MaintenancePart)
        return self.db.scalars(stmt.execution_options(populate_existing=True)).first()

    def delete(self, obj) -> None:
        self.db.delete(obj)
        self.db.flush()

    def list_usage(self, scope: AccessScope, f: UsageFilters, sort: str, descending: bool, page: int,
                   page_size: int) -> Tuple[List[Tuple[MaintenancePart, MaintenanceRecord]], int]:
        stmt = (select(MaintenancePart, MaintenanceRecord)
                .join(MaintenanceRecord, MaintenanceRecord.id == MaintenancePart.maintenance_record_id)
                .where(*_record_scope(scope)))
        for column, value in ((MaintenancePart.part_id, f.part_id), (MaintenanceRecord.hospital_id, f.hospital_id),
                              (MaintenanceRecord.device_id, f.device_id), (MaintenanceRecord.ticket_id, f.ticket_id),
                              (MaintenancePart.maintenance_record_id, f.maintenance_record_id)):
            if value is not None:
                stmt = stmt.where(column == value)
        if f.performed_from:
            stmt = stmt.where(MaintenanceRecord.performed_at >= f.performed_from)
        if f.performed_to:
            stmt = stmt.where(MaintenanceRecord.performed_at < f.performed_to)
        column = USAGE_SORT[sort]
        stmt = stmt.order_by(column.desc() if descending else column.asc(), MaintenancePart.id)
        total = self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        rows = self.db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
        return [(row[0], row[1]) for row in rows], total
