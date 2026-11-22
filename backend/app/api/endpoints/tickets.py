"""Maintenance tickets (B4): report a problem and read tickets (CP1); workflow - status,
assignments, priority, soft delete (CP2).

Visibility (AccessScope.ticket_access): admins the whole organization; engineers and technicians
their hospital plus their own reports; department users only their own reports. Tickets outside
the caller's scope are 404, exactly like tickets that do not exist.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import AdminOnly, CurrentUser, Pagination, pagination_params
from app.core.access import scope_for
from app.core.database import get_db
from app.core.enums import TicketPriority, TicketStatus
from app.models.user import User
from app.repositories.ticket_repository import TicketFilters
from app.schemas.common import Page
from app.schemas.ticket import (
    AssignmentCreate, TicketCreate, TicketDetailResponse, TicketResponse, TicketStatusUpdate, TicketUpdate,
)
from app.services.ticket_service import TicketService

router = APIRouter(tags=["tickets"])

SortField = Literal["created_at", "updated_at", "priority", "status"]


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Query datetimes without a time zone are taken as UTC (never as the server's local time)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _filters(status, priority, hospital_id, department_id, device_id, reported_by, assigned_to, created_from,
             created_to, q, include_deleted, scope) -> TicketFilters:
    return TicketFilters(
        status=list(status or []), priority=list(priority or []), hospital_id=hospital_id,
        department_id=department_id, device_id=device_id, reported_by=reported_by,
        assigned_to=scope.user_id if assigned_to == "me" else (uuid.UUID(assigned_to) if assigned_to else None),
        created_from=_aware(created_from), created_to=_aware(created_to), q=q, include_deleted=include_deleted,
    )


def _page(items, total, p: Pagination, scope) -> Page[TicketResponse]:
    return Page[TicketResponse](items=[TicketResponse.build(t, scope) for t in items], total=total,
                                page=p.page, page_size=p.page_size)


ASSIGNED_TO_PATTERN = r"^(me|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"


@router.post(
    "/tickets", response_model=TicketDetailResponse, status_code=201, summary="Report a problem (create a ticket)",
    description=(
        "Any signed-in user may report a problem on a device they can reach: their own hospital "
        "(department users: any department of it, as with QR scanning), or the whole organization "
        "for administrators. The category is one of the six mobile labels and is stored as a prefix "
        "of the description. Organization, hospital, reporter and status (`open`) are set by the "
        "server. Archived devices and inactive hospitals are refused (400); a department user "
        "without a department gets 403 `department_required`; an unknown or out-of-scope device is 404."
    ),
)
def create_ticket(body: TicketCreate, user: User = CurrentUser, db: Session = Depends(get_db)):
    scope = scope_for(user)
    service = TicketService(db)
    ticket = service.create(scope, body)
    return TicketDetailResponse.build_detail(ticket, scope, service.timeline(scope, ticket))


@router.get("/tickets", response_model=Page[TicketResponse], summary="List / search / filter tickets")
def list_tickets(
    p: Pagination = Depends(pagination_params),
    status: Optional[List[TicketStatus]] = Query(None, description="Repeat to match several statuses"),
    priority: Optional[List[TicketPriority]] = Query(None, description="Repeat to match several priorities"),
    hospital_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = Query(None, description="The device's department"),
    device_id: Optional[uuid.UUID] = None,
    reported_by: Optional[uuid.UUID] = None,
    assigned_to: Optional[str] = Query(None, pattern=ASSIGNED_TO_PATTERN, description="`me` or a user id (active assignment)"),
    created_from: Optional[datetime] = Query(None, description="Inclusive; ISO 8601, UTC if no offset"),
    created_to: Optional[datetime] = Query(None, description="Exclusive; ISO 8601, UTC if no offset"),
    q: Optional[str] = Query(None, max_length=100, description="Search the description, device name and device code"),
    include_deleted: bool = Query(False, description="Administrators only"),
    sort: SortField = "created_at",
    order: Literal["asc", "desc"] = "desc",
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    scope = scope_for(user)
    f = _filters(status, priority, hospital_id, department_id, device_id, reported_by, assigned_to, created_from,
                 created_to, q, include_deleted, scope)
    items, total = TicketService(db).list(scope, f, sort, order == "desc", p.page, p.page_size)
    return _page(items, total, p, scope)


# Declared before /tickets/{ticket_id} on purpose.
@router.get("/tickets/mine", response_model=Page[TicketResponse], summary="Tickets I reported (newest first)")
def my_tickets(p: Pagination = Depends(pagination_params), user: User = CurrentUser, db: Session = Depends(get_db)):
    scope = scope_for(user)
    items, total = TicketService(db).mine(scope, p.page, p.page_size)
    return _page(items, total, p, scope)


@router.get("/tickets/{ticket_id}", response_model=TicketDetailResponse, summary="Get a ticket with its timeline")
def get_ticket(ticket_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    scope = scope_for(user)
    service = TicketService(db)
    ticket = service.get(scope, ticket_id)
    return TicketDetailResponse.build_detail(ticket, scope, service.timeline(scope, ticket))


@router.get(
    "/devices/{device_id}/tickets", response_model=Page[TicketResponse], summary="A device's tickets",
    description=(
        "The device must be in the caller's device scope (department users: their own department). "
        "Department users then see only the tickets they reported on it."
    ),
)
def device_tickets(
    device_id: uuid.UUID,
    p: Pagination = Depends(pagination_params),
    status: Optional[List[TicketStatus]] = Query(None),
    sort: SortField = "created_at",
    order: Literal["asc", "desc"] = "desc",
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    scope = scope_for(user)
    items, total = TicketService(db).for_device(scope, device_id, TicketFilters(status=list(status or [])),
                                                sort, order == "desc", p.page, p.page_size)
    return _page(items, total, p, scope)


# ---- workflow (CP2) ----------------------------------------------------------------------------
def _detail(service: TicketService, ticket, scope) -> TicketDetailResponse:
    return TicketDetailResponse.build_detail(ticket, scope, service.timeline(scope, ticket))


@router.patch(
    "/tickets/{ticket_id}/status", response_model=TicketDetailResponse, summary="Change a ticket's status",
    description=(
        "Allowed changes: open -> cancelled; assigned -> in_progress | cancelled; in_progress -> "
        "waiting_for_parts | resolved | cancelled; waiting_for_parts -> in_progress | resolved | cancelled; "
        "resolved -> closed | in_progress (reopen). `open` and `assigned` follow the assignments. "
        "Work statuses: an active assignee, an engineer of the hospital or an admin. Close and reopen: "
        "engineers and admins. Cancel: engineers and admins, or the reporter while the ticket is open "
        "and unassigned. Resolving needs a linked maintenance record (409 `maintenance_record_required`). "
        "Not in the table: 409 `invalid_status_transition`."
    ),
)
def change_status(ticket_id: uuid.UUID, body: TicketStatusUpdate, user: User = CurrentUser, db: Session = Depends(get_db)):
    scope = scope_for(user)
    service = TicketService(db)
    return _detail(service, service.change_status(scope, ticket_id, body.status), scope)


@router.post(
    "/tickets/{ticket_id}/assignments", response_model=TicketDetailResponse, status_code=201,
    summary="Assign a technician or engineer",
    description=(
        "Engineers (own hospital) and admins assign any active technician or biomedical engineer of "
        "the ticket's hospital; technicians can only take an open or assigned ticket themselves. The "
        "first assignment moves an open ticket to `assigned`."
    ),
)
def assign(ticket_id: uuid.UUID, body: AssignmentCreate, user: User = CurrentUser, db: Session = Depends(get_db)):
    scope = scope_for(user)
    service = TicketService(db)
    return _detail(service, service.assign(scope, ticket_id, body.user_id), scope)


@router.delete(
    "/tickets/{ticket_id}/assignments/{user_id}", response_model=TicketDetailResponse, summary="Unassign",
    description=(
        "Ends an active assignment (the row is kept as history). Removing the last assignee moves an "
        "`assigned` ticket back to `open`; a ticket in progress must keep at least one assignee."
    ),
)
def unassign(ticket_id: uuid.UUID, user_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    scope = scope_for(user)
    service = TicketService(db)
    return _detail(service, service.unassign(scope, ticket_id, user_id), scope)


@router.patch("/tickets/{ticket_id}", response_model=TicketDetailResponse, summary="Change a ticket's priority")
def update_ticket(ticket_id: uuid.UUID, body: TicketUpdate, user: User = CurrentUser, db: Session = Depends(get_db)):
    scope = scope_for(user)
    service = TicketService(db)
    return _detail(service, service.change_priority(scope, ticket_id, body.priority), scope)


@router.delete(
    "/tickets/{ticket_id}", status_code=204, summary="Delete a ticket (administrators; soft delete)",
    description="For mistaken or duplicate tickets. The ticket stays readable for administrators. Idempotent.",
)
def delete_ticket(ticket_id: uuid.UUID, user: User = AdminOnly, db: Session = Depends(get_db)):
    TicketService(db).soft_delete(scope_for(user), ticket_id)
    return Response(status_code=204)
