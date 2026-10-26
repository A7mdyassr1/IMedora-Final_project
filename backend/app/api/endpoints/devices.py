import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CanManageAssets, CurrentUser, Pagination, pagination_params
from app.core.database import get_db
from app.core.enums import Criticality, DeviceStatus, RiskLevel
from app.models.user import User
from app.repositories.device_repository import DeviceFilters
from app.schemas.common import Page
from app.schemas.device import DeviceCreate, DeviceResponse, DeviceUpdate
from app.services.device_service import DeviceService

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("", response_model=DeviceResponse, status_code=201, summary="Register a device")
def create_device(body: DeviceCreate, user: User = CanManageAssets, db: Session = Depends(get_db)):
    return DeviceResponse.from_device(DeviceService(db).create(user.organization_id, body))


@router.get("", response_model=Page[DeviceResponse], summary="List / search / filter devices")
def list_devices(
    p: Pagination = Depends(pagination_params),
    hospital_id: Optional[uuid.UUID] = None,
    department_id: Optional[uuid.UUID] = None,
    category_id: Optional[uuid.UUID] = None,
    manufacturer_id: Optional[uuid.UUID] = None,
    model_id: Optional[uuid.UUID] = None,
    status: Optional[DeviceStatus] = None,
    criticality: Optional[Criticality] = None,
    risk_level: Optional[RiskLevel] = None,
    q: Optional[str] = Query(None, max_length=100, description="Search name, device code, serial number or QR identifier"),
    include_archived: bool = False,
    sort: Literal["name", "device_code", "status", "criticality", "created_at", "next_maintenance_due_date"] = "name",
    order: Literal["asc", "desc"] = "asc",
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    filters = DeviceFilters(
        hospital_id=hospital_id, department_id=department_id, category_id=category_id, manufacturer_id=manufacturer_id,
        model_id=model_id, status=status, criticality=criticality, risk_level=risk_level, q=q, include_archived=include_archived,
    )
    items, total = DeviceService(db).list(user.organization_id, filters, sort, order == "desc", p.page, p.page_size)
    return Page[DeviceResponse](items=[DeviceResponse.from_device(d) for d in items], total=total, page=p.page, page_size=p.page_size)


# Declared before /{device_id} on purpose; QR values are matched case-insensitively as a fallback.
@router.get("/qr/{qr_identifier}", response_model=DeviceResponse, summary="Look a device up by its QR identifier")
def get_device_by_qr(qr_identifier: str, user: User = CurrentUser, db: Session = Depends(get_db)):
    return DeviceResponse.from_device(DeviceService(db).get_by_qr(user.organization_id, qr_identifier))


@router.get("/{device_id}", response_model=DeviceResponse, summary="Get a device (archived devices included)")
def get_device(device_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return DeviceResponse.from_device(DeviceService(db).get(user.organization_id, device_id))


@router.patch("/{device_id}", response_model=DeviceResponse, summary="Update a device")
def update_device(device_id: uuid.UUID, body: DeviceUpdate, user: User = CanManageAssets, db: Session = Depends(get_db)):
    return DeviceResponse.from_device(DeviceService(db).update(user.organization_id, device_id, body, user.id))


@router.delete("/{device_id}", response_model=DeviceResponse, summary="Archive (decommission) a device - never a hard delete")
def archive_device(device_id: uuid.UUID, user: User = CanManageAssets, db: Session = Depends(get_db)):
    return DeviceResponse.from_device(DeviceService(db).archive(user.organization_id, device_id, user.id))
