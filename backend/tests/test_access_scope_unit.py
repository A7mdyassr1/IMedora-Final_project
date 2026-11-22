"""AccessScope derivation (B3.1 CP3, T1). No database."""
import uuid
from types import SimpleNamespace

import pytest

from app.core.access import AccessScope, DepartmentRequiredError, DeviceAccess, scope_for
from app.core.exceptions import ForbiddenError
from app.core.roles import Role

ORG, H1, ICU, LAB = (uuid.uuid4() for _ in range(4))


def user(role: str, department_id=ICU, hospital_id=H1):
    return SimpleNamespace(id=uuid.uuid4(), role=SimpleNamespace(name=role), organization_id=ORG,
                           hospital_id=hospital_id, department_id=department_id)


def test_admin_is_organization_wide_for_everything():
    s = scope_for(user("admin", department_id=None))
    assert s.is_admin and s.device_access is DeviceAccess.ORGANIZATION
    assert s.device_hospital_id is None and s.device_department_id is None
    assert s.structure_hospital_id is None


@pytest.mark.parametrize("role", ["biomedical_engineer", "technician"])
def test_engineer_and_technician_are_hospital_wide(role):
    s = scope_for(user(role, department_id=ICU))  # a department on the user does NOT narrow them
    assert s.device_access is DeviceAccess.HOSPITAL
    assert s.device_hospital_id == H1 and s.device_department_id is None
    assert s.structure_hospital_id == H1


def test_department_user_is_limited_to_their_department():
    s = scope_for(user("department_user", department_id=ICU))
    assert s.device_access is DeviceAccess.DEPARTMENT
    assert s.device_hospital_id == H1 and s.device_department_id == ICU
    assert s.structure_hospital_id == H1  # may list their own hospital's structure


def test_department_user_without_department_has_no_device_access():
    s = scope_for(user("department_user", department_id=None))
    assert s.device_access is DeviceAccess.NONE
    with pytest.raises(DepartmentRequiredError) as exc:
        s.require_device_access()
    assert exc.value.status_code == 403 and exc.value.code == "department_required"
    assert exc.value.message == "An administrator must assign you to a department before you can access devices."
    with pytest.raises(DepartmentRequiredError):
        s.qr_lookup_scope()
    assert s.structure_hospital_id == H1  # still NOT organization-wide for structure
    assert s.device_hospital_id == H1     # never falls back to organization-wide


def test_qr_exception_widens_only_department_users_and_only_to_their_hospital():
    dept = scope_for(user("department_user", department_id=ICU))
    q = dept.qr_lookup_scope()
    assert q.device_access is DeviceAccess.HOSPITAL and q.device_hospital_id == H1
    assert q.organization_id == ORG and q.role is Role.DEPARTMENT_USER
    for role in ("admin", "biomedical_engineer", "technician"):
        s = scope_for(user(role))
        assert s.qr_lookup_scope() is s  # unchanged for everyone else


def test_full_or_limited_device_view():
    dept = scope_for(user("department_user", department_id=ICU))
    assert dept.sees_full_device(ICU) and not dept.sees_full_device(LAB)
    for role in ("admin", "biomedical_engineer", "technician"):
        assert scope_for(user(role)).sees_full_device(LAB)
    assert not scope_for(user("department_user", department_id=None)).sees_full_device(ICU)


def test_unknown_role_grants_nothing():
    with pytest.raises(ForbiddenError):
        scope_for(user("technician-1a2b3c"))  # e.g. a stray role row left by validation scripts


def test_scope_is_immutable():
    s = scope_for(user("technician"))
    with pytest.raises(Exception):
        s.hospital_id = uuid.uuid4()  # type: ignore[misc]
    assert isinstance(s, AccessScope)
