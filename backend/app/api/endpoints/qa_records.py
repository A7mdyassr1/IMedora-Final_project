"""QA records (B6 CP2): inspections, calibrations and compliance checks.

Read: technicians, biomedical engineers (own hospital) and administrators (organization).
Write (create, update): biomedical engineers (own hospital) and administrators only.
Department users: 403 on every endpoint. A role that may not perform an operation gets 403 before
any lookup; ids outside the caller's scope are 404. There is no delete: QA records are history.
"""
import uuid
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Pagination, pagination_params
from app.core.access import scope_for
from app.core.database import get_db
from app.core.enums import QARecordType, QAStatus
from app.models.user import User
from app.repositories.qa_repository import DueFilters, QAFilters
from app.schemas.common import Page
from app.schemas.qa import (
    QADueItem, QADueList, QARecordCreate, QARecordResponse, QARecordUpdate, QASummaryResponse,
)
from app.services.qa_service import QAService

router = APIRouter(tags=["quality assurance"])


def _page(items, total, p: Pagination) -> Page[QARecordResponse]:
    return Page[QARecordResponse](items=[QARecordResponse.build(r) for r in items], total=total,
                                  page=p.page, page_size=p.page_size)


@router.post(
    "/qa-records", response_model=QARecordResponse, status_code=201, summary="Record a QA check",
    description=(
        "Biomedical engineers (devices of their hospital) and administrators (organization). `record_type`: "
        "inspection, calibration or compliance. `status` defaults to `pending`; a `pass` or `fail` result is final. "
        "The organization, hospital and performer are set by the server. `performed_at` defaults to now, never in "
        "the future; `next_due_date` must be on or after the date of the check (422). Archived devices and inactive "
        "hospitals are refused (400). A failed check does not create a ticket or change the device's status."
    ),
)
def create_record(body: QARecordCreate, user: User = CurrentUser, db: Session = Depends(get_db)):
    return QARecordResponse.build(QAService(db).create(scope_for(user), body))


@router.get("/qa-records", response_model=Page[QARecordResponse], summary="List QA records")
def list_records(
    p: Pagination = Depends(pagination_params),
    device_id: Optional[uuid.UUID] = None,
    hospital_id: Optional[uuid.UUID] = None,
    record_type: Optional[QARecordType] = None,
    status: Optional[QAStatus] = None,
    performed_by: Optional[uuid.UUID] = None,
    performed_from: Optional[datetime] = Query(None, description="Inclusive; ISO 8601, UTC if no offset"),
    performed_to: Optional[datetime] = Query(None, description="Exclusive; ISO 8601, UTC if no offset"),
    due_after: Optional[date] = Query(None, description="next_due_date on or after this date"),
    due_before: Optional[date] = Query(None, description="next_due_date on or before this date"),
    sort: Literal["performed_at", "next_due_date", "created_at"] = "performed_at",
    order: Literal["asc", "desc"] = "desc",
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    f = QAFilters(device_id=device_id, hospital_id=hospital_id, record_type=record_type, status=status,
                  performed_by=performed_by, performed_from=performed_from, performed_to=performed_to,
                  due_after=due_after, due_before=due_before)
    items, total = QAService(db).list(scope_for(user), f, sort, order == "desc", p.page, p.page_size)
    return _page(items, total, p)


# CP3. Registered before /qa-records/{record_id} so "summary" / "due" are never parsed as ids.
@router.get(
    "/qa-records/summary", response_model=QASummaryResponse, summary="QA records per status and type",
    description="All QA records in your scope. Archived devices only for administrators with `include_archived=true`.",
)
def qa_summary(hospital_id: Optional[uuid.UUID] = None, include_archived: bool = False, user: User = CurrentUser,
               db: Session = Depends(get_db)):
    return QAService(db).summary(scope_for(user), hospital_id, include_archived)


@router.get(
    "/qa-records/due", response_model=QADueList, summary="QA checks that are due or overdue",
    description=(
        "For each device and record type only the LATEST record counts (an older, superseded record is never due). "
        "Its `next_due_date` decides: `overdue` (before today) or `upcoming` (today to today + `within_days`). "
        "Today is the database's date. Records without a next due date are not listed. Soonest first. "
        "Archived devices only for administrators with `include_archived=true`."
    ),
)
def qa_due(
    p: Pagination = Depends(pagination_params),
    within_days: int = Query(30, ge=0, le=365, description="Upcoming window in days (0-365)."),
    include_overdue: bool = Query(True, description="Also list checks whose due date has passed."),
    hospital_id: Optional[uuid.UUID] = None,
    record_type: Optional[QARecordType] = None,
    device_id: Optional[uuid.UUID] = None,
    include_archived: bool = False,
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    f = DueFilters(within_days=within_days, include_overdue=include_overdue, hospital_id=hospital_id,
                   record_type=record_type, device_id=device_id, include_archived=include_archived)
    items, total, today = QAService(db).due(scope_for(user), f, p.page, p.page_size)
    return QADueList(items=[QADueItem.build_due(r, today) for r in items], total=total, page=p.page,
                     page_size=p.page_size, today=today, within_days=within_days, include_overdue=include_overdue)


@router.get("/qa-records/{record_id}", response_model=QARecordResponse, summary="Get a QA record")
def get_record(record_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return QARecordResponse.build(QAService(db).get(scope_for(user), record_id))


@router.patch(
    "/qa-records/{record_id}", response_model=QARecordResponse, summary="Record a QA result or correct a QA record",
    description=(
        "Biomedical engineers (own hospital) and administrators. `status`: only `pending` -> `pass` or `fail` "
        "(otherwise 409 `invalid_qa_status_transition`; a final result cannot change). `findings`, `performed_at` "
        "and `next_due_date` can be corrected, also on finalized records (`null` clears findings / next_due_date). "
        "The device, record type, organization, hospital and performer cannot change (422). Audited."
    ),
)
def update_record(record_id: uuid.UUID, body: QARecordUpdate, user: User = CurrentUser, db: Session = Depends(get_db)):
    return QARecordResponse.build(QAService(db).update(scope_for(user), record_id, body))


@router.get("/devices/{device_id}/qa-records", response_model=Page[QARecordResponse],
            summary="A device's QA records (newest first)")
def device_records(device_id: uuid.UUID, p: Pagination = Depends(pagination_params),
                   record_type: Optional[QARecordType] = None, user: User = CurrentUser, db: Session = Depends(get_db)):
    items, total = QAService(db).for_device(scope_for(user), device_id, QAFilters(record_type=record_type),
                                            p.page, p.page_size)
    return _page(items, total, p)
