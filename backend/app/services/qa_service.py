"""QA records (B6 CP2): inspections, calibrations and compliance checks.

Who may do what (approved B6 plan, Revision 5, section 2):

    action                      admin          biomedical_engineer   technician     department_user
    --------------------------  -------------  --------------------  -------------  ---------------
    read QA records             organization   own hospital          own hospital   403
    create / update a record    organization   own hospital          403            403
    delete                      no endpoint (QA records are history)

Order of checks (approval clarification): the ROLE first - 403 without any device or record lookup;
then existence and scope (404); then the device's state (400).

Rules:
- Status (D5): a record starts `pending` (or is created directly with its result). Only
  pending -> pass and pending -> fail are allowed; a pass / fail result is final (pass -> fail,
  fail -> pass and anything back to pending -> 409 invalid_qa_status_transition). Sending the
  current status again is not a transition. Engineers and admins may still correct the findings,
  performed_at and next_due_date of a finalized record (audited).
- performed_at is never in the future (5 minutes clock tolerance; D6).
- next_due_date is on or after the date of performed_at, as the DATABASE converts it
  (performed_at::date in its time zone): checked here first, ck_qa_next_due_after_performed is the
  last line of defence; HTTP 422 either way (Master Instructions section 4).
- No new records or corrections on archived devices or in inactive hospitals (Decision 6; D8);
  decommissioned and out-of-service devices are allowed (D9).
- No side effects (D11, D12): a failed check creates no ticket, changes no device status and sends
  no notification.
- Writes lock the device row first (the same lock as risk and maintenance writers; lock order device
  -> record). QA records never change devices, so there is no device audit row.
- Every create and update writes its audit row in the same transaction.
"""
import logging
import uuid
from datetime import date, datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.db_errors import CONSTRAINT_MESSAGES
from app.core.enums import QARecordType, QAStatus
from app.core.exceptions import AppError, BadRequestError, ConflictError, NotFoundError
from app.models.device import Device
from app.models.qa import QARecord
from app.repositories.device_repository import DeviceRepository
from app.repositories.qa_repository import DueFilters, QAFilters, QARepository
from app.schemas.qa import QARecordCreate, QARecordUpdate
from app.services.audit_service import AuditService, snapshot
from app.services.risk_service import (
    aware, reject_future, require_archived_access, require_reader, require_writer,
)

logger = logging.getLogger(__name__)

FINAL = frozenset({QAStatus.PASS, QAStatus.FAIL})
ALLOWED = {QAStatus.PENDING: FINAL, QAStatus.PASS: frozenset(), QAStatus.FAIL: frozenset()}
DUE_CONSTRAINT = "ck_qa_next_due_after_performed"


class InvalidQAStatusTransitionError(ConflictError):
    code = "invalid_qa_status_transition"
    default_message = "This QA status change is not allowed."


class QADueDateError(AppError):
    """Same status, code and message as the mapped CHECK violation (app/core/db_errors.py)."""
    status_code = 422
    code = "constraint_violation"
    default_message = CONSTRAINT_MESSAGES[DUE_CONSTRAINT]


def check_transition(current: QAStatus, target: QAStatus) -> None:
    if target == current:
        return  # not a transition
    if target not in ALLOWED[current]:
        raise InvalidQAStatusTransitionError(
            f"A QA record cannot go from {current.value} to {target.value}; a pass or fail result is final.",
            details=[{"from": current.value, "to": target.value, "allowed": sorted(s.value for s in ALLOWED[current])}],
        )


