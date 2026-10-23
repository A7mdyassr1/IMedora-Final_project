import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.hospital import Hospital


class HospitalRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_in_organization(self, organization_id: uuid.UUID, hospital_id: uuid.UUID) -> Optional[Hospital]:
        return self.db.scalars(
            select(Hospital).where(Hospital.id == hospital_id, Hospital.organization_id == organization_id)
        ).first()

    def get_department_in_hospital(self, hospital_id: uuid.UUID, department_id: uuid.UUID) -> Optional[Department]:
        return self.db.scalars(
            select(Department).where(Department.id == department_id, Department.hospital_id == hospital_id)
        ).first()
