"""Spare parts catalog and hospital stock (B5 CP1).

Who may do what:

    action                                technician     biomedical_engineer   admin          department_user
    ------------------------------------  -------------  --------------------  -------------  ---------------
    read the parts catalog                yes            yes                   yes            403
    create / change / delete a part       -              yes                   yes            403
    read stock, stock history             own hospital   own hospital          organization   403
    create a stock row, change settings,  -              own hospital          organization   403
      restock / correct the quantity

Rules:
- The parts catalog is global reference data, like the device catalog (its audit rows carry the
  acting user's organization). A part can only be deleted while nothing references it: the
  database's RESTRICT foreign keys decide (stock rows, usage) -> 409 in_use.
- One stock row per hospital and part. Out-of-scope stock rows are 404; another hospital in a
  create request gets the answer a non-existent hospital gets (400), as for devices.
- Nothing new is added to an inactive hospital and its stock cannot change (Decision 6); its data
  stays readable.
- The quantity on hand changes ONLY through: the opening quantity of a new stock row, an
  adjustment (restock > 0, or a signed correction, always with a reason), and part usage on
  maintenance records (CP2, via the database trigger). It can never go below zero: checked under
  a row lock (409 insufficient_stock), with the database CHECK as the last line of defence.
- Every change locks the stock row (SELECT ... FOR UPDATE), so concurrent restocks, corrections
  and usage are applied one after the other and none is lost.
- Stock history = the stock row's audit rows. Every quantity change writes one, in the same
  transaction, carrying a `movement` entry (kind, change, reason, maintenance record). No extra
  table is needed (no schema change); history written outside the API is reported as
  `untracked_change`.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import AuditAction
from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.roles import Role
from app.models.hospital import Hospital
from app.models.part import Part, PartInventory
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.part_repository import InventoryFilters, PartRepository
from app.repositories.ticket_repository import TicketRepository
from app.schemas.part import (
    Actor, InventoryAdjustment, InventoryCreate, InventoryUpdate, MovementKind, PartCreate, PartUpdate, StockMovement,
)
from app.services.audit_service import AuditService, snapshot

logger = logging.getLogger(__name__)

STAFF = frozenset({Role.ADMIN, Role.BIOMEDICAL_ENGINEER, Role.TECHNICIAN})
CATALOG_MANAGERS = frozenset({Role.ADMIN, Role.BIOMEDICAL_ENGINEER})


class InsufficientStockError(ConflictError):
    code = "insufficient_stock"
    default_message = "There is not enough stock of this part."


class PartNotStockedError(ConflictError):
    code = "part_not_stocked"
    default_message = "This part is not stocked at the device's hospital, so its use cannot be recorded."


def require_staff(scope: AccessScope) -> None:
    if scope.role not in STAFF:
        raise ForbiddenError("Spare parts are available to technicians, biomedical engineers and administrators.")


def manages_hospital(scope: AccessScope, hospital_id: uuid.UUID) -> bool:
    return scope.is_admin or (scope.role is Role.BIOMEDICAL_ENGINEER and scope.hospital_id == hospital_id)


def movement(kind: MovementKind, change: int, reason: Optional[str] = None,
             maintenance_record_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"kind": kind.value, "quantity_change": change}
    if reason:
        entry["reason"] = reason
    if maintenance_record_id is not None:
        entry["maintenance_record_id"] = str(maintenance_record_id)
    return {"movement": entry}


class StockLedger:
    """Writes the audit row of a stock change (the stock history). Shared by stock adjustments
    (this module) and part usage (maintenance records, CP2) so both write the same shape."""

    def __init__(self, audit: AuditService):
        self.audit = audit

    def opened(self, actor_id: uuid.UUID, inv: PartInventory, reason: Optional[str]) -> None:
        self.audit.record(
            actor_id=actor_id, organization_id=inv.organization_id, table_name=PartInventory.__tablename__,
            record_id=inv.id, action=AuditAction.INSERT,
            new_values={**snapshot(inv), **movement(MovementKind.OPENING, inv.quantity_on_hand, reason)},
        )

    def changed(self, actor_id: uuid.UUID, inv: PartInventory, before: Dict[str, Any], kind: MovementKind,
                reason: Optional[str] = None, maintenance_record_id: Optional[uuid.UUID] = None) -> None:
        """`before` = snapshot(inv) taken before the change; `inv` already holds the new values."""
        change = inv.quantity_on_hand - before["quantity_on_hand"]
        if change == 0:
            return
        self.audit.updated(actor_id, inv, before, extra_new=movement(kind, change, reason, maintenance_record_id))


class InventoryService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PartRepository(db)
        self.structure = HospitalRepository(db)
        self.audit = AuditService(db)
        self.ledger = StockLedger(self.audit)

    # ---- parts catalog -------------------------------------------------------------------------------
    def get_part(self, scope: AccessScope, part_id: uuid.UUID) -> Part:
        require_staff(scope)
        part = self.repo.get_part(part_id)
        if part is None:
            raise NotFoundError("Part not found.")
        return part

    def list_parts(self, scope: AccessScope, q: Optional[str], page: int, page_size: int) -> Tuple[List[Part], int]:
        require_staff(scope)
        return self.repo.list_parts(q, page, page_size)

    @staticmethod
    def _require_catalog_manager(scope: AccessScope) -> None:
        if scope.role not in CATALOG_MANAGERS:
            raise ForbiddenError("Only biomedical engineers and administrators can manage the parts catalog.")

    def create_part(self, scope: AccessScope, data: PartCreate) -> Part:
        require_staff(scope)
        self._require_catalog_manager(scope)
        if self.repo.part_by_number(data.part_number) is not None:
            raise ConflictError("A part with this part number already exists.")
        part = self.repo.add(Part(name=data.name, part_number=data.part_number, unit=data.unit,
                                  description=data.description or None))
        self.audit.inserted(scope.user_id, part, organization_id=scope.organization_id)
        self.db.commit()
        logger.info("Part created id=%s number=%s", part.id, part.part_number)
        return self.repo.get_part(part.id)

    def update_part(self, scope: AccessScope, part_id: uuid.UUID, data: PartUpdate) -> Part:
        require_staff(scope)
        self._require_catalog_manager(scope)
        part = self.get_part(scope, part_id)
        changes = data.model_dump(exclude_unset=True)
        if "description" in changes and not changes["description"]:
            changes["description"] = None
        if "part_number" in changes and changes["part_number"] != part.part_number:
            other = self.repo.part_by_number(changes["part_number"])
            if other is not None and other.id != part.id:
                raise ConflictError("A part with this part number already exists.")
        changes = {k: v for k, v in changes.items() if getattr(part, k) != v}
        if not changes:
            return part
        before = snapshot(part)
        for key, value in changes.items():
            setattr(part, key, value)
        self.db.flush()
        self.audit.updated(scope.user_id, part, before, organization_id=scope.organization_id)
        self.db.commit()
        return self.repo.get_part(part.id)

    def delete_part(self, scope: AccessScope, part_id: uuid.UUID) -> None:
        require_staff(scope)
        self._require_catalog_manager(scope)
        part = self.get_part(scope, part_id)
        self.audit.deleted(scope.user_id, part, organization_id=scope.organization_id)
        self.db.delete(part)
        # RESTRICT: PostgreSQL refuses while a stock row or a usage line points at the part (409 in_use);
        # the audit row then rolls back with it.
        self.db.commit()
        logger.info("Part deleted id=%s", part_id)

    # ---- stock rows ----------------------------------------------------------------------------------
    def get_inventory(self, scope: AccessScope, inventory_id: uuid.UUID) -> PartInventory:
        require_staff(scope)
        inv = self.repo.get_inventory(scope, inventory_id)
        if inv is None:
            raise NotFoundError("Stock record not found.")
        return inv

    def list_inventory(self, scope: AccessScope, f: InventoryFilters, sort: str, descending: bool, page: int,
                       page_size: int) -> Tuple[List[PartInventory], int]:
        require_staff(scope)
        return self.repo.list_inventory(scope, f, sort, descending, page, page_size)

    def _require_stock_manager(self, scope: AccessScope, hospital_id: uuid.UUID) -> None:
        if not manages_hospital(scope, hospital_id):
            raise ForbiddenError("Only biomedical engineers of the hospital and administrators can manage its stock.")

    @staticmethod
    def _require_active(hospital: Hospital) -> None:
        if not hospital.is_active:  # Decision 6: an inactive hospital's data is read-only
            raise BadRequestError("Hospital is inactive; its stock cannot be changed.")

    def create_inventory(self, scope: AccessScope, data: InventoryCreate) -> PartInventory:
        require_staff(scope)
        if scope.role not in CATALOG_MANAGERS:
            raise ForbiddenError("Only biomedical engineers of the hospital and administrators can manage its stock.")
        hospital_id = data.hospital_id or scope.hospital_id
        # Engineers: only their own hospital. Another hospital gets the answer an unknown one gets.
        hospital = self.structure.get_in_organization(scope.organization_id, hospital_id)
        if hospital is None or (scope.device_hospital_id is not None and hospital_id != scope.device_hospital_id):
            raise BadRequestError("Hospital does not exist in your organization.")
        self._require_active(hospital)
        if self.repo.get_part(data.part_id) is None:
            raise BadRequestError("Unknown part.")
        if self.repo.stock_for(hospital_id, data.part_id) is not None:
            raise ConflictError("This hospital already has a stock record for this part.")
        inv = self.repo.add(PartInventory(
            organization_id=scope.organization_id, hospital_id=hospital_id, part_id=data.part_id,
            quantity_on_hand=data.quantity_on_hand, reorder_threshold=data.reorder_threshold,
        ))
        self.ledger.opened(scope.user_id, inv, data.reason)
        self.db.commit()  # uq_inventory_hospital_part still decides between two concurrent creates (409)
        logger.info("Stock row created id=%s hospital=%s part=%s qty=%s", inv.id, hospital_id, data.part_id,
                    data.quantity_on_hand)
        return self.get_inventory(scope, inv.id)

    def _locked(self, scope: AccessScope, inventory_id: uuid.UUID) -> PartInventory:
        inv = self.repo.get_inventory(scope, inventory_id, for_update=True)
        if inv is None:
            raise NotFoundError("Stock record not found.")
        self._require_stock_manager(scope, inv.hospital_id)
        self._require_active(inv.hospital)
        return inv

    def update_inventory(self, scope: AccessScope, inventory_id: uuid.UUID, data: InventoryUpdate) -> PartInventory:
        require_staff(scope)
        inv = self._locked(scope, inventory_id)
        if inv.reorder_threshold == data.reorder_threshold:
            self.db.rollback()  # nothing to change: release the row lock
            return self.get_inventory(scope, inventory_id)
        before = snapshot(inv)
        inv.reorder_threshold = data.reorder_threshold
        self.db.flush()
        self.audit.updated(scope.user_id, inv, before)
        self.db.commit()
        return self.get_inventory(scope, inventory_id)

    def adjust(self, scope: AccessScope, inventory_id: uuid.UUID, data: InventoryAdjustment) -> PartInventory:
        require_staff(scope)
        inv = self._locked(scope, inventory_id)
        new_quantity = inv.quantity_on_hand + data.quantity_change
        if new_quantity < 0:
            raise InsufficientStockError(
                f"Only {inv.quantity_on_hand} {inv.part.unit} on hand; cannot remove {-data.quantity_change}.",
                details=[{"available": inv.quantity_on_hand, "requested": -data.quantity_change}])
        before = snapshot(inv)
        inv.quantity_on_hand = new_quantity
        self.db.flush()
        self.ledger.changed(scope.user_id, inv, before, MovementKind(data.kind.value), data.reason)
        self.db.commit()
        logger.info("Stock adjusted id=%s kind=%s change=%s now=%s", inv.id, data.kind.value, data.quantity_change,
                    new_quantity)
        return self.get_inventory(scope, inventory_id)

    # ---- stock history -------------------------------------------------------------------------------
    def history(self, scope: AccessScope, inventory_id: uuid.UUID) -> Tuple[PartInventory, List[StockMovement], int]:
        inv = self.get_inventory(scope, inventory_id)
        rows = self.repo.movement_rows(inv)
        people = TicketRepository(self.db).users_by_id(inv.organization_id, [r.user_id for r in rows])
        movements: List[StockMovement] = []
        for r in rows:
            new = r.new_values or {}
            if "quantity_on_hand" not in new:
                continue  # a settings change (reorder threshold)
            old_qty = 0 if r.action is AuditAction.INSERT else (r.old_values or {}).get("quantity_on_hand")
            if old_qty is None:
                continue
            change = new["quantity_on_hand"] - old_qty
            if change == 0:
                continue
            meta = new.get("movement") or {}
            try:
                kind = MovementKind(meta.get("kind"))
            except ValueError:
                kind = MovementKind.OPENING if r.action is AuditAction.INSERT else MovementKind.CORRECTION
            person = people.get(r.user_id)
            movements.append(StockMovement(
                at=r.created_at, kind=kind, quantity_change=change, quantity_after=new["quantity_on_hand"],
                reason=meta.get("reason"),
                maintenance_record_id=meta.get("maintenance_record_id"),
                by=Actor(id=person.id, name=person.full_name, role=person.role.name) if person else None,
            ))
        untracked = inv.quantity_on_hand - sum(m.quantity_change for m in movements)
        return inv, movements, untracked
