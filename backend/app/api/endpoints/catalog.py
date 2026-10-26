import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import CanManageAssets, CurrentUser, Pagination, pagination_params
from app.core.database import get_db
from app.models.catalog import DeviceCategory, DeviceModel, Manufacturer
from app.models.user import User
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import (
    CategoryCreate, CategoryResponse, CategoryUpdate, DeviceModelCreate, DeviceModelResponse, DeviceModelUpdate,
    ManufacturerCreate, ManufacturerResponse, ManufacturerUpdate,
)
from app.schemas.common import Page
from app.services.catalog_service import CatalogService

# The catalog is shared by every hospital in the database, so writes are limited to
# administrators and biomedical engineers; every authenticated user may read it.
category_router = APIRouter(prefix="/device-categories", tags=["catalog"])
manufacturer_router = APIRouter(prefix="/manufacturers", tags=["catalog"])
model_router = APIRouter(prefix="/device-models", tags=["catalog"])

Q = Query(None, max_length=100, description="Search by name")


def _model_response(m: DeviceModel) -> DeviceModelResponse:
    return DeviceModelResponse(
        id=m.id, name=m.name, manufacturer_id=m.manufacturer_id, manufacturer_name=m.manufacturer.name,
        device_category_id=m.device_category_id, category_name=m.category.name,
    )


def _simple_page(rows, total, p: Pagination, schema) -> Page:
    return Page[schema](items=[schema(id=r.id, name=r.name) for r in rows], total=total, page=p.page, page_size=p.page_size)


# ---- categories ------------------------------------------------------------------------
@category_router.post("", response_model=CategoryResponse, status_code=201, summary="Create a category")
def create_category(body: CategoryCreate, user: User = CanManageAssets, db: Session = Depends(get_db)):
    o = CatalogService(db).create_simple(DeviceCategory, body.name)
    return CategoryResponse(id=o.id, name=o.name)


@category_router.get("", response_model=Page[CategoryResponse], summary="List categories")
def list_categories(p: Pagination = Depends(pagination_params), q: Optional[str] = Q, user: User = CurrentUser, db: Session = Depends(get_db)):
    rows, total = CatalogRepository(db).list(DeviceCategory, p.page, p.page_size, q)
    return _simple_page(rows, total, p, CategoryResponse)


@category_router.get("/{category_id}", response_model=CategoryResponse, summary="Get a category")
def get_category(category_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    o = CatalogService(db).get(DeviceCategory, category_id, "Category")
    return CategoryResponse(id=o.id, name=o.name)


@category_router.patch("/{category_id}", response_model=CategoryResponse, summary="Rename a category")
def rename_category(category_id: uuid.UUID, body: CategoryUpdate, user: User = CanManageAssets, db: Session = Depends(get_db)):
    o = CatalogService(db).rename(DeviceCategory, category_id, body.name, "Category")
    return CategoryResponse(id=o.id, name=o.name)


@category_router.delete("/{category_id}", status_code=204, summary="Delete a category (409 while models use it)")
def delete_category(category_id: uuid.UUID, user: User = CanManageAssets, db: Session = Depends(get_db)):
    CatalogService(db).delete(DeviceCategory, category_id, "Category")
    return Response(status_code=204)


# ---- manufacturers -----------------------------------------------------------------------
@manufacturer_router.post("", response_model=ManufacturerResponse, status_code=201, summary="Create a manufacturer")
def create_manufacturer(body: ManufacturerCreate, user: User = CanManageAssets, db: Session = Depends(get_db)):
    o = CatalogService(db).create_simple(Manufacturer, body.name)
    return ManufacturerResponse(id=o.id, name=o.name)


@manufacturer_router.get("", response_model=Page[ManufacturerResponse], summary="List manufacturers")
def list_manufacturers(p: Pagination = Depends(pagination_params), q: Optional[str] = Q, user: User = CurrentUser, db: Session = Depends(get_db)):
    rows, total = CatalogRepository(db).list(Manufacturer, p.page, p.page_size, q)
    return _simple_page(rows, total, p, ManufacturerResponse)


@manufacturer_router.get("/{manufacturer_id}", response_model=ManufacturerResponse, summary="Get a manufacturer")
def get_manufacturer(manufacturer_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    o = CatalogService(db).get(Manufacturer, manufacturer_id, "Manufacturer")
    return ManufacturerResponse(id=o.id, name=o.name)


@manufacturer_router.patch("/{manufacturer_id}", response_model=ManufacturerResponse, summary="Rename a manufacturer")
def rename_manufacturer(manufacturer_id: uuid.UUID, body: ManufacturerUpdate, user: User = CanManageAssets, db: Session = Depends(get_db)):
    o = CatalogService(db).rename(Manufacturer, manufacturer_id, body.name, "Manufacturer")
    return ManufacturerResponse(id=o.id, name=o.name)


@manufacturer_router.delete("/{manufacturer_id}", status_code=204, summary="Delete a manufacturer (409 while models use it)")
def delete_manufacturer(manufacturer_id: uuid.UUID, user: User = CanManageAssets, db: Session = Depends(get_db)):
    CatalogService(db).delete(Manufacturer, manufacturer_id, "Manufacturer")
    return Response(status_code=204)


# ---- models ---------------------------------------------------------------------------------
@model_router.post("", response_model=DeviceModelResponse, status_code=201, summary="Create a device model")
def create_model(body: DeviceModelCreate, user: User = CanManageAssets, db: Session = Depends(get_db)):
    return _model_response(CatalogService(db).create_model(body.manufacturer_id, body.device_category_id, body.name))


@model_router.get("", response_model=Page[DeviceModelResponse], summary="List device models")
def list_models(
    p: Pagination = Depends(pagination_params),
    q: Optional[str] = Q,
    manufacturer_id: Optional[uuid.UUID] = None,
    category_id: Optional[uuid.UUID] = None,
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    rows, total = CatalogRepository(db).list(
        DeviceModel, p.page, p.page_size, q, manufacturer_id=manufacturer_id, device_category_id=category_id
    )
    return Page[DeviceModelResponse](items=[_model_response(r) for r in rows], total=total, page=p.page, page_size=p.page_size)


@model_router.get("/{model_id}", response_model=DeviceModelResponse, summary="Get a device model")
def get_model(model_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return _model_response(CatalogService(db).get(DeviceModel, model_id, "Device model"))


@model_router.patch("/{model_id}", response_model=DeviceModelResponse, summary="Update a device model")
def update_model(model_id: uuid.UUID, body: DeviceModelUpdate, user: User = CanManageAssets, db: Session = Depends(get_db)):
    return _model_response(CatalogService(db).update_model(model_id, body.model_dump(exclude_unset=True)))


@model_router.delete("/{model_id}", status_code=204, summary="Delete a device model (409 while devices use it)")
def delete_model(model_id: uuid.UUID, user: User = CanManageAssets, db: Session = Depends(get_db)):
    CatalogService(db).delete(DeviceModel, model_id, "Device model")
    return Response(status_code=204)
