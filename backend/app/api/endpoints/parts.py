"""Spare parts (B5): the global parts catalog and per-hospital stock.

Staff only (technicians, biomedical engineers, administrators); department users get 403.
Stock rows outside the caller's hospital (organization for admins) are 404.
"""
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Pagination, pagination_params
from app.core.access import scope_for
from app.core.database import get_db
from app.models.user import User
from app.repositories.part_repository import InventoryFilters
from app.schemas.common import Page
from app.schemas.part import (
    InventoryAdjustment, InventoryCreate, InventoryResponse, InventoryUpdate, PartCreate, PartResponse, PartUpdate,
    StockHistory,
)
from app.services.inventory_service import InventoryService

router = APIRouter(tags=["parts"])


# ---- catalog --------------------------------------------------------------------------------------
@router.get("/parts", response_model=Page[PartResponse], summary="List spare parts (catalog)")
def list_parts(p: Pagination = Depends(pagination_params),
               q: Optional[str] = Query(None, max_length=100, description="Name or part number contains"),
               user: User = CurrentUser, db: Session = Depends(get_db)):
    items, total = InventoryService(db).list_parts(scope_for(user), q, p.page, p.page_size)
    return Page[PartResponse](items=[PartResponse.model_validate(i) for i in items], total=total, page=p.page,
                              page_size=p.page_size)


@router.post("/parts", response_model=PartResponse, status_code=201,
             summary="Add a part to the catalog (engineers, administrators)",
             description="Global reference data. `part_number` is unique, stored upper-case.")
def create_part(body: PartCreate, user: User = CurrentUser, db: Session = Depends(get_db)):
    return InventoryService(db).create_part(scope_for(user), body)


@router.get("/parts/{part_id}", response_model=PartResponse, summary="Get a part")
def get_part(part_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return InventoryService(db).get_part(scope_for(user), part_id)


@router.patch("/parts/{part_id}", response_model=PartResponse, summary="Change a part (engineers, administrators)")
def update_part(part_id: uuid.UUID, body: PartUpdate, user: User = CurrentUser, db: Session = Depends(get_db)):
    return InventoryService(db).update_part(scope_for(user), part_id, body)


@router.delete("/parts/{part_id}", status_code=204, summary="Delete an unused part (engineers, administrators)",
               description="Refused (409 `in_use`) while any hospital stocks the part or it was used in maintenance.")
def delete_part(part_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    InventoryService(db).delete_part(scope_for(user), part_id)
    return Response(status_code=204)


# ---- stock ----------------------------------------------------------------------------------------
@router.get("/inventory", response_model=Page[InventoryResponse], summary="Stock levels",
            description="Own hospital (administrators: organization). `low_stock=true`: at or below the reorder threshold.")
def list_inventory(
    p: Pagination = Depends(pagination_params),
    hospital_id: Optional[uuid.UUID] = None,
    part_id: Optional[uuid.UUID] = None,
    low_stock: bool = False,
    q: Optional[str] = Query(None, max_length=100, description="Part name or part number contains"),
    sort: Literal["part_name", "part_number", "quantity_on_hand", "updated_at"] = "part_name",
    order: Literal["asc", "desc"] = "asc",
    user: User = CurrentUser,
    db: Session = Depends(get_db),
):
    f = InventoryFilters(hospital_id=hospital_id, part_id=part_id, low_stock=low_stock, q=q)
    items, total = InventoryService(db).list_inventory(scope_for(user), f, sort, order == "desc", p.page, p.page_size)
    return Page[InventoryResponse](items=[InventoryResponse.build(i) for i in items], total=total, page=p.page,
                                   page_size=p.page_size)


@router.post("/inventory", response_model=InventoryResponse, status_code=201,
             summary="Start stocking a part at a hospital (engineers: own hospital; administrators)",
             description="One stock row per hospital and part. The opening quantity is the first stock movement.")
def create_inventory(body: InventoryCreate, user: User = CurrentUser, db: Session = Depends(get_db)):
    return InventoryResponse.build(InventoryService(db).create_inventory(scope_for(user), body))


@router.get("/inventory/{inventory_id}", response_model=InventoryResponse, summary="Get a stock row")
def get_inventory(inventory_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return InventoryResponse.build(InventoryService(db).get_inventory(scope_for(user), inventory_id))


@router.patch("/inventory/{inventory_id}", response_model=InventoryResponse,
              summary="Change stock settings (reorder threshold)",
              description="The quantity cannot be set here: use POST /inventory/{id}/adjustments.")
def update_inventory(inventory_id: uuid.UUID, body: InventoryUpdate, user: User = CurrentUser,
                     db: Session = Depends(get_db)):
    return InventoryResponse.build(InventoryService(db).update_inventory(scope_for(user), inventory_id, body))


@router.post(
    "/inventory/{inventory_id}/adjustments", response_model=InventoryResponse,
    summary="Restock or correct the quantity on hand (engineers: own hospital; administrators)",
    description="`restock`: stock received (positive change). `correction`: stock count, damage, expiry, loss (either "
                "sign). A reason is required. The quantity can never go below zero (409 `insufficient_stock`).",
)
def adjust_inventory(inventory_id: uuid.UUID, body: InventoryAdjustment, user: User = CurrentUser,
                     db: Session = Depends(get_db)):
    return InventoryResponse.build(InventoryService(db).adjust(scope_for(user), inventory_id, body))


@router.get("/inventory/{inventory_id}/movements", response_model=StockHistory, summary="Stock history of a stock row",
            description="Every quantity change made through the API, oldest first: opening stock, restocks, "
                        "corrections, and parts used on (or returned from) maintenance records.")
def inventory_movements(inventory_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    inv, movements, untracked = InventoryService(db).history(scope_for(user), inventory_id)
    return StockHistory(inventory=InventoryResponse.build(inv), movements=movements, untracked_change=untracked)
