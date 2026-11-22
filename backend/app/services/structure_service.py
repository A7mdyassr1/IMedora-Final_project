import logging
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.department import Department
from app.models.hospital import Hospital
from app.models.location import Location
from app.models.organization import Organization
from app.core.access import AccessScope
from app.models.user import User
from app.repositories.hospital_repository import HospitalRepository
from app.schemas.structure import (
    DepartmentCreate, DepartmentUpdate, HospitalCreate, HospitalUpdate, LocationCreate, LocationUpdate,
)
from app.services.audit_service import AuditService, snapshot

logger = logging.getLogger(__name__)


class StructureService:
    """Organization / hospitals / departments / locations. Everything is scoped to one organization.

    Every change takes the acting user (`actor`) and writes an audit row in the same transaction.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = HospitalRepository(db)
        self.audit = AuditService(db)

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

    def rename_organization(self, org_id: uuid.UUID, name: str, *, actor: User) -> Organization:
        org = self.get_organization(org_id)
        before = snapshot(org)
        org.name = name
        self.audit.updated(actor.id, org, before, organization_id=org.id)
        self._commit()
        return org

    # -- hospitals ----------------------------------------------------------------
    def create_hospital(self, org_id: uuid.UUID, data: HospitalCreate, *, actor: User) -> Hospital:
        hospital = self.repo.add(Hospital(organization_id=org_id, name=data.name, code=data.code, address=data.address, is_active=True))
        self.audit.inserted(actor.id, hospital)
        self._commit()
        logger.info("Hospital created id=%s", hospital.id)
        return hospital

    def get_hospital(self, org_id, hospital_id) -> Hospital:
        h = self.repo.get_in_organization(org_id, hospital_id)
        if h is None:
            raise NotFoundError("Hospital not found.")
        return h

    # -- scoped reads (B3.1 CP3) ------------------------------------------------------
    # Admin: whole organization. Everyone else: their own hospital only. A record outside the
    # scope is a 404, exactly like a record that does not exist. Write paths (admin-only) keep
    # using the organization-level getters above and below.
    def list_hospitals(self, scope: AccessScope, page: int, page_size: int, q=None, is_active=None):
        return self.repo.list_hospitals(scope.organization_id, page, page_size, q, is_active,
                                        within_hospital=scope.structure_hospital_id)

    def read_hospital(self, scope: AccessScope, hospital_id) -> Hospital:
        if scope.structure_hospital_id is not None and hospital_id != scope.structure_hospital_id:
            raise NotFoundError("Hospital not found.")
        return self.get_hospital(scope.organization_id, hospital_id)

    def list_departments(self, scope: AccessScope, page: int, page_size: int, hospital_id=None, q=None):
        return self.repo.list_departments(scope.organization_id, page, page_size, hospital_id, q,
                                          within_hospital=scope.structure_hospital_id)

    def read_department(self, scope: AccessScope, department_id) -> Department:
        d = self.repo.get_department(scope.organization_id, department_id, within_hospital=scope.structure_hospital_id)
        if d is None:
            raise NotFoundError("Department not found.")
        return d

    def list_locations(self, scope: AccessScope, page: int, page_size: int, hospital_id=None):
        return self.repo.list_locations(scope.organization_id, page, page_size, hospital_id,
                                        within_hospital=scope.structure_hospital_id)

    def read_location(self, scope: AccessScope, location_id) -> Location:
        loc = self.repo.get_location(scope.organization_id, location_id, within_hospital=scope.structure_hospital_id)
        if loc is None:
            raise NotFoundError("Location not found.")
        return loc

    def update_hospital(self, org_id, hospital_id, data: HospitalUpdate, *, actor: User) -> Hospital:
        h = self.get_hospital(org_id, hospital_id)
        changes = data.model_dump(exclude_unset=True)
        # Lock-out guard: every user belongs to a hospital, and users of an inactive hospital
        # cannot log in, so deactivating your own hospital would lock you out immediately.
        if changes.get("is_active") is False and h.id == actor.hospital_id:
            raise BadRequestError("You cannot deactivate the hospital you belong to; it would lock you out.")
        before = snapshot(h)
        for field, value in changes.items():
            setattr(h, field, value)
        self.audit.updated(actor.id, h, before)
        self._commit()
        return h

    # -- departments -----------------------------------------------------------------
    def _active_hospital_or_400(self, org_id, hospital_id, what: str) -> Hospital:
        h = self.repo.get_in_organization(org_id, hospital_id)
        if h is None:
            raise BadRequestError("Hospital does not exist in your organization.")
        if not h.is_active:  # Decision 6: nothing new is added to an inactive hospital
            raise BadRequestError(f"Hospital is inactive; {what} cannot be added to it.")
        return h

    def create_department(self, org_id, data: DepartmentCreate, *, actor: User) -> Department:
        self._active_hospital_or_400(org_id, data.hospital_id, "departments")
        dept = self.repo.add(Department(hospital_id=data.hospital_id, name=data.name))
        self.audit.inserted(actor.id, dept, organization_id=org_id)
        self._commit()
        return dept

    def get_department(self, org_id, department_id) -> Department:
        d = self.repo.get_department(org_id, department_id)
        if d is None:
            raise NotFoundError("Department not found.")
        return d

    def update_department(self, org_id, department_id, data: DepartmentUpdate, *, actor: User) -> Department:
        d = self.get_department(org_id, department_id)
        before = snapshot(d)
        d.name = data.name
        self.audit.updated(actor.id, d, before, organization_id=org_id)
        self._commit()
        return d

    def delete_department(self, org_id, department_id, *, actor: User) -> None:
        d = self.get_department(org_id, department_id)
        self.audit.deleted(actor.id, d, organization_id=org_id)
        self.db.delete(d)
        # Blocked by PostgreSQL (RESTRICT) while devices still use it; the audit row then rolls back too.
        self._commit()

    # -- locations --------------------------------------------------------------------
    def create_location(self, org_id, data: LocationCreate, *, actor: User) -> Location:
        self._active_hospital_or_400(org_id, data.hospital_id, "locations")
        loc = self.repo.add(
            Location(hospital_id=data.hospital_id, building=data.building, floor=data.floor, room=data.room)
        )
        self.audit.inserted(actor.id, loc, organization_id=org_id)
        self._commit()
        return loc

    def get_location(self, org_id, location_id) -> Location:
        loc = self.repo.get_location(org_id, location_id)
        if loc is None:
            raise NotFoundError("Location not found.")
        return loc

    def update_location(self, org_id, location_id, data: LocationUpdate, *, actor: User) -> Location:
        loc = self.get_location(org_id, location_id)
        before = snapshot(loc)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(loc, field, value)
        if not loc.label:
            raise BadRequestError("A location needs at least one of building, floor or room.")
        self.audit.updated(actor.id, loc, before, organization_id=org_id)
        self._commit()
        return loc

    def delete_location(self, org_id, location_id, *, actor: User) -> None:
        # PostgreSQL detaches devices (ON DELETE SET NULL); they are not deleted. That detaching
        # is done by the database itself, so only the location's own deletion is audited.
        loc = self.get_location(org_id, location_id)
        self.audit.deleted(actor.id, loc, organization_id=org_id)
        self.db.delete(loc)
        self._commit()
