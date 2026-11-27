"""Dashboard & analytics aggregates (B10). Every query is a GROUP BY / aggregate in PostgreSQL inside the
caller's device scope (B3.1 `scope_conditions`), never a row-by-row loop in Python.

Scope: tickets, maintenance records and schedules are counted through their device (joined), so the
same organization / hospital / department / archive conditions apply to all of them. The optional
`hospital_id` / `department_id` filters only narrow that scope.

Dates: a date filter is turned into a time range at the database's midnight
(`CAST(:date AS timestamptz)` uses the session time zone), so "a day" is the database's day, as for the
QA due-date rule (B6), and the timestamp indexes stay usable.
"""
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import TIMESTAMP, Date, case, cast, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import DeviceStatus, TicketStatus
from app.models.catalog import DeviceCategory, DeviceModel
from app.models.department import Department
from app.models.device import Device
from app.models.hospital import Hospital
from app.models.maintenance import MaintenanceRecord, MaintenanceSchedule, MaintenanceType
from app.models.part import Part, PartInventory
from app.models.qa import QARecord
from app.models.ticket import MaintenanceTicket
from app.repositories.device_repository import scope_conditions
from app.repositories.part_repository import _inventory_scope


# Maintenance types are admin-defined names; "preventive" / "corrective" work is the type of that name,
# case-insensitive (the seeds, the bulk data and the AI package use these names).
PREVENTIVE, CORRECTIVE = "preventive", "corrective"
RESOLVED = (TicketStatus.RESOLVED, TicketStatus.CLOSED)
OPEN = (TicketStatus.OPEN, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_FOR_PARTS)


def type_named(name: str):
    return func.lower(MaintenanceType.name) == name


# Stock at or below its reorder threshold (B5 rule; no threshold = never low).
LOW_STOCK = (PartInventory.reorder_threshold.is_not(None),
             PartInventory.quantity_on_hand <= PartInventory.reorder_threshold)

# date_trunc() fields of the trend intervals. Fixed SQL literals (never user text), so the bucket expression
# is the same in SELECT and GROUP BY; date_trunc on a timestamptz uses the session time zone.
TRUNC = {"day": "'day'", "week": "'week'", "month": "'month'"}


@dataclass
class AnalyticsFilters:
    hospital_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None
    include_archived: bool = False


def device_conditions(scope: AccessScope, f: AnalyticsFilters) -> list:
    """The caller's device scope, narrowed by the filters; archived devices only when asked for (admins,
    checked by the service)."""
    conditions = scope_conditions(scope)
    if f.hospital_id is not None:
        conditions.append(Device.hospital_id == f.hospital_id)
    if f.department_id is not None:
        conditions.append(Device.department_id == f.department_id)
    if not f.include_archived:
        conditions.append(Device.deleted_at.is_(None))
    return conditions


def day_start(d: date):
    """The database's midnight at the start of `d` (session time zone)."""
    return cast(d.isoformat(), TIMESTAMP(timezone=True))


def period_conditions(column, date_from: date, date_to: date) -> list:
    """`column` (timestamptz) falls on a database date in [date_from, date_to]."""
    return [column >= day_start(date_from), column < day_start(date_to + timedelta(days=1))]


