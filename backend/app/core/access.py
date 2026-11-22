"""Central data-access scope (B3.1 CP3).

ONE place decides what part of the organization a user may read. Everything is derived from
the authenticated user's own database row (role, organization, hospital, department) as loaded
by `get_current_user` - never from query parameters or request bodies.

    role                 devices                       hospitals / departments / locations
    -------------------  ----------------------------  ------------------------------------
    admin                whole organization            whole organization
    biomedical_engineer  own hospital                  own hospital
    technician           own hospital                  own hospital
    department_user      own department                own hospital
    department_user      NONE -> 403 department_required   own hospital
      without department

QR exception (approved): a department user may look a device up by QR anywhere in their OWN
hospital, but outside their own department they only get the limited summary (see
DeviceService.get_by_qr). Problem reporting through QR arrives with the B4 ticket APIs.

Out-of-scope records are reported as 404 by the callers, exactly like records that do not
exist, so the API never reveals that they exist.

This module has no database access and no SQL: repositories turn a scope into WHERE clauses.
"""
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from app.core.exceptions import ForbiddenError
from app.core.roles import Role


class DepartmentRequiredError(ForbiddenError):
    code = "department_required"
    default_message = "An administrator must assign you to a department before you can access devices."


class DeviceAccess(StrEnum):
    ORGANIZATION = "organization"
    HOSPITAL = "hospital"
    DEPARTMENT = "department"
    NONE = "none"  # department_user without a department


@dataclass(frozen=True)
class AccessScope:
    user_id: uuid.UUID
    role: Role
    organization_id: uuid.UUID
    hospital_id: uuid.UUID                 # the user's own hospital (users.hospital_id is NOT NULL)
    department_id: Optional[uuid.UUID]     # the user's own department, if any
    device_access: DeviceAccess

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    # ---- devices ----------------------------------------------------------------------------
    def require_device_access(self) -> None:
        """Raise 403 department_required for a department user without a department."""
        if self.device_access is DeviceAccess.NONE:
            raise DepartmentRequiredError()

    @property
    def device_hospital_id(self) -> Optional[uuid.UUID]:
        """Hospital every device query must be limited to; None = whole organization."""
        return None if self.device_access is DeviceAccess.ORGANIZATION else self.hospital_id

    @property
    def device_department_id(self) -> Optional[uuid.UUID]:
        """Department every device query must be limited to; None = no department limit."""
        return self.department_id if self.device_access is DeviceAccess.DEPARTMENT else None

    def qr_lookup_scope(self) -> "AccessScope":
        """The scope used for QR lookups. Identical to the normal scope except that a department
        user may resolve QR codes across their whole hospital (the approved QR exception)."""
        self.require_device_access()
        if self.device_access is DeviceAccess.DEPARTMENT:
            return AccessScope(self.user_id, self.role, self.organization_id, self.hospital_id,
                               self.department_id, DeviceAccess.HOSPITAL)
        return self

    def sees_full_device(self, device_department_id: uuid.UUID) -> bool:
        """False only for a department user looking at a device of another department."""
        if self.device_access is DeviceAccess.DEPARTMENT:
            return device_department_id == self.department_id
        return self.device_access is not DeviceAccess.NONE

    # ---- organization structure (hospitals, departments, locations) ------------------------
    @property
    def structure_hospital_id(self) -> Optional[uuid.UUID]:
        """Hospital that structure reads are limited to; None = whole organization (admin)."""
        return None if self.is_admin else self.hospital_id


def scope_for(user) -> AccessScope:
    """Build the scope from an authenticated User row (role relationship loaded)."""
    try:
        role = Role(user.role.name)
    except ValueError:
        # A role name the backend does not know (e.g. a stray test role) grants nothing.
        raise ForbiddenError()
    if role is Role.ADMIN:
        access = DeviceAccess.ORGANIZATION
    elif role in (Role.BIOMEDICAL_ENGINEER, Role.TECHNICIAN):
        access = DeviceAccess.HOSPITAL
    elif role is Role.DEPARTMENT_USER:
        access = DeviceAccess.DEPARTMENT if user.department_id is not None else DeviceAccess.NONE
    else:  # pragma: no cover - every Role member is handled above
        raise ForbiddenError()
    return AccessScope(
        user_id=user.id,
        role=role,
        organization_id=user.organization_id,
        hospital_id=user.hospital_id,
        department_id=user.department_id,
        device_access=access,
    )
