"""Maintenance tickets (B4 CP1): report a problem and read tickets.

Visibility (AccessScope.ticket_access): admins the whole organization; engineers and technicians
their hospital plus their own reports; department users only their own reports. Tickets outside
the caller's scope are 404, exactly like tickets that do not exist.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Pagination, pagination_params
from app.core.access import scope_for
from app.core.database import get_db
from app.core.enums import TicketPriority, TicketStatus
from app.models.user import User
from app.repositories.ticket_repository import TicketFilters
from app.schemas.common import Page
from app.schemas.ticket import TicketCreate, TicketDetailResponse, TicketResponse
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
