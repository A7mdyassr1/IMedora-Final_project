"""A device's history (B6 CP4): GET /devices/{id}/history.

One time-ordered feed (newest first) of the device's tickets, maintenance records, risk assessments
and QA records, each limited by the caller's role and scope (see app/services/device_history.py).
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Pagination, pagination_params
from app.core.access import scope_for
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import Page
from app.schemas.history import DeviceHistoryEntry
from app.services.device_history import DeviceHistoryService, parse_types

router = APIRouter(tags=["devices"])


@router.get(
    "/devices/{device_id}/history", response_model=Page[DeviceHistoryEntry], summary="A device's history",
    description=(
        "Tickets reported and resolved, maintenance records, risk assessments and QA records of one device, newest "
        "first (equal times: by entry type name, alphabetically, then id). Archived devices included.\n\n"
        "- Administrators (organization), engineers and technicians (own hospital): every entry type; tickets as in "
        "`GET /devices/{id}/tickets`.\n"
        "- Department users (devices of their own department): only `ticket_reported` / `ticket_resolved` entries of "
        "tickets they reported, staff shown as roles. Asking for another type: 403.\n\n"
        "Closed and cancelled tickets have no time of their own: they show as the ticket's current status."
    ),
)
def device_history(
    device_id: uuid.UUID,
    p: Pagination = Depends(pagination_params),
    types: Optional[str] = Query(None, description="Comma-separated subset of ticket_reported, ticket_resolved, "
                                                   "maintenance_record, risk_assessment, qa_record"),
    at_from: Optional[datetime] = Query(None, alias="from", description="Inclusive; ISO 8601, UTC if no offset"),
    at_to: Optional[datetime] = Query(None, alias="to", description="Inclusive; ISO 8601, UTC if no offset"),
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    items, total = DeviceHistoryService(db).history(scope_for(user), device_id, parse_types(types), at_from, at_to,
                                                    p.page, p.page_size)
    return Page[DeviceHistoryEntry](items=items, total=total, page=p.page, page_size=p.page_size)
