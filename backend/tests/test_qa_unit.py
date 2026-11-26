"""B6 CP2 - QA records without a database: request schemas (trusted fields, D4b), the status rules
(D5), the 422 due-date error, and the approved authorization ORDER (role first, no lookup)."""
import uuid

import pytest
from pydantic import ValidationError

from app.core.access import AccessScope, DeviceAccess
from app.core.enums import QARecordType, QAStatus
from app.core.exceptions import ForbiddenError
from app.core.roles import Role
from app.repositories.qa_repository import QAFilters
from app.schemas.qa import QARecordCreate, QARecordUpdate
from app.services.qa_service import InvalidQAStatusTransitionError, QADueDateError, QAService, check_transition

DEVICE = uuid.uuid4()
P, F, PEND = QAStatus.PASS, QAStatus.FAIL, QAStatus.PENDING


class _NoDatabase:
    def __getattr__(self, name):
        raise AssertionError(f"the database was used ({name}) before the role check")


def _scope(role: Role) -> AccessScope:
    access = {Role.ADMIN: DeviceAccess.ORGANIZATION, Role.DEPARTMENT_USER: DeviceAccess.DEPARTMENT}.get(role, DeviceAccess.HOSPITAL)
    return AccessScope(uuid.uuid4(), role, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), access)


# ---- status rules (D5) --------------------------------------------------------------------------------------
@pytest.mark.parametrize("current,target", [(PEND, P), (PEND, F), (PEND, PEND), (P, P), (F, F)])
def test_allowed_status_changes(current, target):
    check_transition(current, target)  # no exception


@pytest.mark.parametrize("current,target", [(P, F), (F, P), (P, PEND), (F, PEND)])
def test_a_final_result_cannot_change(current, target):
    with pytest.raises(InvalidQAStatusTransitionError) as exc:
        check_transition(current, target)
    assert exc.value.status_code == 409 and exc.value.code == "invalid_qa_status_transition"
    assert exc.value.details == [{"from": current.value, "to": target.value, "allowed": []}]


def test_enums_are_the_original_values():
    assert [m.value for m in QARecordType] == ["inspection", "calibration", "compliance"]
    assert [m.value for m in QAStatus] == ["pass", "fail", "pending"]


def test_due_date_error_is_the_mapped_constraint_response():
    err = QADueDateError()
    assert (err.status_code, err.code) == (422, "constraint_violation")
    assert err.message == "The next due date cannot be before the date the QA check was performed."


# ---- schemas (D4b) ------------------------------------------------------------------------------------------
def test_create_defaults_and_requirements():
    body = QARecordCreate(device_id=DEVICE, record_type="calibration", findings="  Within tolerance ")
    assert body.status is QAStatus.PENDING and body.findings == "Within tolerance" and body.next_due_date is None
    for missing in ({"record_type": "calibration"}, {"device_id": DEVICE}):
        with pytest.raises(ValidationError):
            QARecordCreate(**missing)


@pytest.mark.parametrize("field", ["organization_id", "hospital_id", "performed_by", "id", "created_at", "updated_at"])
def test_create_rejects_fields_the_server_sets(field):
    with pytest.raises(ValidationError):
        QARecordCreate(device_id=DEVICE, record_type="inspection", **{field: str(uuid.uuid4())})


@pytest.mark.parametrize("field", ["device_id", "record_type", "organization_id", "hospital_id", "performed_by", "id"])
def test_update_rejects_the_device_type_and_identity_fields(field):
    with pytest.raises(ValidationError):
        QARecordUpdate(status="pass", **{field: "inspection" if field == "record_type" else str(uuid.uuid4())})


def test_update_rules():
    with pytest.raises(ValidationError):
        QARecordUpdate()
    for null in ("status", "performed_at"):
        with pytest.raises(ValidationError):
            QARecordUpdate(**{null: None})
    cleared = QARecordUpdate(findings=None, next_due_date=None)
    assert cleared.model_fields_set == {"findings", "next_due_date"}


# ---- authorization order: role first, no lookup ----------------------------------------------------------------
@pytest.mark.parametrize("role", [Role.TECHNICIAN, Role.DEPARTMENT_USER])
def test_writers_are_checked_before_any_database_access(role):
    service = QAService(_NoDatabase())
    with pytest.raises(ForbiddenError):
        service.create(_scope(role), QARecordCreate(device_id=DEVICE, record_type="calibration"))
    with pytest.raises(ForbiddenError):
        service.update(_scope(role), uuid.uuid4(), QARecordUpdate(status="pass"))


def test_department_users_are_refused_reads_before_any_database_access():
    service = QAService(_NoDatabase())
    scope = _scope(Role.DEPARTMENT_USER)
    for call in (lambda: service.get(scope, uuid.uuid4()),
                 lambda: service.list(scope, QAFilters(), "performed_at", True, 1, 20),
                 lambda: service.for_device(scope, uuid.uuid4(), QAFilters(), 1, 20)):
        with pytest.raises(ForbiddenError):
            call()
