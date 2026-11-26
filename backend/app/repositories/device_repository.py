import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import Criticality, DeviceStatus, RiskLevel
from app.models.catalog import DeviceModel
from app.models.department import Department
from app.models.device import Device
from app.repositories.pagination import paginate


@dataclass
class DeviceFilters:
    hospital_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    category_id: Optional[uuid.UUID] = None
    manufacturer_id: Optional[uuid.UUID] = None
    model_id: Optional[uuid.UUID] = None
    status: Optional[DeviceStatus] = None
    criticality: Optional[Criticality] = None
    risk_level: Optional[RiskLevel] = None
    q: Optional[str] = None
    include_archived: bool = False


SORT_COLUMNS = {
    "name": Device.name,
    "device_code": Device.device_code,
    "status": Device.status,
    "criticality": Device.criticality,
    "created_at": Device.created_at,
    "next_maintenance_due_date": Device.next_maintenance_due_date,
}


def scope_conditions(scope: AccessScope) -> list:
    """WHERE conditions that keep a device query inside the caller's scope (B3.1 CP3).
    Always the organization; plus the hospital and/or department the scope is limited to.
    The caller must have checked scope.require_device_access() first."""
    conditions = [Device.organization_id == scope.organization_id]
    if scope.device_hospital_id is not None:
        conditions.append(Device.hospital_id == scope.device_hospital_id)
    if scope.device_department_id is not None:
        conditions.append(Device.department_id == scope.device_department_id)
    return conditions


class DeviceRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, device: Device) -> Device:
        self.db.add(device)
        self.db.flush()
        return device

    def get(self, scope: AccessScope, device_id: uuid.UUID) -> Optional[Device]:
        """The device if it exists INSIDE the caller's scope, else None (the API answers 404 for both)."""
        return self.db.scalars(
            select(Device).where(Device.id == device_id, *scope_conditions(scope)).execution_options(populate_existing=True)
        ).first()

    @staticmethod
    def qr_candidates(qr: str) -> List[str]:
        """The values a scanned QR is matched against, in order of preference:
        exactly as scanned, then upper-case (the form the API stores), then lower-case.
        The column itself is compared (`qr_identifier IN (...)`), never a function of it such as
        upper(qr_identifier), so PostgreSQL CAN answer the lookup from the unique index on
        devices.qr_identifier. Whether it does is the planner's choice (on a tiny table a
        sequential scan can be cheaper); see the B3.1 Checkpoint 1 report for measured plans."""
        raw = qr.strip()
        return list(dict.fromkeys(v for v in (raw, raw.upper(), raw.lower()) if v))

    @staticmethod
    def qr_lookup_statement(org_id: uuid.UUID, candidates: List[str], hospital_id: Optional[uuid.UUID] = None):
        # Still `qr_identifier IN (...)` on the column itself (CP1): the unique index stays usable;
        # the hospital condition (CP3 scope) only filters the one row it finds.
        stmt = select(Device).where(Device.organization_id == org_id, Device.qr_identifier.in_(candidates))
        if hospital_id is not None:
            stmt = stmt.where(Device.hospital_id == hospital_id)
        return stmt

    def get_by_qr(self, scope: AccessScope, qr: str) -> Optional[Device]:
        """QR lookup inside `scope` (use AccessScope.qr_lookup_scope(): department users may
        resolve codes across their hospital). Never wider than one hospital for non-admins."""
        candidates = self.qr_candidates(qr)
        if not candidates:
            return None
        stmt = self.qr_lookup_statement(scope.organization_id, candidates, scope.device_hospital_id)
        if scope.device_department_id is not None:
            stmt = stmt.where(Device.department_id == scope.device_department_id)
        rows = self.db.scalars(stmt).unique().all()
        if not rows:
            return None
        # Several rows can only match if legacy data differs by case alone; prefer the closest form.
        rank = {value: i for i, value in enumerate(candidates)}
        return min(rows, key=lambda d: rank.get(d.qr_identifier, len(rank)))

    def list(self, scope: AccessScope, f: DeviceFilters, sort: str, descending: bool, page: int, page_size: int) -> Tuple[List[Device], int]:
        # Scope first; the user's filters can only narrow it further (a hospital_id or
        # department_id outside the scope simply yields an empty page).
        stmt = select(Device).where(*scope_conditions(scope))
        if not f.include_archived:
            stmt = stmt.where(Device.deleted_at.is_(None))
        if f.hospital_id:
            stmt = stmt.where(Device.hospital_id == f.hospital_id)
        if f.department_id:
            stmt = stmt.where(Device.department_id == f.department_id)
        if f.model_id:
            stmt = stmt.where(Device.device_model_id == f.model_id)
        if f.category_id:
            stmt = stmt.where(Device.device_model_id.in_(select(DeviceModel.id).where(DeviceModel.device_category_id == f.category_id)))
        if f.manufacturer_id:
            stmt = stmt.where(Device.device_model_id.in_(select(DeviceModel.id).where(DeviceModel.manufacturer_id == f.manufacturer_id)))
        if f.status:
            stmt = stmt.where(Device.status == f.status)
        if f.criticality:
            stmt = stmt.where(Device.criticality == f.criticality)
        if f.risk_level:
            stmt = stmt.where(Device.current_risk_level == f.risk_level)
        if f.q:
            like = f"%{f.q.strip()}%"
            stmt = stmt.where(
                or_(Device.name.ilike(like), Device.device_code.ilike(like), Device.serial_number.ilike(like),
                    Device.qr_identifier.ilike(like),
                    # B8: the mobile device picker searches by name, code AND department (Master Instructions 5)
                    Device.department_id.in_(select(Department.id).where(Department.name.ilike(like))))
            )
        column = SORT_COLUMNS[sort]
        stmt = stmt.order_by(column.desc() if descending else column.asc(), Device.id)
        return paginate(self.db, stmt, page, page_size)