class QAService:
    WHAT = "QA records"

    def __init__(self, db: Session):
        self.db = db
        self.repo = QARepository(db)
        self.devices = DeviceRepository(db)
        self.audit = AuditService(db)

    # ---- reads --------------------------------------------------------------------------------------
    def get(self, scope: AccessScope, record_id: uuid.UUID) -> QARecord:
        require_reader(scope, self.WHAT)
        record = self.repo.get(scope, record_id)
        if record is None:
            raise NotFoundError("QA record not found.")
        return record

    def list(self, scope: AccessScope, f: QAFilters, sort: str, descending: bool, page: int,
             page_size: int) -> Tuple[List[QARecord], int]:
        require_reader(scope, self.WHAT)
        f.performed_from, f.performed_to = aware(f.performed_from), aware(f.performed_to)
        return self.repo.list(scope, f, sort, descending, page, page_size)

    def for_device(self, scope: AccessScope, device_id: uuid.UUID, f: QAFilters, page: int,
                   page_size: int) -> Tuple[List[QARecord], int]:
        require_reader(scope, self.WHAT)
        if self.devices.get(scope, device_id) is None:  # archived devices keep a readable history (D8b)
            raise NotFoundError("Device not found.")
        f.device_id = device_id
        return self.list(scope, f, "performed_at", True, page, page_size)

    # ---- CP3: summary and due list ---------------------------------------------------------------------
    def summary(self, scope: AccessScope, hospital_id: Optional[uuid.UUID], include_archived: bool) -> dict:
        """All QA records in scope, counted by status and by type (archived devices: admins who ask)."""
        require_reader(scope, self.WHAT)
        require_archived_access(scope, include_archived)
        by_status, by_type = self.repo.counts(scope, hospital_id, include_archived)
        return {"total": sum(by_status.values()),
                "by_status": {s.value: by_status.get(s, 0) for s in QAStatus},
                "by_type": {t.value: by_type.get(t, 0) for t in QARecordType},
                "hospital_id": hospital_id, "include_archived": include_archived}

    def due(self, scope: AccessScope, f: DueFilters, page: int, page_size: int) -> Tuple[List[QARecord], int, date]:
        """D15 / D18: the latest record per (device, record type), overdue and/or due within
        `within_days`. Returns the records, the total and the database's today."""
        require_reader(scope, self.WHAT)
        require_archived_access(scope, f.include_archived)
        items, total = self.repo.due(scope, f, page, page_size)
        return items, total, self.repo.today()

    # ---- writes -------------------------------------------------------------------------------------
    @staticmethod
    def _check_device_state(device: Device, correction: bool) -> None:
        if device.deleted_at is not None:
            raise BadRequestError("QA records of archived devices cannot be changed." if correction
                                  else "Archived devices cannot receive new QA records.")
        if not device.hospital.is_active:
            raise BadRequestError("Hospital is inactive; its QA records cannot be changed." if correction
                                  else "Hospital is inactive; QA records cannot be added to it.")

    def _check_due_date(self, performed_at: datetime, next_due_date: Optional[date]) -> None:
        if next_due_date is not None and next_due_date < self.repo.date_of(performed_at):
            raise QADueDateError()

    def create(self, scope: AccessScope, data: QARecordCreate) -> QARecord:
        require_writer(scope, "QA records")                              # role first, no lookup
        device = self.devices.get(scope, data.device_id)                 # existence and scope
        if device is None:
            raise NotFoundError("Device not found.")
        self.repo.lock_device(device.id)
        device = self.devices.get(scope, device.id)                      # state as committed now
        self._check_device_state(device, correction=False)
        performed_at = reject_future(data.performed_at, "The QA check date cannot be in the future.")
        if performed_at is None:
            performed_at = self.repo.now()  # what the column default would give, made explicit for the due-date rule
        self._check_due_date(performed_at, data.next_due_date)
        record = self.repo.add(QARecord(
            organization_id=device.organization_id, hospital_id=device.hospital_id, device_id=device.id,
            performed_by=scope.user_id, record_type=data.record_type, status=data.status, findings=data.findings,
            performed_at=performed_at, next_due_date=data.next_due_date,
        ))
        self.audit.inserted(scope.user_id, record)
        self.db.commit()
        logger.info("QA record created id=%s device=%s type=%s status=%s", record.id, device.id,
                    data.record_type, data.status)
        return self.get(scope, record.id)

    def update(self, scope: AccessScope, record_id: uuid.UUID, data: QARecordUpdate) -> QARecord:
        require_writer(scope, "QA records")                              # role first, no lookup
        record = self.repo.get(scope, record_id)                         # existence and scope
        if record is None:
            raise NotFoundError("QA record not found.")
        self.repo.lock_device(record.device_id)                          # lock order: device, then record
        record = self.repo.get(scope, record_id, for_update=True)
        device = self.devices.get(scope, record.device_id)
        self._check_device_state(device, correction=True)

        fields = data.model_fields_set
        changes = {}
        if "status" in fields:
            check_transition(record.status, data.status)
            if data.status != record.status:
                changes["status"] = data.status
        if "findings" in fields and data.findings != record.findings:
            changes["findings"] = data.findings
        performed_at = record.performed_at
        if "performed_at" in fields:
            performed_at = reject_future(data.performed_at, "The QA check date cannot be in the future.")
            if performed_at != record.performed_at:
                changes["performed_at"] = performed_at
        next_due = data.next_due_date if "next_due_date" in fields else record.next_due_date
        if "next_due_date" in fields and next_due != record.next_due_date:
            changes["next_due_date"] = next_due
        if {"performed_at", "next_due_date"} & set(changes):
            self._check_due_date(performed_at, next_due)
        if not changes:
            self.db.rollback()  # nothing to change: release the locks
            return self.get(scope, record_id)

        old = snapshot(record)
        for key, value in changes.items():
            setattr(record, key, value)
        self.db.flush()
        self.audit.updated(scope.user_id, record, old)
        self.db.commit()
        logger.info("QA record updated id=%s fields=%s", record_id, sorted(changes))
        return self.get(scope, record_id)
