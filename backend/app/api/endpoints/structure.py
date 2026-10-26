import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import AdminOnly, CurrentUser, Pagination, pagination_params
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import Page
from app.schemas.structure import (
    DepartmentCreate, DepartmentResponse, DepartmentUpdate, HospitalCreate, HospitalResponse, HospitalUpdate,
    LocationCreate, LocationResponse, LocationUpdate, OrganizationResponse, OrganizationUpdate,
)
from app.services.structure_service import StructureService

org_router = APIRouter(prefix="/organizations", tags=["organizations"])
hospital_router = APIRouter(prefix="/hospitals", tags=["hospitals"])
department_router = APIRouter(prefix="/departments", tags=["departments"])
location_router = APIRouter(prefix="/locations", tags=["locations"])


def _page(items, total, p: Pagination, schema) -> Page:
    return Page[schema](items=[schema.model_validate(i, from_attributes=True) for i in items], total=total, page=p.page, page_size=p.page_size)


# ---- organization ---------------------------------------------------------------
@org_router.get("/current", response_model=OrganizationResponse, summary="Your organization")
def get_organization(user: User = CurrentUser, db: Session = Depends(get_db)):
    return OrganizationResponse.model_validate(StructureService(db).get_organization(user.organization_id), from_attributes=True)


@org_router.patch("/current", response_model=OrganizationResponse, summary="Rename your organization")
def rename_organization(body: OrganizationUpdate, admin: User = AdminOnly, db: Session = Depends(get_db)):
    return OrganizationResponse.model_validate(StructureService(db).rename_organization(admin.organization_id, body.name), from_attributes=True)


# ---- hospitals --------------------------------------------------------------------
@hospital_router.post("", response_model=HospitalResponse, status_code=201, summary="Create a hospital")
def create_hospital(body: HospitalCreate, admin: User = AdminOnly, db: Session = Depends(get_db)):
    return HospitalResponse.model_validate(StructureService(db).create_hospital(admin.organization_id, body), from_attributes=True)


@hospital_router.get("", response_model=Page[HospitalResponse], summary="List hospitals")
def list_hospitals(
    p: Pagination = Depends(pagination_params),
    q: Optional[str] = Query(None, max_length=100),
    is_active: Optional[bool] = None,
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    items, total = StructureService(db).repo.list_hospitals(user.organization_id, p.page, p.page_size, q, is_active)
    return _page(items, total, p, HospitalResponse)


@hospital_router.get("/{hospital_id}", response_model=HospitalResponse, summary="Get a hospital")
def get_hospital(hospital_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return HospitalResponse.model_validate(StructureService(db).get_hospital(user.organization_id, hospital_id), from_attributes=True)


@hospital_router.patch("/{hospital_id}", response_model=HospitalResponse, summary="Update / deactivate a hospital")
def update_hospital(hospital_id: uuid.UUID, body: HospitalUpdate, admin: User = AdminOnly, db: Session = Depends(get_db)):
    return HospitalResponse.model_validate(StructureService(db).update_hospital(admin.organization_id, hospital_id, body), from_attributes=True)


# ---- departments -----------------------------------------------------------------------
@department_router.post("", response_model=DepartmentResponse, status_code=201, summary="Create a department")
def create_department(body: DepartmentCreate, admin: User = AdminOnly, db: Session = Depends(get_db)):
    return DepartmentResponse.model_validate(StructureService(db).create_department(admin.organization_id, body), from_attributes=True)


@department_router.get("", response_model=Page[DepartmentResponse], summary="List departments")
def list_departments(
    p: Pagination = Depends(pagination_params),
    hospital_id: Optional[uuid.UUID] = None,
    q: Optional[str] = Query(None, max_length=100),
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    items, total = StructureService(db).repo.list_departments(user.organization_id, p.page, p.page_size, hospital_id, q)
    return _page(items, total, p, DepartmentResponse)


@department_router.get("/{department_id}", response_model=DepartmentResponse, summary="Get a department")
def get_department(department_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return DepartmentResponse.model_validate(StructureService(db).get_department(user.organization_id, department_id), from_attributes=True)


@department_router.patch("/{department_id}", response_model=DepartmentResponse, summary="Rename a department")
def update_department(department_id: uuid.UUID, body: DepartmentUpdate, admin: User = AdminOnly, db: Session = Depends(get_db)):
    return DepartmentResponse.model_validate(StructureService(db).update_department(admin.organization_id, department_id, body), from_attributes=True)


@department_router.delete("/{department_id}", status_code=204, summary="Delete a department (409 while devices use it)")
def delete_department(department_id: uuid.UUID, admin: User = AdminOnly, db: Session = Depends(get_db)):
    StructureService(db).delete_department(admin.organization_id, department_id)
    return Response(status_code=204)


# ---- locations -----------------------------------------------------------------------------
def _location_response(loc) -> LocationResponse:
    return LocationResponse(id=loc.id, hospital_id=loc.hospital_id, building=loc.building, floor=loc.floor, room=loc.room, label=loc.label)


@location_router.post("", response_model=LocationResponse, status_code=201, summary="Create a location")
def create_location(body: LocationCreate, admin: User = AdminOnly, db: Session = Depends(get_db)):
    return _location_response(StructureService(db).create_location(admin.organization_id, body))


@location_router.get("", response_model=Page[LocationResponse], summary="List locations")
def list_locations(
    p: Pagination = Depends(pagination_params),
    hospital_id: Optional[uuid.UUID] = None,
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    items, total = StructureService(db).repo.list_locations(user.organization_id, p.page, p.page_size, hospital_id)
    return Page[LocationResponse](items=[_location_response(i) for i in items], total=total, page=p.page, page_size=p.page_size)


@location_router.get("/{location_id}", response_model=LocationResponse, summary="Get a location")
def get_location(location_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return _location_response(StructureService(db).get_location(user.organization_id, location_id))


@location_router.patch("/{location_id}", response_model=LocationResponse, summary="Update a location")
def update_location(location_id: uuid.UUID, body: LocationUpdate, admin: User = AdminOnly, db: Session = Depends(get_db)):
    return _location_response(StructureService(db).update_location(admin.organization_id, location_id, body))


@location_router.delete("/{location_id}", status_code=204, summary="Delete a location (devices are detached, not deleted)")
def delete_location(location_id: uuid.UUID, admin: User = AdminOnly, db: Session = Depends(get_db)):
    StructureService(db).delete_location(admin.organization_id, location_id)
    return Response(status_code=204)
