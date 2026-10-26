import logging
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.department import Department
from app.models.hospital import Hospital
from app.models.location import Location
from app.models.organization import Organization
from app.repositories.hospital_repository import HospitalRepository
from app.schemas.structure import (
    DepartmentCreate, DepartmentUpdate, HospitalCreate, HospitalUpdate, LocationCreate, LocationUpdate,
)

logger = logging.getLogger(__name__)


class StructureService:
    """Organization / hospitals / departments / locations. Everything is scoped to one organization."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = HospitalRepository(db)

    def _commit(self):
        # Constraint violations (duplicates, RESTRICT) surface here as IntegrityError and are
        # translated centrally in core/db_errors.py.
        self.db.commit()

    # -- organization ------------------------------------------------------------
    def get_organization(self, org_id: uuid.UUID) -> Organization:
        org = self.repo.get_organization(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        return org

    def rename_organization(self, org_id: uuid.UUID, name: str) -> Organization:
        org = self.get_organization(org_id)
        org.name = name
        self._commit()
        return org

    # -- hospitals ----------------------------------------------------------------
    def create_hospital(self, org_id: uuid.UUID, data: HospitalCreate) -> Hospital:
        hospital = self.repo.add(Hospital(organization_id=org_id, name=data.name, code=data.code, address=data.address, is_active=True))
        self._commit()
        logger.info("Hospital created id=%s", hospital.id)
        return hospital

    def get_hospital(self, org_id, hospital_id) -> Hospital:
        h = self.repo.get_in_organization(org_id, hospital_id)
        if h is None:
            raise NotFoundError("Hospital not found.")
        return h

    def update_hospital(self, org_id, hospital_id, data: HospitalUpdate) -> Hospital:
        h = self.get_hospital(org_id, hospital_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(h, field, value)
        self._commit()
        return h

    # -- departments -----------------------------------------------------------------
    def _hospital_or_400(self, org_id, hospital_id) -> Hospital:
        h = self.repo.get_in_organization(org_id, hospital_id)
        if h is None:
            raise BadRequestError("Hospital does not exist in your organization.")
        return h

    def create_department(self, org_id, data: DepartmentCreate) -> Department:
        self._hospital_or_400(org_id, data.hospital_id)
        dept = self.repo.add(Department(hospital_id=data.hospital_id, name=data.name))
        self._commit()
        return dept

    def get_department(self, org_id, department_id) -> Department:
        d = self.repo.get_department(org_id, department_id)
        if d is None:
            raise NotFoundError("Department not found.")
        return d

    def update_department(self, org_id, department_id, data: DepartmentUpdate) -> Department:
        d = self.get_department(org_id, department_id)
        d.name = data.name
        self._commit()
        return d

    def delete_department(self, org_id, department_id) -> None:
        self.db.delete(self.get_department(org_id, department_id))
        self._commit()  # blocked by PostgreSQL (RESTRICT) while devices still use it

    # -- locations --------------------------------------------------------------------
    def create_location(self, org_id, data: LocationCreate) -> Location:
        self._hospital_or_400(org_id, data.hospital_id)
        loc = self.repo.add(
            Location(hospital_id=data.hospital_id, building=data.building, floor=data.floor, room=data.room)
        )
        self._commit()
        return loc

    def get_location(self, org_id, location_id) -> Location:
        loc = self.repo.get_location(org_id, location_id)
        if loc is None:
            raise NotFoundError("Location not found.")
        return loc

    def update_location(self, org_id, location_id, data: LocationUpdate) -> Location:
        loc = self.get_location(org_id, location_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(loc, field, value)
        if not loc.label:
            raise BadRequestError("A location needs at least one of building, floor or room.")
        self._commit()
        return loc

    def delete_location(self, org_id, location_id) -> None:
        # PostgreSQL detaches devices (ON DELETE SET NULL); they are not deleted.
        self.db.delete(self.get_location(org_id, location_id))
        self._commit()
