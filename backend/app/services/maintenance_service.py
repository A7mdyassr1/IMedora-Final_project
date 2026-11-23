"""Maintenance management (B4 CP3): types, records, schedules, devices.next_maintenance_due_date.

Who may do what (approved B4 plan F7/F8 and the CP3 rules posted before coding):

    action                         technician     biomedical_engineer   admin          department_user
    -----------------------------  -------------  --------------------  -------------  ---------------
    read types / records / sched.  own hospital   own hospital          organization   403
    create a record                own hospital   own hospital          organization   403
      ... linked to a ticket       if assigned    own hospital          organization   -
    correct a record               -              own hospital          organization   -
    create / change a schedule     -              own hospital          organization   -
    create a maintenance type      -              -                     yes            -

Rules:
- Records are history: never deleted; engineers/admins may correct the description, and the work
  date when no schedule depends on it. performed_at is never in the future (5 minutes clock
  tolerance) and never before the linked ticket was reported.
- No new records or schedules on archived devices or in inactive hospitals (Decision 6).
- A record linked to a ticket: same device (also a composite FK), ticket not deleted / closed /
  cancelled; technicians must be actively assigned to it (Q5). The TICKET ROW IS LOCKED, so a
  record can never land on a ticket being cancelled at the same moment, and "resolve needs a
  record" (Q7) is checked against committed data.
- A record linked to a schedule moves it forward: last_performed_date = the work date and
  next_due_date = work date + frequency. A backdated record never moves a schedule backwards.
  Inactive schedules take no records.
- devices.next_maintenance_due_date = earliest next_due_date of the device's ACTIVE schedules
  (None when there are none). Recomputed in the same transaction as every change that can move
  it, with the DEVICE ROW LOCKED (lock order: ticket, then device), audited when it changes.
- Dates of timestamps are taken in the database's time zone (one deployment per organization).
- Every mutation writes its audit rows in the same transaction.

Parts used (B5 CP2; stock arithmetic by the database trigger, see app/services/part_usage.py):

    action                         technician            biomedical_engineer   admin
    -----------------------------  --------------------  --------------------  ------------
    list parts on a new record     yes (own hospital)    own hospital          organization
    add a part to a record         records they did      own hospital          organization
    correct / remove a usage line  -                     own hospital          organization
    read part usage                own hospital          own hospital          organization

- Parts come from the stock of the RECORD'S (device's) hospital, which must be active.
- A new record and its parts are one transaction: not enough stock -> nothing is recorded.
- No new usage on archived devices; corrections stay possible (bookkeeping of real movements).
- Usage on a ticket that is closed, cancelled or deleted is final (409); the ticket row is
  locked first, as for new records.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.roles import Role
from app.core.ticket_workflow import TERMINAL, TicketFacts, is_active_assignee, manages
from app.models.device import Device
from app.models.maintenance import MaintenanceRecord, MaintenanceSchedule, MaintenanceType
from app.repositories.device_repository import DeviceRepository
from app.repositories.maintenance_repository import MaintenanceRepository, RecordFilters, ScheduleFilters
from app.repositories.part_repository import PartRepository, UsageFilters
from app.repositories.ticket_repository import TicketRepository
from app.schemas.maintenance import (
    MaintenanceRecordCreate, MaintenanceRecordUpdate, MaintenanceScheduleCreate, MaintenanceScheduleUpdate,
)
from app.schemas.part import PartUse
from app.services.audit_service import AuditService, snapshot
from app.services.part_usage import PartUsage

logger = logging.getLogger(__name__)

STAFF = frozenset({Role.ADMIN, Role.BIOMEDICAL_ENGINEER, Role.TECHNICIAN})
FUTURE_TOLERANCE = timedelta(minutes=5)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class MaintenanceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MaintenanceRepository(db)
        self.devices = DeviceRepository(db)
        self.tickets = TicketRepository(db)
        self.audit = AuditService(db)
        self.usage = PartUsage(db, self.audit)

    # ---- permission helpers -------------------------------------------------------------------------
    @staticmethod
    def _require_staff(scope: AccessScope) -> None:
        if scope.role not in STAFF:
            raise ForbiddenError("Maintenance data is available to technicians, biomedical engineers and administrators.")

    @staticmethod
    def _manages_hospital(scope: AccessScope, hospital_id: uuid.UUID) -> bool:
        return scope.is_admin or (scope.role is Role.BIOMEDICAL_ENGINEER and scope.hospital_id == hospital_id)

    def _device_for_new_work(self, scope: AccessScope, device_id: uuid.UUID) -> Device:
        device = self.devices.get(scope, device_id)  # device scope: own hospital / organization
        if device is None:
            raise NotFoundError("Device not found.")
        if device.is_archived:
            raise BadRequestError("Archived devices cannot receive new maintenance data.")
        if not device.hospital.is_active:
            raise BadRequestError("Hospital is inactive; maintenance data cannot be added to it.")
        return device

    def _type(self, type_id: uuid.UUID) -> MaintenanceType:
        mtype = self.repo.get_type(type_id)
        if mtype is None:
            raise BadRequestError("Unknown maintenance type.")
        return mtype

    def today(self):
        return self.db.scalar(select(func.current_date()))

    # ---- devices.next_maintenance_due_date (the one writer) -------------------------------------------
    def _recompute_next_due(self, actor_id: uuid.UUID, device_id: uuid.UUID) -> None:
        """Call with the device row already locked (repo.lock_device)."""
        device = self.db.get(Device, device_id, populate_existing=True)
        new = self.repo.earliest_active_due(device_id)
        if device.next_maintenance_due_date != new:
            before = snapshot(device)
            device.next_maintenance_due_date = new
            self.db.flush()
            self.audit.updated(actor_id, device, before)

    # ---- types --------------------------------------------------------------------------------------
    def list_types(self, scope: AccessScope) -> List[MaintenanceType]:
        self._require_staff(scope)
        return self.repo.list_types()

    def create_type(self, scope: AccessScope, name: str) -> MaintenanceType:
        if not scope.is_admin:
            raise ForbiddenError("Only administrators can create maintenance types.")
        if self.repo.type_by_name(name) is not None:
            raise ConflictError("A maintenance type with this name already exists.")
        mtype = self.repo.add(MaintenanceType(name=name))
        # global reference data: the audit row carries the acting user's organization (as the catalog)
        self.audit.inserted(scope.user_id, mtype, organization_id=scope.organization_id)
        self.db.commit()
        return self.repo.get_type(mtype.id)

    # ---- records ------------------------------------------------------------------------------------
    def get_record(self, scope: AccessScope, record_id: uuid.UUID) -> MaintenanceRecord:
        self._require_staff(scope)
        record = self.repo.get_record(scope, record_id)
        if record is None:
            raise NotFoundError("Maintenance record not found.")
        return record

    def list_records(self, scope: AccessScope, f: RecordFilters, sort: str, descending: bool, page: int,
                     page_size: int) -> Tuple[List[MaintenanceRecord], int]:
        self._require_staff(scope)
        f.performed_from, f.performed_to = _aware(f.performed_from), _aware(f.performed_to)
        return self.repo.list_records(scope, f, sort, descending, page, page_size)

    def device_records(self, scope: AccessScope, device_id: uuid.UUID, f: RecordFilters, sort: str, descending: bool,
                       page: int, page_size: int) -> Tuple[List[MaintenanceRecord], int]:
        self._require_staff(scope)
        if self.devices.get(scope, device_id) is None:  # archived devices keep a readable history
            raise NotFoundError("Device not found.")
        f.device_id = device_id
        return self.list_records(scope, f, sort, descending, page, page_size)

    def _check_work_time(self, performed_at: Optional[datetime], ticket=None) -> Optional[datetime]:
        performed_at = _aware(performed_at)
        if performed_at is None:
            return None
        if performed_at > datetime.now(timezone.utc) + FUTURE_TOLERANCE:
            raise BadRequestError("The work date cannot be in the future.")
        if ticket is not None and performed_at < ticket.created_at:
            raise BadRequestError("Work on a ticket cannot be dated before the ticket was reported.")
        return performed_at

    def create_record(self, scope: AccessScope, data: MaintenanceRecordCreate) -> MaintenanceRecord:
        self._require_staff(scope)
        device = self._device_for_new_work(scope, data.device_id)
        mtype = self._type(data.maintenance_type_id)

        ticket = None
        if data.ticket_id is not None:
            # lock order: ticket, then device
            ticket = self.tickets.get_for_update(scope, data.ticket_id, include_deleted=scope.is_admin)
            if ticket is None or ticket.device_id != device.id:
                raise BadRequestError("The ticket does not exist or belongs to another device.")
            if ticket.is_deleted:
                raise ConflictError("Deleted tickets cannot be modified.")
            if ticket.status in TERMINAL:
                raise ConflictError("Closed or cancelled tickets cannot receive maintenance records.")
            facts = TicketFacts(ticket.hospital_id, ticket.reported_by, ticket.status,
                                frozenset(a.user_id for a in ticket.active_assignments))
            if not (manages(scope, facts) or is_active_assignee(scope, facts)):  # Q5
                raise ForbiddenError("Only the ticket's assignees, its hospital's engineers and administrators "
                                     "can record work on it.")
        performed_at = self._check_work_time(data.performed_at, ticket)

        schedule = None
        if data.schedule_id is not None:
            self.repo.lock_device(device.id)
            schedule = self.repo.get_schedule(scope, data.schedule_id, for_update=True)
            if schedule is None or schedule.device_id != device.id or schedule.maintenance_type_id != mtype.id:
                raise BadRequestError("The schedule does not exist or belongs to another device or maintenance type.")
            if not schedule.is_active:
                raise BadRequestError("Inactive schedules cannot receive maintenance records.")

        record = MaintenanceRecord(
            organization_id=device.organization_id, hospital_id=device.hospital_id, device_id=device.id,
            maintenance_type_id=mtype.id, ticket_id=data.ticket_id, schedule_id=data.schedule_id,
            performed_by=scope.user_id, description=data.description,
        )
        if performed_at is not None:
            record.performed_at = performed_at
        self.repo.add(record)
        self.audit.inserted(scope.user_id, record)

        if schedule is not None:
            work_date = self.repo.date_of(record.performed_at)
            if schedule.last_performed_date is None or work_date >= schedule.last_performed_date:
                before = snapshot(schedule)
                schedule.last_performed_date = work_date
                schedule.next_due_date = work_date + timedelta(days=schedule.frequency_days)
                self.db.flush()
                self.audit.updated(scope.user_id, schedule, before)
                self._recompute_next_due(scope.user_id, device.id)
        # B5: parts used, from the device's hospital stock (locked last); any failure undoes the record too
        self.usage.use(scope.user_id, record, data.parts)
        self.db.commit()
        logger.info("Maintenance record created id=%s device=%s ticket=%s schedule=%s parts=%s",
                    record.id, device.id, data.ticket_id, data.schedule_id, len(data.parts))
        return self.get_record(scope, record.id)

    def update_record(self, scope: AccessScope, record_id: uuid.UUID, data: MaintenanceRecordUpdate) -> MaintenanceRecord:
        self._require_staff(scope)
        record = self.repo.get_record(scope, record_id, for_update=True)
        if record is None:
            raise NotFoundError("Maintenance record not found.")
        if not self._manages_hospital(scope, record.hospital_id):
            raise ForbiddenError("Only biomedical engineers and administrators can correct maintenance records.")
        changes = {}
        if data.description is not None and data.description != record.description:
            changes["description"] = data.description
        if data.performed_at is not None:
            if record.schedule_id is not None:
                raise ConflictError("The work date of a scheduled maintenance record cannot be changed.")
            ticket = None
            if record.ticket_id is not None:
                ticket = self.tickets.get(scope, record.ticket_id, include_deleted=True)
            new_time = self._check_work_time(data.performed_at, ticket)
            if new_time != record.performed_at:
                changes["performed_at"] = new_time
        if not changes:
            self.db.rollback()
            return self.get_record(scope, record_id)
        before = snapshot(record)
        for key, value in changes.items():
            setattr(record, key, value)
        self.db.flush()
        self.audit.updated(scope.user_id, record, before)
        self.db.commit()
        return self.get_record(scope, record_id)

    # ---- parts used (B5 CP2) -------------------------------------------------------------------------
    def _record_for_usage(self, scope: AccessScope, record_id: uuid.UUID, *, correction: bool) -> MaintenanceRecord:
        """Checks who may change the record's parts, locks ticket -> record, returns the locked record."""
        self._require_staff(scope)
        record = self.repo.get_record(scope, record_id)
        if record is None:
            raise NotFoundError("Maintenance record not found.")
        manager = self._manages_hospital(scope, record.hospital_id)
        if correction and not manager:
            raise ForbiddenError("Only biomedical engineers of the hospital and administrators can correct the parts "
                                 "used on a maintenance record.")
        if not correction and not (manager or record.performed_by == scope.user_id):
            raise ForbiddenError("Only the technician who did the work, the hospital's engineers and administrators "
                                 "can add parts to this maintenance record.")
        if not record.device.hospital.is_active:
            raise BadRequestError("Hospital is inactive; its stock cannot be changed.")
        if not correction and record.device.deleted_at is not None:
            raise BadRequestError("Archived devices cannot receive new maintenance data.")
        if record.ticket_id is not None:
            ticket = self.tickets.get_for_update(scope, record.ticket_id, include_deleted=True)
            if ticket is None or ticket.is_deleted or ticket.status in TERMINAL:
                raise ConflictError("The parts used on a closed, cancelled or deleted ticket cannot be changed.")
        return self.repo.get_record(scope, record_id, for_update=True)

    def add_part(self, scope: AccessScope, record_id: uuid.UUID, line: PartUse) -> MaintenanceRecord:
        record = self._record_for_usage(scope, record_id, correction=False)
        self.usage.use(scope.user_id, record, [line])
        self.db.commit()
        logger.info("Part used record=%s part=%s quantity=%s", record_id, line.part_id, line.quantity)
        return self.get_record(scope, record_id)

    def _usage_line(self, record: MaintenanceRecord, part_id: uuid.UUID):
        usage = PartRepository(self.db).usage_line(record.id, part_id, for_update=True)
        if usage is None:
            raise NotFoundError("This part is not listed on this maintenance record.")
        return usage

    def change_part(self, scope: AccessScope, record_id: uuid.UUID, part_id: uuid.UUID, quantity: int) -> MaintenanceRecord:
        record = self._record_for_usage(scope, record_id, correction=True)
        if self.usage.change(scope.user_id, record, self._usage_line(record, part_id), quantity):
            self.db.commit()
            logger.info("Part usage corrected record=%s part=%s quantity=%s", record_id, part_id, quantity)
        else:
            self.db.rollback()  # nothing to change: release the locks
        return self.get_record(scope, record_id)

    def remove_part(self, scope: AccessScope, record_id: uuid.UUID, part_id: uuid.UUID) -> MaintenanceRecord:
        record = self._record_for_usage(scope, record_id, correction=True)
        self.usage.remove(scope.user_id, record, self._usage_line(record, part_id))
        self.db.commit()
        logger.info("Part usage removed record=%s part=%s", record_id, part_id)
        return self.get_record(scope, record_id)

    def list_usage(self, scope: AccessScope, f: UsageFilters, sort: str, descending: bool, page: int, page_size: int):
        self._require_staff(scope)
        f.performed_from, f.performed_to = _aware(f.performed_from), _aware(f.performed_to)
        return PartRepository(self.db).list_usage(scope, f, sort, descending, page, page_size)

    # ---- schedules ----------------------------------------------------------------------------------
    def get_schedule(self, scope: AccessScope, schedule_id: uuid.UUID) -> MaintenanceSchedule:
        self._require_staff(scope)
        schedule = self.repo.get_schedule(scope, schedule_id)
        if schedule is None:
            raise NotFoundError("Maintenance schedule not found.")
        return schedule

    def list_schedules(self, scope: AccessScope, f: ScheduleFilters, sort: str, descending: bool, page: int,
                       page_size: int) -> Tuple[List[MaintenanceSchedule], int]:
        self._require_staff(scope)
        return self.repo.list_schedules(scope, f, sort, descending, page, page_size)

    def device_schedules(self, scope: AccessScope, device_id: uuid.UUID, page: int, page_size: int):
        self._require_staff(scope)
        if self.devices.get(scope, device_id) is None:
            raise NotFoundError("Device not found.")
        f = ScheduleFilters(device_id=device_id, include_inactive=True, include_archived_devices=True)
        return self.repo.list_schedules(scope, f, "next_due_date", False, page, page_size)

    def create_schedule(self, scope: AccessScope, data: MaintenanceScheduleCreate) -> MaintenanceSchedule:
        self._require_staff(scope)
        device = self._device_for_new_work(scope, data.device_id)
        if not self._manages_hospital(scope, device.hospital_id):
            raise ForbiddenError("Only biomedical engineers and administrators can manage maintenance schedules.")
        mtype = self._type(data.maintenance_type_id)
        self.repo.lock_device(device.id)
        if self.repo.schedule_for(device.id, mtype.id) is not None:
            raise ConflictError("This device already has a schedule for this maintenance type.")
        schedule = self.repo.add(MaintenanceSchedule(
            organization_id=device.organization_id, hospital_id=device.hospital_id, device_id=device.id,
            maintenance_type_id=mtype.id, frequency_days=data.frequency_days, next_due_date=data.next_due_date,
            is_active=True,
        ))
        self.audit.inserted(scope.user_id, schedule)
        self._recompute_next_due(scope.user_id, device.id)
        self.db.commit()
        logger.info("Maintenance schedule created id=%s device=%s", schedule.id, device.id)
        return self.get_schedule(scope, schedule.id)

    def update_schedule(self, scope: AccessScope, schedule_id: uuid.UUID, data: MaintenanceScheduleUpdate) -> MaintenanceSchedule:
        self._require_staff(scope)
        schedule = self.repo.get_schedule(scope, schedule_id)
        if schedule is None:
            raise NotFoundError("Maintenance schedule not found.")
        if not self._manages_hospital(scope, schedule.hospital_id):
            raise ForbiddenError("Only biomedical engineers and administrators can manage maintenance schedules.")
        self.repo.lock_device(schedule.device_id)  # lock order: device, then schedule
        schedule = self.repo.get_schedule(scope, schedule_id, for_update=True)
        changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if getattr(schedule, k) != v}
        if not changes:
            self.db.rollback()
            return self.get_schedule(scope, schedule_id)
        deactivating_only = set(changes) == {"is_active"} and changes["is_active"] is False
        if not deactivating_only:
            if schedule.device.deleted_at is not None:
                raise BadRequestError("Schedules of archived devices can only be deactivated.")
            if changes.get("is_active") is True and not schedule.device.hospital.is_active:
                raise BadRequestError("Hospital is inactive; schedules cannot be reactivated in it.")
        before = snapshot(schedule)
        for key, value in changes.items():
            setattr(schedule, key, value)
        self.db.flush()
        self.audit.updated(scope.user_id, schedule, before)
        self._recompute_next_due(scope.user_id, schedule.device_id)
        self.db.commit()
        return self.get_schedule(scope, schedule_id)
