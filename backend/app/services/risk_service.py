"""Risk assessments (B6 CP1).

Who may do what (approved B6 plan, Revision 5, section 2):

    action                      admin          biomedical_engineer   technician     department_user
    --------------------------  -------------  --------------------  -------------  ---------------
    read assessments            organization   own hospital          own hospital   403
    create an assessment        organization   own hospital          403            403
    correct an assessment       organization   own hospital          403            403
    delete                      no endpoint (assessments are history)

Authorization order (approval clarification): the ROLE is checked first - a caller whose role may
not perform the operation gets 403 without any device or assessment lookup, so an unknown or
out-of-scope id never reveals whether it exists. Only then: existence and scope (404), then the
device's state (400).

Write sequence (create and correction), all in ONE transaction:
 1. role -> 403          2. device / assessment in scope -> 404
 3. lock the device row, reading devices.current_risk_level ("before")
 4. archived device / inactive hospital -> 400 (Decision 6; D8a, D8c, D8d)
 5. assessed_at not in the future (5 minutes clock tolerance) -> 400 (D6)
 6. no other assessment of the device at exactly this assessed_at -> 409 (D7)
 7. insert / update; flush - the database trigger recomputes devices.current_risk_level
 8. re-read devices.current_risk_level ("after")
 9. audit row for the assessment
10. D17: an audit row for the device when the trigger changed its level
11. commit

The trigger is the ONLY writer of devices.current_risk_level (Master Instructions section 4). The
device row lock orders concurrent writers so each trigger run sees the previous writer's committed
row (finding F1); it computes nothing. The backend only READS the level, before and after.

D17 is the team's interpretation of "an audit row for every mutation" (section 4) for the change
the trigger makes to the device, following B5's audited stock rows: action `update` on `devices`,
old {"current_risk_level": before}, new {"current_risk_level": after, "cause": {...}}, written at
clock_timestamp() so it sorts after the assessment's own row; skipped when the level is unchanged.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import AuditAction, RiskLevel
from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.roles import Role
from app.models.device import Device
from app.models.risk import RiskAssessment
from app.repositories.device_repository import DeviceRepository
from app.repositories.risk_repository import RiskFilters, RiskRepository
from app.schemas.risk import RiskAssessmentCreate, RiskAssessmentUpdate
from app.services.audit_service import AuditService, snapshot

logger = logging.getLogger(__name__)

READERS = frozenset({Role.ADMIN, Role.BIOMEDICAL_ENGINEER, Role.TECHNICIAN})
WRITERS = frozenset({Role.ADMIN, Role.BIOMEDICAL_ENGINEER})
FUTURE_TOLERANCE = timedelta(minutes=5)


class DuplicateAssessmentTimeError(ConflictError):
    code = "duplicate_assessment_time"
    default_message = ("This device already has a risk assessment at exactly this time. "
                       "Use a different assessment time or correct the existing assessment.")


def aware(value: Optional[datetime]) -> Optional[datetime]:
    """Timestamps without an offset are taken as UTC (the API's documented convention)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def reject_future(value: Optional[datetime], message: str) -> Optional[datetime]:
    value = aware(value)
    if value is not None and value > datetime.now(timezone.utc) + FUTURE_TOLERANCE:
        raise BadRequestError(message)
    return value


def require_reader(scope: AccessScope, what: str) -> None:
    if scope.role not in READERS:
        raise ForbiddenError(f"{what} are available to technicians, biomedical engineers and administrators.")


def require_archived_access(scope: AccessScope, include_archived: bool) -> None:
    """Decision 6 / B3.1: archived devices in lists and summaries are admin-only, never ignored silently."""
    if include_archived and not scope.is_admin:
        raise ForbiddenError("Only administrators can include archived devices.")


def require_writer(scope: AccessScope, what: str) -> None:
    if scope.role not in WRITERS:
        raise ForbiddenError(f"Only biomedical engineers and administrators can record or correct {what}.")


class RiskService:
    WHAT = "Risk assessments"

    def __init__(self, db: Session):
        self.db = db
        self.repo = RiskRepository(db)
        self.devices = DeviceRepository(db)
        self.audit = AuditService(db)

    # ---- reads --------------------------------------------------------------------------------------
    def get(self, scope: AccessScope, assessment_id: uuid.UUID) -> RiskAssessment:
        require_reader(scope, self.WHAT)
        assessment = self.repo.get(scope, assessment_id)
        if assessment is None:
            raise NotFoundError("Risk assessment not found.")
        return assessment

    def list(self, scope: AccessScope, f: RiskFilters, sort: str, descending: bool, page: int,
             page_size: int) -> Tuple[List[RiskAssessment], int]:
        require_reader(scope, self.WHAT)
        f.assessed_from, f.assessed_to = aware(f.assessed_from), aware(f.assessed_to)
        return self.repo.list(scope, f, sort, descending, page, page_size)

    def for_device(self, scope: AccessScope, device_id: uuid.UUID, f: RiskFilters, page: int,
                   page_size: int) -> Tuple[List[RiskAssessment], int]:
        require_reader(scope, self.WHAT)
        if self.devices.get(scope, device_id) is None:  # archived devices keep a readable history (D8b)
            raise NotFoundError("Device not found.")
        f.device_id = device_id
        return self.list(scope, f, "assessed_at", True, page, page_size)

    def summary(self, scope: AccessScope, hospital_id: Optional[uuid.UUID], include_archived: bool) -> dict:
        """CP3: devices per current risk level (the trigger's cached value, never recomputed) plus
        `unassessed`. Archived devices only for administrators who ask (Decision 6, as the device list)."""
        require_reader(scope, self.WHAT)
        require_archived_access(scope, include_archived)
        counts = self.repo.level_counts(scope, hospital_id, include_archived)
        by_level = {level.value: counts.get(level, 0) for level in RiskLevel}
        by_level["unassessed"] = counts.get(None, 0)
        return {"total": sum(by_level.values()), "by_level": by_level, "hospital_id": hospital_id,
                "include_archived": include_archived}

    # ---- writes -------------------------------------------------------------------------------------
    def _check_device_state(self, device: Device, correction: bool) -> None:
        if device.deleted_at is not None:
            raise BadRequestError("Risk assessments of archived devices cannot be corrected." if correction
                                  else "Archived devices cannot receive new risk assessments.")
        if not device.hospital.is_active:
            raise BadRequestError("Hospital is inactive; its risk assessments cannot be changed." if correction
                                  else "Hospital is inactive; risk assessments cannot be added to it.")

    def _audit_device_level(self, scope: AccessScope, device: Device, before: Optional[RiskLevel],
                            after: Optional[RiskLevel], assessment_id: uuid.UUID, action: str) -> None:
        """D17: the trigger's change to devices.current_risk_level, as READ before and after."""
        if before == after:
            return
        self.audit.record(
            actor_id=scope.user_id, organization_id=device.organization_id, table_name="devices",
            record_id=device.id, action=AuditAction.UPDATE,
            old_values={"current_risk_level": before.value if before else None},
            new_values={"current_risk_level": after.value if after else None,
                        "cause": {"table": "risk_assessments", "record_id": str(assessment_id), "action": action}},
            at=func.clock_timestamp(),
        )

    def create(self, scope: AccessScope, data: RiskAssessmentCreate) -> RiskAssessment:
        require_writer(scope, "risk assessments")                       # 1. role first, no lookup
        device = self.devices.get(scope, data.device_id)                 # 2. existence and scope
        if device is None:
            raise NotFoundError("Device not found.")
        before = self.repo.lock_device_risk(device.id)                   # 3. device row lock
        device = self.devices.get(scope, device.id)                      #    state as committed now
        self._check_device_state(device, correction=False)               # 4.
        assessed_at = reject_future(data.assessed_at, "The assessment date cannot be in the future.")  # 5.
        if assessed_at is None:
            assessed_at = self.repo.now()  # what the column default would give, made explicit for D7
        if self.repo.same_time_exists(device.id, assessed_at):           # 6.
            raise DuplicateAssessmentTimeError()
        assessment = self.repo.add(RiskAssessment(                      # 7. the trigger runs here
            organization_id=device.organization_id, hospital_id=device.hospital_id, device_id=device.id,
            assessed_by=scope.user_id, risk_level=data.risk_level, notes=data.notes, assessed_at=assessed_at,
        ))
        after = self.repo.read_device_risk(device.id)                    # 8.
        self.audit.inserted(scope.user_id, assessment)                   # 9.
        self._audit_device_level(scope, device, before, after, assessment.id, "insert")  # 10.
        self.db.commit()                                                 # 11.
        logger.info("Risk assessment created id=%s device=%s level=%s device_level %s->%s",
                    assessment.id, device.id, data.risk_level, before, after)
        self.db.expire_all()  # the response must show the level the trigger committed
        return self.get(scope, assessment.id)

    def update(self, scope: AccessScope, assessment_id: uuid.UUID, data: RiskAssessmentUpdate) -> RiskAssessment:
        require_writer(scope, "risk assessments")                       # 1. role first, no lookup
        assessment = self.repo.get(scope, assessment_id)                 # 2. existence and scope
        if assessment is None:
            raise NotFoundError("Risk assessment not found.")
        before = self.repo.lock_device_risk(assessment.device_id)        # 3. lock order: device, then row
        assessment = self.repo.get(scope, assessment_id, for_update=True)
        device = self.devices.get(scope, assessment.device_id)
        self._check_device_state(device, correction=True)                # 4.

        changes = {}
        fields = data.model_fields_set
        if "risk_level" in fields and data.risk_level != assessment.risk_level:
            changes["risk_level"] = data.risk_level
        if "notes" in fields and data.notes != assessment.notes:
            changes["notes"] = data.notes
        if "assessed_at" in fields:
            new_time = reject_future(data.assessed_at, "The assessment date cannot be in the future.")  # 5.
            if new_time != assessment.assessed_at:
                if self.repo.same_time_exists(assessment.device_id, new_time, exclude_id=assessment.id):  # 6.
                    raise DuplicateAssessmentTimeError()
                changes["assessed_at"] = new_time
        if not changes:
            self.db.rollback()  # nothing to change: release the locks
            return self.get(scope, assessment_id)

        old = snapshot(assessment)
        for key, value in changes.items():
            setattr(assessment, key, value)
        self.db.flush()                                                  # 7. the trigger runs here
        after = self.repo.read_device_risk(assessment.device_id)         # 8.
        self.audit.updated(scope.user_id, assessment, old)               # 9.
        self._audit_device_level(scope, device, before, after, assessment.id, "update")  # 10.
        self.db.commit()                                                 # 11.
        logger.info("Risk assessment corrected id=%s fields=%s device_level %s->%s",
                    assessment_id, sorted(changes), before, after)
        self.db.expire_all()
        return self.get(scope, assessment_id)
