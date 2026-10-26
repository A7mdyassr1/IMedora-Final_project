import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import Criticality, DeviceStatus, RiskLevel
from app.models.catalog import DeviceModel
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


class DeviceRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, device: Device) -> Device:
        self.db.add(device)
        self.db.flush()
        return device

    def get(self, org_id: uuid.UUID, device_id: uuid.UUID) -> Optional[Device]:
        return self.db.scalars(
            select(Device).where(Device.id == device_id, Device.organization_id == org_id).execution_options(populate_existing=True)
        ).first()

    def get_by_qr(self, org_id: uuid.UUID, qr: str) -> Optional[Device]:
        qr = qr.strip()
        base = select(Device).where(Device.organization_id == org_id)
        exact = self.db.scalars(base.where(Device.qr_identifier == qr)).first()  # uses the unique index
        if exact is not None:
            return exact
        # Scanners/keyboards differ in case; fall back to a case-insensitive match within the organization.
        return self.db.scalars(base.where(func.upper(Device.qr_identifier) == qr.upper())).first()

    def list(self, org_id: uuid.UUID, f: DeviceFilters, sort: str, descending: bool, page: int, page_size: int) -> Tuple[List[Device], int]:
        stmt = select(Device).where(Device.organization_id == org_id)
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
                or_(Device.name.ilike(like), Device.device_code.ilike(like), Device.serial_number.ilike(like), Device.qr_identifier.ilike(like))
            )
        column = SORT_COLUMNS[sort]
        stmt = stmt.order_by(column.desc() if descending else column.asc(), Device.id)
        return paginate(self.db, stmt, page, page_size)
