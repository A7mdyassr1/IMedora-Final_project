"""Maintenance types, records and schedules (B4 CP3).

Scope: records and schedules carry organization_id and hospital_id, so the caller's DEVICE scope
(AccessScope.device_hospital_id: own hospital for engineers / technicians, None = organization
for admins) becomes plain WHERE clauses. Department users have no access (checked by the
service). Out of scope = not found (404), like every other B3.1/B4 read.

`devices.next_maintenance_due_date` has exactly one writer: `recompute_next_due`, which runs
after every change that can affect it, inside the same transaction, with the device row locked.
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.models.device import Device
from app.models.maintenance import MaintenanceRecord, MaintenanceSchedule, MaintenanceType
from app.repositories.pagination import paginate

RECORD_SORT = {"performed_at": MaintenanceRecord.performed_at, "created_at": MaintenanceRecord.created_at}
SCHEDULE_SORT = {"next_due_date": MaintenanceSchedule.next_due_date, "created_at": MaintenanceSchedule.created_at,
                 "frequency_days": MaintenanceSchedule.frequency_days}


@dataclass
class RecordFilters:
    device_id: Optional[uuid.UUID] = None
    hospital_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None   # the device's department
    maintenance_type_id: Optional[uuid.UUID] = None
    performed_by: Optional[uuid.UUID] = None
    ticket_id: Optional[uuid.UUID] = None
    schedule_id: Optional[uuid.UUID] = None
    performed_from: Optional[datetime] = None   # inclusive
    performed_to: Optional[datetime] = None     # exclusive


@dataclass
class ScheduleFilters:
    device_id: Optional[uuid.UUID] = None
    hospital_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    maintenance_type_id: Optional[uuid.UUID] = None
    include_inactive: bool = False
    include_archived_devices: bool = False
    due_before: Optional[date] = None           # inclusive
    overdue: bool = False                       # next_due_date before today (database date)


def _scoped(model, scope: AccessScope) -> list:
    conditions = [model.organization_id == scope.organization_id]
    if scope.device_hospital_id is not None:
        conditions.append(model.hospital_id == scope.device_hospital_id)
    return conditions


class MaintenanceRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, obj):
        self.db.add(obj)
        self.db.flush()
        return obj

    # ---- types (global reference data) ----------------------------------------------------------
    def list_types(self) -> List[MaintenanceType]:
        return list(self.db.scalars(select(MaintenanceType).order_by(MaintenanceType.name)))

    def get_type(self, type_id: uuid.UUID) -> Optional[MaintenanceType]:
        return self.db.get(MaintenanceType, type_id)

    def type_by_name(self, name: str) -> Optional[MaintenanceType]:
        return self.db.scalar(select(MaintenanceType).where(MaintenanceType.name == name))

    # ---- records ------------------------------------------------------------------------------------
    def get_record(self, scope: AccessScope, record_id: uuid.UUID, for_update: bool = False) -> Optional[MaintenanceRecord]:
        stmt = select(MaintenanceRecord).where(MaintenanceRecord.id == record_id, *_scoped(MaintenanceRecord, scope))
        if for_update:
            stmt = stmt.with_for_update(of=MaintenanceRecord)
        return self.db.scalars(stmt.execution_options(populate_existing=True)).first()

    def list_records(self, scope: AccessScope, f: RecordFilters, sort: str, descending: bool, page: int,
                     page_size: int) -> Tuple[List[MaintenanceRecord], int]:
        stmt = select(MaintenanceRecord).where(*_scoped(MaintenanceRecord, scope))
        for column, value in ((MaintenanceRecord.device_id, f.device_id), (MaintenanceRecord.hospital_id, f.hospital_id),
                              (MaintenanceRecord.maintenance_type_id, f.maintenance_type_id),
                              (MaintenanceRecord.performed_by, f.performed_by), (MaintenanceRecord.ticket_id, f.ticket_id),
                              (MaintenanceRecord.schedule_id, f.schedule_id)):
            if value is not None:
                stmt = stmt.where(column == value)
        if f.department_id:
            stmt = stmt.where(MaintenanceRecord.device_id.in_(select(Device.id).where(Device.department_id == f.department_id)))
        if f.performed_from:
            stmt = stmt.where(MaintenanceRecord.performed_at >= f.performed_from)
        if f.performed_to:
            stmt = stmt.where(MaintenanceRecord.performed_at < f.performed_to)
        column = RECORD_SORT[sort]
        stmt = stmt.order_by(column.desc() if descending else column.asc(), MaintenanceRecord.id)
        return paginate(self.db, stmt, page, page_size)

    def work_for_ticket(self, ticket_id: uuid.UUID, device_id: uuid.UUID) -> list:
        """(performed_at, performed_by, description) of the records linked to a ticket, oldest first -
        only the columns the timeline needs (index ix_records_ticket_id)."""
        return list(self.db.execute(
            select(MaintenanceRecord.performed_at, MaintenanceRecord.performed_by, MaintenanceRecord.description)
            .where(MaintenanceRecord.ticket_id == ticket_id, MaintenanceRecord.device_id == device_id)
            .order_by(MaintenanceRecord.performed_at, MaintenanceRecord.id)))

    def date_of(self, value) -> date:
        """The calendar date of a timestamp as the DATABASE sees it (its TimeZone setting): the same
        rule PostgreSQL applies to `performed_at::date`, independent of the application server."""
        return self.db.scalar(select(cast(value, Date)))

    # ---- schedules ----------------------------------------------------------------------------------
    def get_schedule(self, scope: AccessScope, schedule_id: uuid.UUID, for_update: bool = False) -> Optional[MaintenanceSchedule]:
        stmt = select(MaintenanceSchedule).where(MaintenanceSchedule.id == schedule_id, *_scoped(MaintenanceSchedule, scope))
        if for_update:
            stmt = stmt.with_for_update(of=MaintenanceSchedule)
        return self.db.scalars(stmt.execution_options(populate_existing=True)).first()

    def schedule_for(self, device_id: uuid.UUID, type_id: uuid.UUID) -> Optional[MaintenanceSchedule]:
        return self.db.scalar(select(MaintenanceSchedule).where(MaintenanceSchedule.device_id == device_id,
                                                                 MaintenanceSchedule.maintenance_type_id == type_id))

    def list_schedules(self, scope: AccessScope, f: ScheduleFilters, sort: str, descending: bool, page: int,
                       page_size: int) -> Tuple[List[MaintenanceSchedule], int]:
        stmt = select(MaintenanceSchedule).where(*_scoped(MaintenanceSchedule, scope))
        for column, value in ((MaintenanceSchedule.device_id, f.device_id), (MaintenanceSchedule.hospital_id, f.hospital_id),
                              (MaintenanceSchedule.maintenance_type_id, f.maintenance_type_id)):
            if value is not None:
                stmt = stmt.where(column == value)
        if not f.include_inactive:
            stmt = stmt.where(MaintenanceSchedule.is_active.is_(True))
        devices = select(Device.id)
        narrowed = False
        if not f.include_archived_devices:  # Decision 6: archived devices leave due lists
            devices, narrowed = devices.where(Device.deleted_at.is_(None)), True
        if f.department_id:
            devices, narrowed = devices.where(Device.department_id == f.department_id), True
        if narrowed:
            stmt = stmt.where(MaintenanceSchedule.device_id.in_(devices))
        if f.due_before:
            stmt = stmt.where(MaintenanceSchedule.next_due_date <= f.due_before)
        if f.overdue:
            stmt = stmt.where(MaintenanceSchedule.next_due_date < func.current_date())
        column = SCHEDULE_SORT[sort]
        stmt = stmt.order_by(column.desc() if descending else column.asc(), MaintenanceSchedule.id)
        return paginate(self.db, stmt, page, page_size)

    # ---- devices.next_maintenance_due_date ------------------------------------------------------------
    def lock_device(self, device_id: uuid.UUID) -> None:
        """Row lock on the device (only the devices row: no joins), held until commit. Every writer of
        the device's schedules takes it first, so the recompute below always sees the others' result."""
        self.db.execute(select(Device.id).where(Device.id == device_id).with_for_update())

    def earliest_active_due(self, device_id: uuid.UUID) -> Optional[date]:
        return self.db.scalar(select(func.min(MaintenanceSchedule.next_due_date))
                              .where(MaintenanceSchedule.device_id == device_id, MaintenanceSchedule.is_active.is_(True)))