class AnalyticsRepository:
    def __init__(self, db: Session):
        self.db = db

    def today(self) -> date:
        return self.db.scalar(select(func.current_date()))

    # ---- devices (CP1) -------------------------------------------------------------------------
    def device_breakdown(self, scope: AccessScope, f: AnalyticsFilters) -> List[Tuple[str, Optional[str], str, int]]:
        """(status, risk level or None, criticality, count): one row per combination present."""
        stmt = (select(Device.status, Device.current_risk_level, Device.criticality, func.count())
                .where(*device_conditions(scope, f))
                .group_by(Device.status, Device.current_risk_level, Device.criticality))
        return [(s.value, r.value if r is not None else None, c.value, n) for s, r, c, n in self.db.execute(stmt)]

    def devices_by_department(self, scope: AccessScope, f: AnalyticsFilters) -> List[Tuple[uuid.UUID, str, int]]:
        stmt = (select(Department.id, Department.name, func.count(Device.id))
                .join(Device, Device.department_id == Department.id)
                .where(*device_conditions(scope, f))
                .group_by(Department.id, Department.name)
                .order_by(func.count(Device.id).desc(), Department.name, Department.id))
        return [tuple(row) for row in self.db.execute(stmt)]

    def devices_by_category(self, scope: AccessScope, f: AnalyticsFilters) -> List[Tuple[uuid.UUID, str, int]]:
        stmt = (select(DeviceCategory.id, DeviceCategory.name, func.count(Device.id))
                .select_from(Device)
                .join(DeviceModel, DeviceModel.id == Device.device_model_id)
                .join(DeviceCategory, DeviceCategory.id == DeviceModel.device_category_id)
                .where(*device_conditions(scope, f))
                .group_by(DeviceCategory.id, DeviceCategory.name)
                .order_by(func.count(Device.id).desc(), DeviceCategory.name, DeviceCategory.id))
        return [tuple(row) for row in self.db.execute(stmt)]

    # ---- maintenance (CP2) -----------------------------------------------------------------------
    def records_by_type(self, scope: AccessScope, f: AnalyticsFilters, start: date,
                        end: date) -> List[Tuple[uuid.UUID, str, int]]:
        """Maintenance records performed in the period, per maintenance type (most first, then name)."""
        n = func.count(MaintenanceRecord.id)
        stmt = (select(MaintenanceType.id, MaintenanceType.name, n)
                .select_from(MaintenanceRecord)
                .join(Device, Device.id == MaintenanceRecord.device_id)
                .join(MaintenanceType, MaintenanceType.id == MaintenanceRecord.maintenance_type_id)
                .where(*device_conditions(scope, f), *period_conditions(MaintenanceRecord.performed_at, start, end))
                .group_by(MaintenanceType.id, MaintenanceType.name)
                .order_by(n.desc(), MaintenanceType.name, MaintenanceType.id))
        return [tuple(row) for row in self.db.execute(stmt)]

    def _preventive_due(self, scope: AccessScope, f: AnalyticsFilters):
        """Evaluated devices (in scope, not decommissioned) with the due date of their ACTIVE preventive
        schedule (NULL = none). One schedule per device and type (uq_schedule_device_type); MIN() only
        guards against two types whose names differ in case."""
        due = (select(MaintenanceSchedule.device_id, func.min(MaintenanceSchedule.next_due_date).label("due"))
               .join(MaintenanceType, MaintenanceType.id == MaintenanceSchedule.maintenance_type_id)
               .where(MaintenanceSchedule.organization_id == scope.organization_id,  # the outer query scopes
                      MaintenanceSchedule.is_active.is_(True), type_named(PREVENTIVE))
               .group_by(MaintenanceSchedule.device_id).subquery())
        return due, [*device_conditions(scope, f), Device.status != DeviceStatus.DECOMMISSIONED]

    def preventive_buckets(self, scope: AccessScope, f: AnalyticsFilters, today: date, due_soon_days: int) -> Dict[str, int]:
        due, conditions = self._preventive_due(scope, f)
        bucket = case((due.c.due.is_(None), "no_schedule"), (due.c.due < today, "overdue"),
                      (due.c.due <= today + timedelta(days=due_soon_days), "due_soon"), else_="on_track")
        stmt = (select(bucket, func.count()).select_from(Device).outerjoin(due, due.c.device_id == Device.id)
                .where(*conditions).group_by(bucket))
        return dict(self.db.execute(stmt).all())

    def preventive_overdue(self, scope: AccessScope, f: AnalyticsFilters, today: date, limit: int) -> list:
        """The most overdue devices first, then by device code."""
        due, conditions = self._preventive_due(scope, f)
        stmt = (select(Device.id, Device.device_code, Device.name, Department.name, Hospital.name, due.c.due)
                .select_from(Device).join(due, due.c.device_id == Device.id)
                .join(Department, Department.id == Device.department_id).join(Hospital, Hospital.id == Device.hospital_id)
                .where(*conditions, due.c.due < today)
                .order_by(due.c.due, Device.device_code, Device.id).limit(limit))
        return [tuple(row) for row in self.db.execute(stmt)]

    def schedules_due(self, scope: AccessScope, f: AnalyticsFilters, today: date, due_soon_days: int) -> Dict[str, int]:
        """Active schedules of every type, of devices in scope that are not decommissioned: overdue (due
        before today) and due soon (today .. today + due_soon_days)."""
        soon = today + timedelta(days=due_soon_days)
        stmt = (select(func.count().filter(MaintenanceSchedule.next_due_date < today),
                       func.count().filter(MaintenanceSchedule.next_due_date.between(today, soon)))
                .select_from(MaintenanceSchedule).join(Device, Device.id == MaintenanceSchedule.device_id)
                .where(*device_conditions(scope, f), Device.status != DeviceStatus.DECOMMISSIONED,
                       MaintenanceSchedule.is_active.is_(True)))
        overdue, due_soon = self.db.execute(stmt).one()
        return {"overdue": overdue, "due_soon": due_soon}

    # ---- tickets (CP2) ---------------------------------------------------------------------------
    def _tickets(self, scope: AccessScope, f: AnalyticsFilters) -> list:
        """Tickets of devices in scope; admin-deleted tickets never count (B4)."""
        return [*device_conditions(scope, f), MaintenanceTicket.deleted_at.is_(None)]

    def tickets_created(self, scope: AccessScope, f: AnalyticsFilters, start: date, end: date) -> list:
        """(status, priority, count) of tickets created in the period."""
        stmt = (select(MaintenanceTicket.status, MaintenanceTicket.priority, func.count())
                .join(Device, Device.id == MaintenanceTicket.device_id)
                .where(*self._tickets(scope, f), *period_conditions(MaintenanceTicket.created_at, start, end))
                .group_by(MaintenanceTicket.status, MaintenanceTicket.priority))
        return [(s.value, p.value, n) for s, p, n in self.db.execute(stmt)]

    def tickets_by_department(self, scope: AccessScope, f: AnalyticsFilters, start: date,
                              end: date) -> List[Tuple[uuid.UUID, str, int]]:
        """Tickets created in the period, per department of their device (most first, then name)."""
        n = func.count(MaintenanceTicket.id)
        stmt = (select(Department.id, Department.name, n)
                .select_from(MaintenanceTicket)
                .join(Device, Device.id == MaintenanceTicket.device_id)
                .join(Department, Department.id == Device.department_id)
                .where(*self._tickets(scope, f), *period_conditions(MaintenanceTicket.created_at, start, end))
                .group_by(Department.id, Department.name)
                .order_by(n.desc(), Department.name, Department.id))
        return [tuple(row) for row in self.db.execute(stmt)]

    def tickets_open(self, scope: AccessScope, f: AnalyticsFilters) -> List[Tuple[str, str, int]]:
        """(status, priority, count) of the tickets open right now (open, assigned, in progress, waiting for
        parts), whatever their creation date."""
        stmt = (select(MaintenanceTicket.status, MaintenanceTicket.priority, func.count())
                .join(Device, Device.id == MaintenanceTicket.device_id)
                .where(*self._tickets(scope, f), MaintenanceTicket.status.in_(OPEN))
                .group_by(MaintenanceTicket.status, MaintenanceTicket.priority))
        return [(s.value, p.value, n) for s, p, n in self.db.execute(stmt)]

    def resolution(self, scope: AccessScope, f: AnalyticsFilters, start: date, end: date) -> Tuple[int, Optional[tuple]]:
        """Resolved / closed tickets RESOLVED in the period (the AI rule buckets MTTR by resolution date):
        their number and (mean, median, min, max) hours from report to resolution."""
        hours = func.extract("epoch", MaintenanceTicket.resolved_at - MaintenanceTicket.created_at) / 3600
        stmt = (select(func.count(), func.avg(hours), func.percentile_cont(0.5).within_group(hours),
                       func.min(hours), func.max(hours))
                .join(Device, Device.id == MaintenanceTicket.device_id)
                .where(*self._tickets(scope, f), MaintenanceTicket.status.in_(RESOLVED),
                       MaintenanceTicket.resolved_at.is_not(None),
                       *period_conditions(MaintenanceTicket.resolved_at, start, end)))
        n, avg, med, lo, hi = self.db.execute(stmt).one()
        return n, ((float(avg), float(med), float(lo), float(hi)) if n else None)

    # ---- problem devices (CP2) -------------------------------------------------------------------
    def problem_devices(self, scope: AccessScope, f: AnalyticsFilters, start: date, end: date, min_tickets: int,
                        limit: int) -> Tuple[int, list]:
        """Devices ranked by failure tickets created in the period (not cancelled), then corrective records
        performed in the period, then device code. Only devices with at least `min_tickets` failures (and
        with any problem at all). Returns (number of such devices, the first `limit`)."""
        failures = (select(MaintenanceTicket.device_id.label("device_id"), func.count().label("tickets"),
                           func.max(MaintenanceTicket.created_at).label("last_ticket_at"))
                    .where(MaintenanceTicket.organization_id == scope.organization_id,  # the outer query scopes
                           MaintenanceTicket.deleted_at.is_(None), MaintenanceTicket.status != TicketStatus.CANCELLED,
                           *period_conditions(MaintenanceTicket.created_at, start, end))
                    .group_by(MaintenanceTicket.device_id).subquery())
        corrective = (select(MaintenanceRecord.device_id.label("device_id"), func.count().label("corrective"))
                      .join(MaintenanceType, MaintenanceType.id == MaintenanceRecord.maintenance_type_id)
                      .where(MaintenanceRecord.organization_id == scope.organization_id, type_named(CORRECTIVE),
                             *period_conditions(MaintenanceRecord.performed_at, start, end))
                      .group_by(MaintenanceRecord.device_id).subquery())
        tickets = func.coalesce(failures.c.tickets, 0)
        repairs = func.coalesce(corrective.c.corrective, 0)
        stmt = (select(Device.id, Device.device_code, Device.name, Department.name, Hospital.name, tickets, repairs,
                       failures.c.last_ticket_at, func.count().over())
                .select_from(Device)
                .outerjoin(failures, failures.c.device_id == Device.id)
                .outerjoin(corrective, corrective.c.device_id == Device.id)
                .join(Department, Department.id == Device.department_id).join(Hospital, Hospital.id == Device.hospital_id)
                .where(*device_conditions(scope, f), or_(failures.c.device_id.is_not(None), corrective.c.device_id.is_not(None)),
                       tickets >= min_tickets)
                .order_by(tickets.desc(), repairs.desc(), Device.device_code, Device.id).limit(limit))
        rows = [tuple(row) for row in self.db.execute(stmt)]
        total = rows[0][-1] if rows else 0          # count(*) OVER () runs before LIMIT; limit is >= 1
        return total, [row[:-1] for row in rows]

    # ---- inventory (CP3) -------------------------------------------------------------------------
    @staticmethod
    def _stock(scope: AccessScope, hospital_id: Optional[uuid.UUID]) -> list:
        """Stock rows the caller may read (B5 inventory scope: organization; own hospital for non-admins),
        narrowed to one hospital if asked."""
        conditions = _inventory_scope(scope)
        if hospital_id is not None:
            conditions.append(PartInventory.hospital_id == hospital_id)
        return conditions

    def stock_totals(self, scope: AccessScope, hospital_id: Optional[uuid.UUID]) -> Tuple[int, int, int, int, int]:
        """(stock rows, distinct parts, units on hand, low-stock rows, out-of-stock rows)."""
        q = PartInventory.quantity_on_hand
        stmt = (select(func.count(), func.count(func.distinct(PartInventory.part_id)), func.coalesce(func.sum(q), 0),
                       func.count().filter(*LOW_STOCK), func.count().filter(q == 0))
                .where(*self._stock(scope, hospital_id)))
        return tuple(int(v) for v in self.db.execute(stmt).one())

    def low_stock(self, scope: AccessScope, hospital_id: Optional[uuid.UUID], limit: int) -> list:
        """Low-stock rows, emptiest first (then part number, hospital)."""
        stmt = (select(PartInventory.id, Part.id, Part.part_number, Part.name, Part.unit, Hospital.id, Hospital.name,
                       PartInventory.quantity_on_hand, PartInventory.reorder_threshold)
                .join(Part, Part.id == PartInventory.part_id).join(Hospital, Hospital.id == PartInventory.hospital_id)
                .where(*self._stock(scope, hospital_id), *LOW_STOCK)
                .order_by(PartInventory.quantity_on_hand, Part.part_number, Hospital.name, PartInventory.id)
                .limit(limit))
        return [tuple(row) for row in self.db.execute(stmt)]

    # ---- trends (CP3) ----------------------------------------------------------------------------
    def trend(self, scope: AccessScope, f: AnalyticsFilters, metric: str, interval: str, start: date,
              end: date) -> Dict[date, Tuple[Optional[float], int]]:
        """One GROUP BY per call: {bucket start (database date): (value, number of tickets / records)} for
        the buckets that have any. Same rules as /tickets and /maintenance: failures by creation date, MTTR
        by resolution date, maintenance by performed date."""
        def bucket(column):
            return cast(func.date_trunc(literal_column(TRUNC[interval]), column), Date)

        if metric == "mttr_hours":
            b = bucket(MaintenanceTicket.resolved_at)
            hours = func.extract("epoch", MaintenanceTicket.resolved_at - MaintenanceTicket.created_at) / 3600
            stmt = (select(b, func.avg(hours), func.count())
                    .join(Device, Device.id == MaintenanceTicket.device_id)
                    .where(*self._tickets(scope, f), MaintenanceTicket.status.in_(RESOLVED),
                           MaintenanceTicket.resolved_at.is_not(None),
                           *period_conditions(MaintenanceTicket.resolved_at, start, end)))
        elif metric == "tickets":
            b = bucket(MaintenanceTicket.created_at)
            stmt = (select(b, func.count(), func.count())
                    .join(Device, Device.id == MaintenanceTicket.device_id)
                    .where(*self._tickets(scope, f), MaintenanceTicket.status != TicketStatus.CANCELLED,
                           *period_conditions(MaintenanceTicket.created_at, start, end)))
        else:
            b = bucket(MaintenanceRecord.performed_at)
            stmt = (select(b, func.count(), func.count())
                    .select_from(MaintenanceRecord)
                    .join(Device, Device.id == MaintenanceRecord.device_id)
                    .where(*device_conditions(scope, f), *period_conditions(MaintenanceRecord.performed_at, start, end)))
            if metric != "total_maintenance":
                stmt = (stmt.join(MaintenanceType, MaintenanceType.id == MaintenanceRecord.maintenance_type_id)
                        .where(type_named(PREVENTIVE if metric == "preventive_maintenance" else CORRECTIVE)))
        return {day: (float(value), n) for day, value, n in self.db.execute(stmt.group_by(b))}

    # ---- QA (CP4) --------------------------------------------------------------------------------
    def qa_by_status(self, scope: AccessScope, f: AnalyticsFilters) -> Dict[str, int]:
        """QA records of devices in scope, by status (every record, as the B6 QA summary counts them; through
        the device, so the department filter applies too)."""
        stmt = (select(QARecord.status, func.count())
                .join(Device, Device.id == QARecord.device_id)
                .where(*device_conditions(scope, f))
                .group_by(QARecord.status))
        return {s.value: n for s, n in self.db.execute(stmt)}
