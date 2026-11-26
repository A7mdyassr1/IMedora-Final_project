"""B6 CP1 - risk assessments without a database: request schemas (trusted fields, D4b), date helpers
(D6), and the approved authorization ORDER - the role is checked before any lookup, proven with a
database stub that fails the test if it is touched."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.access import AccessScope, DeviceAccess
from app.core.exceptions import BadRequestError, ForbiddenError
from app.core.roles import Role
from app.schemas.risk import RiskAssessmentCreate, RiskAssessmentUpdate
from app.services.risk_service import RiskService, aware, reject_future

DEVICE = uuid.uuid4()


class _NoDatabase:
    """Any attribute access means the service tried to use the database."""

    def __getattr__(self, name):
        raise AssertionError(f"the database was used ({name}) before the role check")


def _scope(role: Role) -> AccessScope:
    access = {Role.ADMIN: DeviceAccess.ORGANIZATION, Role.DEPARTMENT_USER: DeviceAccess.DEPARTMENT}.get(role, DeviceAccess.HOSPITAL)
    return AccessScope(uuid.uuid4(), role, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), access)


# ---- schemas ------------------------------------------------------------------------------------------
def test_create_requires_device_and_level_and_trims_notes():
    body = RiskAssessmentCreate(device_id=DEVICE, risk_level="high", notes="  Battery swelling  ")
    assert body.notes == "Battery swelling" and body.assessed_at is None
    with pytest.raises(ValidationError):
        RiskAssessmentCreate(risk_level="high")
    with pytest.raises(ValidationError):
        RiskAssessmentCreate(device_id=DEVICE)


@pytest.mark.parametrize("field", ["organization_id", "hospital_id", "assessed_by", "id", "created_at", "updated_at"])
def test_create_rejects_fields_the_server_sets(field):
    with pytest.raises(ValidationError):
        RiskAssessmentCreate(device_id=DEVICE, risk_level="low", **{field: str(uuid.uuid4())})


@pytest.mark.parametrize("value", ["", "   ", "x" * 4001])
def test_notes_cannot_be_blank_or_too_long(value):
    with pytest.raises(ValidationError):
        RiskAssessmentCreate(device_id=DEVICE, risk_level="low", notes=value)


@pytest.mark.parametrize("level", ["severe", "HIGH", "", None])
def test_only_the_original_risk_levels_are_accepted(level):
    with pytest.raises(ValidationError):
        RiskAssessmentCreate(device_id=DEVICE, risk_level=level)
    assert {RiskAssessmentCreate(device_id=DEVICE, risk_level=v).risk_level.value
            for v in ("low", "medium", "high", "critical")} == {"low", "medium", "high", "critical"}


@pytest.mark.parametrize("field", ["device_id", "organization_id", "hospital_id", "assessed_by", "id", "created_at"])
def test_correction_rejects_the_device_and_identity_fields(field):
    with pytest.raises(ValidationError):
        RiskAssessmentUpdate(risk_level="low", **{field: str(uuid.uuid4())})


def test_correction_rules():
    with pytest.raises(ValidationError):
        RiskAssessmentUpdate()                       # nothing to change
    for null in ("risk_level", "assessed_at"):
        with pytest.raises(ValidationError):
            RiskAssessmentUpdate(**{null: None})
    cleared = RiskAssessmentUpdate(notes=None)       # null notes = clear them
    assert cleared.model_fields_set == {"notes"} and cleared.notes is None


# ---- dates (D6) ---------------------------------------------------------------------------------------
def test_naive_times_are_utc_and_future_times_are_refused():
    assert aware(datetime(2026, 1, 1, 8)).tzinfo == timezone.utc
    assert aware(None) is None
    within_tolerance = datetime.now(timezone.utc) + timedelta(minutes=2)
    assert reject_future(within_tolerance, "x") == within_tolerance
    with pytest.raises(BadRequestError):
        reject_future(datetime.now(timezone.utc) + timedelta(minutes=10), "x")


# ---- authorization order: role first, no lookup ------------------------------------------------------------
@pytest.mark.parametrize("role", [Role.TECHNICIAN, Role.DEPARTMENT_USER])
def test_writers_are_checked_before_any_database_access(role):
    service = RiskService(_NoDatabase())
    with pytest.raises(ForbiddenError):
        service.create(_scope(role), RiskAssessmentCreate(device_id=DEVICE, risk_level="low"))
    with pytest.raises(ForbiddenError):
        service.update(_scope(role), uuid.uuid4(), RiskAssessmentUpdate(notes="x"))


def test_department_users_are_refused_reads_before_any_database_access():
    service = RiskService(_NoDatabase())
    scope = _scope(Role.DEPARTMENT_USER)
    from app.repositories.risk_repository import RiskFilters
    for call in (lambda: service.get(scope, uuid.uuid4()),
                 lambda: service.list(scope, RiskFilters(), "assessed_at", True, 1, 20),
                 lambda: service.for_device(scope, uuid.uuid4(), RiskFilters(), 1, 20)):
        with pytest.raises(ForbiddenError):
            call()
