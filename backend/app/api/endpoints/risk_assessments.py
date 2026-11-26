"""Risk assessments (B6 CP1).

Read: technicians, biomedical engineers (own hospital) and administrators (organization).
Write (create, correct): biomedical engineers (own hospital) and administrators only.
Department users: 403 on every endpoint. A role that may not perform an operation gets 403 before
any lookup; ids outside the caller's scope are 404. There is no delete: assessments are history.

devices.current_risk_level is maintained by the database from the latest assessment (by
assessed_at); the API only reads it.
"""
import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Pagination, pagination_params
from app.core.access import scope_for
from app.core.database import get_db
from app.core.enums import RiskLevel
from app.models.user import User
from app.repositories.risk_repository import RiskFilters
from app.schemas.common import Page
from app.schemas.risk import RiskAssessmentCreate, RiskAssessmentResponse, RiskAssessmentUpdate, RiskSummaryResponse
from app.services.risk_service import RiskService

router = APIRouter(tags=["risk"])


def _page(items, total, p: Pagination) -> Page[RiskAssessmentResponse]:
    return Page[RiskAssessmentResponse](items=[RiskAssessmentResponse.build(a) for a in items], total=total,
                                        page=p.page, page_size=p.page_size)


@router.post(
    "/risk-assessments", response_model=RiskAssessmentResponse, status_code=201, summary="Record a risk assessment",
    description=(
        "Biomedical engineers (devices of their hospital) and administrators (organization). The organization, "
        "hospital and assessor are set by the server. `assessed_at` defaults to now and may be in the past, never "
        "in the future; a second assessment of the same device at exactly the same time is refused (409 "
        "`duplicate_assessment_time`). The device's `current_risk_level` (in the response) is updated by the "
        "database from the device's latest assessment. Archived devices and inactive hospitals are refused (400)."
    ),
)
def create_assessment(body: RiskAssessmentCreate, user: User = CurrentUser, db: Session = Depends(get_db)):
    return RiskAssessmentResponse.build(RiskService(db).create(scope_for(user), body))


@router.get("/risk-assessments", response_model=Page[RiskAssessmentResponse], summary="List risk assessments")
def list_assessments(
    p: Pagination = Depends(pagination_params),
    device_id: Optional[uuid.UUID] = None,
    hospital_id: Optional[uuid.UUID] = None,
    risk_level: Optional[RiskLevel] = None,
    assessed_by: Optional[uuid.UUID] = None,
    assessed_from: Optional[datetime] = Query(None, description="Inclusive; ISO 8601, UTC if no offset"),
    assessed_to: Optional[datetime] = Query(None, description="Exclusive; ISO 8601, UTC if no offset"),
    sort: Literal["assessed_at", "created_at", "risk_level"] = "assessed_at",
    order: Literal["asc", "desc"] = "desc",
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    f = RiskFilters(device_id=device_id, hospital_id=hospital_id, risk_level=risk_level, assessed_by=assessed_by,
                    assessed_from=assessed_from, assessed_to=assessed_to)
    items, total = RiskService(db).list(scope_for(user), f, sort, order == "desc", p.page, p.page_size)
    return _page(items, total, p)


# CP3. Registered before /risk-assessments/{assessment_id} so "summary" is never parsed as an id.
@router.get(
    "/risk-assessments/summary", response_model=RiskSummaryResponse, summary="Devices per current risk level",
    description=(
        "Technicians, engineers (own hospital) and administrators (organization). Counts devices by the risk level "
        "the database keeps from their latest assessment, plus `unassessed`. Archived devices are left out unless an "
        "administrator sets `include_archived=true` (403 for other roles)."
    ),
)
def risk_summary(hospital_id: Optional[uuid.UUID] = None, include_archived: bool = False, user: User = CurrentUser,
                 db: Session = Depends(get_db)):
    return RiskService(db).summary(scope_for(user), hospital_id, include_archived)


@router.get("/risk-assessments/{assessment_id}", response_model=RiskAssessmentResponse, summary="Get a risk assessment")
def get_assessment(assessment_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return RiskAssessmentResponse.build(RiskService(db).get(scope_for(user), assessment_id))


@router.patch(
    "/risk-assessments/{assessment_id}", response_model=RiskAssessmentResponse, summary="Correct a risk assessment",
    description=(
        "Biomedical engineers (own hospital) and administrators. Only `risk_level`, `notes` (null clears them) and "
        "`assessed_at` can be corrected; the device, organization, hospital and assessor cannot. Every correction is "
        "audited. Assessments of archived devices or inactive hospitals cannot be corrected (400)."
    ),
)
def correct_assessment(assessment_id: uuid.UUID, body: RiskAssessmentUpdate, user: User = CurrentUser,
                       db: Session = Depends(get_db)):
    return RiskAssessmentResponse.build(RiskService(db).update(scope_for(user), assessment_id, body))


@router.get("/devices/{device_id}/risk-assessments", response_model=Page[RiskAssessmentResponse],
            summary="A device's risk assessment history (newest first)")
def device_assessments(device_id: uuid.UUID, p: Pagination = Depends(pagination_params),
                       user: User = CurrentUser, db: Session = Depends(get_db)):
    items, total = RiskService(db).for_device(scope_for(user), device_id, RiskFilters(), p.page, p.page_size)
    return _page(items, total, p)
