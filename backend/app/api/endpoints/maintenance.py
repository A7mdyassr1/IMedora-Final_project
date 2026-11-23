"""Maintenance management (B4 CP3): types, records, schedules.

Staff only (technicians, biomedical engineers, administrators); department users get 403 - they
see the work done on their own tickets through the ticket timeline. Records and schedules outside
the caller's hospital (organization for admins) are 404.
"""
import uuid
from datetime import date, datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AdminOnly, CurrentUser, Pagination, pagination_params
from app.core.access import scope_for
from app.core.database import get_db
from app.models.user import User
from app.repositories.maintenance_repository import RecordFilters, ScheduleFilters
from app.schemas.common import Page
from app.schemas.maintenance import (
    MaintenanceRecordCreate, MaintenanceRecordResponse, MaintenanceRecordUpdate, MaintenanceScheduleCreate,
    MaintenanceScheduleResponse, MaintenanceScheduleUpdate, MaintenanceTypeCreate, MaintenanceTypeResponse,
)
from app.schemas.part import PartUse, PartUseUpdate
from app.services.maintenance_service import MaintenanceService

router = APIRouter(tags=["maintenance"])


def _records(items, total, p: Pagination) -> Page[MaintenanceRecordResponse]:
    return Page[MaintenanceRecordResponse](items=[MaintenanceRecordResponse.build(r) for r in items], total=total,
                                           page=p.page, page_size=p.page_size)


def _schedules(service: MaintenanceService, items, total, p: Pagination) -> Page[MaintenanceScheduleResponse]:
    today = service.today()
    return Page[MaintenanceScheduleResponse](items=[MaintenanceScheduleResponse.build(s, today) for s in items],
                                             total=total, page=p.page, page_size=p.page_size)


# ---- types ----------------------------------------------------------------------------------------
@router.get("/maintenance-types", response_model=List[MaintenanceTypeResponse], summary="List maintenance types")
def list_types(user: User = CurrentUser, db: Session = Depends(get_db)):
    return MaintenanceService(db).list_types(scope_for(user))


@router.post(
    "/maintenance-types", response_model=MaintenanceTypeResponse, status_code=201,
    summary="Create a maintenance type (administrators)",
    description="Global reference data (like the device catalog). Names are trimmed and lower-cased, e.g. `calibration`.",
)
def create_type(body: MaintenanceTypeCreate, user: User = AdminOnly, db: Session = Depends(get_db)):
    return MaintenanceService(db).create_type(scope_for(user), body.name)


# ---- records --------------------------------------------------------------------------------------
@router.post(
    "/maintenance-records", response_model=MaintenanceRecordResponse, status_code=201, summary="Record maintenance work",
    description=(
        "Technicians, biomedical engineers and administrators, on devices of their hospital (admins: organization). "
        "`ticket_id`: corrective work on that ticket (same device; not closed, cancelled or deleted; technicians must "
        "be assigned to it) - this is what allows the ticket to be resolved. `schedule_id`: preventive work for that "
        "active schedule (same device and type) - it moves the schedule's next due date to work date + frequency and "
        "updates the device's next maintenance date. Archived devices and inactive hospitals are refused."
    ),
)
def create_record(body: MaintenanceRecordCreate, user: User = CurrentUser, db: Session = Depends(get_db)):
    return MaintenanceRecordResponse.build(MaintenanceService(db).create_record(scope_for(user), body))


