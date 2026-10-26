"""Organization structure queries: hospitals, departments, locations (always organization-scoped)."""
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.hospital import Hospital
from app.models.location import Location
from app.models.organization import Organization
from app.repositories.pagination import paginate


def _hospital_ids(org_id: uuid.UUID):
    return select(Hospital.id).where(Hospital.organization_id == org_id)


class HospitalRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, obj):
        self.db.add(obj)
        self.db.flush()
        return obj

    # -- organization -----------------------------------------------------------
    def get_organization(self, org_id: uuid.UUID) -> Optional[Organization]:
        return self.db.get(Organization, org_id)

    # -- hospitals ---------------------------------------------------------------
    def get_in_organization(self, organization_id: uuid.UUID, hospital_id: uuid.UUID) -> Optional[Hospital]:
        return self.db.scalars(
            select(Hospital).where(Hospital.id == hospital_id, Hospital.organization_id == organization_id)
        ).first()

    def list_hospitals(self, org_id, page, page_size, q: Optional[str] = None, is_active: Optional[bool] = None) -> Tuple[List[Hospital], int]:
        stmt = select(Hospital).where(Hospital.organization_id == org_id)
        if q:
            stmt = stmt.where(Hospital.name.ilike(f"%{q.strip()}%") | Hospital.code.ilike(f"%{q.strip()}%"))
        if is_active is not None:
            stmt = stmt.where(Hospital.is_active == is_active)
        return paginate(self.db, stmt.order_by(Hospital.name, Hospital.id), page, page_size)

    # -- departments --------------------------------------------------------------
    def get_department_in_hospital(self, hospital_id: uuid.UUID, department_id: uuid.UUID) -> Optional[Department]:
        return self.db.scalars(
            select(Department).where(Department.id == department_id, Department.hospital_id == hospital_id)
        ).first()

    def get_department(self, org_id: uuid.UUID, department_id: uuid.UUID) -> Optional[Department]:
        return self.db.scalars(
            select(Department).where(Department.id == department_id, Department.hospital_id.in_(_hospital_ids(org_id)))
        ).first()

    def list_departments(self, org_id, page, page_size, hospital_id=None, q=None) -> Tuple[List[Department], int]:
        stmt = select(Department).where(Department.hospital_id.in_(_hospital_ids(org_id)))
        if hospital_id:
            stmt = stmt.where(Department.hospital_id == hospital_id)
        if q:
            stmt = stmt.where(Department.name.ilike(f"%{q.strip()}%"))
        return paginate(self.db, stmt.order_by(Department.name, Department.id), page, page_size)

    # -- locations -------------------------------------------------------------------
    def get_location_in_hospital(self, hospital_id: uuid.UUID, location_id: uuid.UUID) -> Optional[Location]:
        return self.db.scalars(
            select(Location).where(Location.id == location_id, Location.hospital_id == hospital_id)
        ).first()

    def get_location(self, org_id: uuid.UUID, location_id: uuid.UUID) -> Optional[Location]:
        return self.db.scalars(
            select(Location).where(Location.id == location_id, Location.hospital_id.in_(_hospital_ids(org_id)))
        ).first()

    def list_locations(self, org_id, page, page_size, hospital_id=None) -> Tuple[List[Location], int]:
        stmt = select(Location).where(Location.hospital_id.in_(_hospital_ids(org_id)))
        if hospital_id:
            stmt = stmt.where(Location.hospital_id == hospital_id)
        return paginate(
            self.db, stmt.order_by(Location.building, Location.floor, Location.room, Location.id), page, page_size
        )