@router.get("/maintenance-records", response_model=Page[MaintenanceRecordResponse], summary="List maintenance records")
def list_records(
    p: Pagination = Depends(pagination_params),
    device_id: Optional[uuid.UUID] = None,
    hospital_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = Query(None, description="The device's department"),
    maintenance_type_id: Optional[uuid.UUID] = None,
    performed_by: Optional[uuid.UUID] = None,
    ticket_id: Optional[uuid.UUID] = None,
    schedule_id: Optional[uuid.UUID] = None,
    performed_from: Optional[datetime] = Query(None, description="Inclusive; ISO 8601, UTC if no offset"),
    performed_to: Optional[datetime] = Query(None, description="Exclusive; ISO 8601, UTC if no offset"),
    sort: Literal["performed_at", "created_at"] = "performed_at",
    order: Literal["asc", "desc"] = "desc",
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    f = RecordFilters(device_id=device_id, hospital_id=hospital_id, department_id=department_id,
                      maintenance_type_id=maintenance_type_id, performed_by=performed_by, ticket_id=ticket_id,
                      schedule_id=schedule_id, performed_from=performed_from, performed_to=performed_to)
    items, total = MaintenanceService(db).list_records(scope_for(user), f, sort, order == "desc", p.page, p.page_size)
    return _records(items, total, p)


@router.get("/maintenance-records/{record_id}", response_model=MaintenanceRecordResponse, summary="Get a maintenance record")
def get_record(record_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return MaintenanceRecordResponse.build(MaintenanceService(db).get_record(scope_for(user), record_id))


@router.patch(
    "/maintenance-records/{record_id}", response_model=MaintenanceRecordResponse, summary="Correct a maintenance record",
    description="Engineers (own hospital) and administrators. Description, and the work date unless the record belongs to a schedule. Records are never deleted.",
)
def update_record(record_id: uuid.UUID, body: MaintenanceRecordUpdate, user: User = CurrentUser, db: Session = Depends(get_db)):
    return MaintenanceRecordResponse.build(MaintenanceService(db).update_record(scope_for(user), record_id, body))


# ---- parts used on a record (B5 CP2) -----------------------------------------------------------------
@router.post(
    "/maintenance-records/{record_id}/parts", response_model=MaintenanceRecordResponse, status_code=201,
    summary="Add a spare part used in this work",
    description="The technician who did the work, the hospital's engineers and administrators. The quantity is taken "
                "from the stock of the device's hospital: 409 `part_not_stocked` if the hospital does not stock the "
                "part, 409 `insufficient_stock` if not enough is on hand.",
)
def add_record_part(record_id: uuid.UUID, body: PartUse, user: User = CurrentUser, db: Session = Depends(get_db)):
    return MaintenanceRecordResponse.build(MaintenanceService(db).add_part(scope_for(user), record_id, body))


@router.patch(
    "/maintenance-records/{record_id}/parts/{part_id}", response_model=MaintenanceRecordResponse,
    summary="Correct the quantity of a part used (engineers, administrators)",
    description="The difference is taken from (or given back to) the hospital's stock.",
)
def change_record_part(record_id: uuid.UUID, part_id: uuid.UUID, body: PartUseUpdate, user: User = CurrentUser,
                       db: Session = Depends(get_db)):
    return MaintenanceRecordResponse.build(
        MaintenanceService(db).change_part(scope_for(user), record_id, part_id, body.quantity))


@router.delete(
    "/maintenance-records/{record_id}/parts/{part_id}", response_model=MaintenanceRecordResponse,
    summary="Remove a part recorded by mistake (engineers, administrators)",
    description="Its quantity goes back to the hospital's stock. The change is kept in the stock history and audit log.",
)
def remove_record_part(record_id: uuid.UUID, part_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return MaintenanceRecordResponse.build(MaintenanceService(db).remove_part(scope_for(user), record_id, part_id))


@router.get("/devices/{device_id}/maintenance-records", response_model=Page[MaintenanceRecordResponse],
            summary="A device's maintenance history (newest first)")
def device_records(device_id: uuid.UUID, p: Pagination = Depends(pagination_params),
                   maintenance_type_id: Optional[uuid.UUID] = None, user: User = CurrentUser, db: Session = Depends(get_db)):
    items, total = MaintenanceService(db).device_records(scope_for(user), device_id,
                                                         RecordFilters(maintenance_type_id=maintenance_type_id),
                                                         "performed_at", True, p.page, p.page_size)
    return _records(items, total, p)


# ---- schedules ------------------------------------------------------------------------------------
@router.post(
    "/maintenance-schedules", response_model=MaintenanceScheduleResponse, status_code=201,
    summary="Create a maintenance schedule (engineers, administrators)",
    description="One schedule per device and maintenance type. Updates the device's next maintenance date.",
)
def create_schedule(body: MaintenanceScheduleCreate, user: User = CurrentUser, db: Session = Depends(get_db)):
    service = MaintenanceService(db)
    return MaintenanceScheduleResponse.build(service.create_schedule(scope_for(user), body), service.today())


@router.get(
    "/maintenance-schedules", response_model=Page[MaintenanceScheduleResponse], summary="Due / overdue maintenance",
    description="Active schedules of non-archived devices, soonest first by default.",
)
def list_schedules(
    p: Pagination = Depends(pagination_params),
    device_id: Optional[uuid.UUID] = None,
    hospital_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = Query(None, description="The device's department"),
    maintenance_type_id: Optional[uuid.UUID] = None,
    due_before: Optional[date] = Query(None, description="next_due_date on or before this date"),
    overdue: bool = Query(False, description="Only schedules due before today"),
    include_inactive: bool = False,
    sort: Literal["next_due_date", "created_at", "frequency_days"] = "next_due_date",
    order: Literal["asc", "desc"] = "asc",
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    service = MaintenanceService(db)
    f = ScheduleFilters(device_id=device_id, hospital_id=hospital_id, department_id=department_id,
                        maintenance_type_id=maintenance_type_id, due_before=due_before, overdue=overdue,
                        include_inactive=include_inactive)
    items, total = service.list_schedules(scope_for(user), f, sort, order == "desc", p.page, p.page_size)
    return _schedules(service, items, total, p)


@router.get("/maintenance-schedules/{schedule_id}", response_model=MaintenanceScheduleResponse, summary="Get a maintenance schedule")
def get_schedule(schedule_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    service = MaintenanceService(db)
    return MaintenanceScheduleResponse.build(service.get_schedule(scope_for(user), schedule_id), service.today())


@router.patch(
    "/maintenance-schedules/{schedule_id}", response_model=MaintenanceScheduleResponse,
    summary="Change or deactivate a maintenance schedule (engineers, administrators)",
    description="frequency_days, next_due_date, is_active. Schedules are deactivated, never deleted. Updates the device's next maintenance date.",
)
def update_schedule(schedule_id: uuid.UUID, body: MaintenanceScheduleUpdate, user: User = CurrentUser, db: Session = Depends(get_db)):
    service = MaintenanceService(db)
    return MaintenanceScheduleResponse.build(service.update_schedule(scope_for(user), schedule_id, body), service.today())


@router.get("/devices/{device_id}/maintenance-schedules", response_model=Page[MaintenanceScheduleResponse],
            summary="A device's schedules (active and inactive)")
def device_schedules(device_id: uuid.UUID, p: Pagination = Depends(pagination_params), user: User = CurrentUser,
                     db: Session = Depends(get_db)):
    service = MaintenanceService(db)
    items, total = service.device_schedules(scope_for(user), device_id, p.page, p.page_size)
    return _schedules(service, items, total, p)
