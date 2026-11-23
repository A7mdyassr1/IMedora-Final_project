"""Parts used on maintenance records (B5 CP2) - the maintenance <-> stock integration.

The database trigger `trg_maintenance_parts_adjust_inventory` does the stock arithmetic: inserting
a usage line subtracts its quantity from the stock of the RECORD'S hospital, changing the quantity
applies the difference, deleting the line gives the stock back. This module never writes
quantity_on_hand itself. For every change it:

1. locks the hospital's stock rows of the parts involved (SELECT ... FOR UPDATE, part_id order),
   so concurrent usage, restocks and corrections queue instead of overselling or deadlocking;
2. checks under that lock, for a clear answer instead of a database error:
   - the part exists (400), the hospital stocks it (409 part_not_stocked),
   - enough is on hand for any increase (409 insufficient_stock, with available / requested);
3. writes the usage line (the trigger adjusts the locked stock row), re-reads the stock row and
   writes two audit rows in the same transaction: the usage line itself and the stock movement
   (kind usage / usage_change / usage_return, linked to the maintenance record).

The database CHECK (quantity_on_hand >= 0) and the trigger's RAISE EXCEPTION stay the last line of
defence; both are mapped to the same 409 errors (app/core/db_errors.py).

Callers (MaintenanceService) decide WHO may change usage and lock the ticket and the record first:
lock order everywhere is ticket -> device -> schedule -> record -> stock rows.
"""
import uuid
from typing import Dict, Iterable, List

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, ConflictError
from app.models.maintenance import MaintenanceRecord
from app.models.part import MaintenancePart, PartInventory
from app.repositories.part_repository import PartRepository
from app.schemas.part import MovementKind, PartUse
from app.services.audit_service import AuditService, snapshot
from app.services.inventory_service import InsufficientStockError, PartNotStockedError, StockLedger


class PartUsage:
    def __init__(self, db: Session, audit: AuditService):
        self.db = db
        self.repo = PartRepository(db)
        self.audit = audit
        self.ledger = StockLedger(audit)

    def _stock(self, record: MaintenanceRecord, part_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, PartInventory]:
        part_ids = list(part_ids)
        known = self.repo.parts_by_id(part_ids)
        unknown = [str(p) for p in part_ids if p not in known]
        if unknown:
            raise BadRequestError("Unknown part.", details=[{"part_id": p} for p in unknown])
        stock = self.repo.lock_stock(record.hospital_id, part_ids)
        missing = [str(p) for p in part_ids if p not in stock]
        if missing:
            raise PartNotStockedError(details=[{"part_id": p} for p in missing])
        return stock

    @staticmethod
    def _enough(inv: PartInventory, needed: int) -> None:
        if needed > inv.quantity_on_hand:
            raise InsufficientStockError(
                f"Only {inv.quantity_on_hand} {inv.part.unit} of {inv.part.part_number} on hand; {needed} needed.",
                details=[{"part_id": str(inv.part_id), "available": inv.quantity_on_hand, "requested": needed}])

    # ---- writes ---------------------------------------------------------------------------------------
    def use(self, actor_id: uuid.UUID, record: MaintenanceRecord, lines: List[PartUse]) -> None:
        """Add usage lines to a record (new record, or a part not yet listed on it)."""
        if not lines:
            return
        stock = self._stock(record, [line.part_id for line in lines])
        existing = {mp.part_id for mp in self.repo.usage_for_record(record.id)}
        for line in lines:
            if line.part_id in existing:
                raise ConflictError("This part is already listed on this maintenance record; change its quantity instead.")
            self._enough(stock[line.part_id], line.quantity)
        for line in sorted(lines, key=lambda l: l.part_id):
            inv = stock[line.part_id]
            before = snapshot(inv)
            usage = self.repo.add(MaintenancePart(maintenance_record_id=record.id, part_id=line.part_id,
                                                  quantity=line.quantity))
            self.repo.refresh(inv)  # the trigger subtracted the quantity
            self.audit.inserted(actor_id, usage, organization_id=record.organization_id)
            self.ledger.changed(actor_id, inv, before, MovementKind.USAGE, maintenance_record_id=record.id)

    def change(self, actor_id: uuid.UUID, record: MaintenanceRecord, usage: MaintenancePart, quantity: int) -> bool:
        """Correct the quantity of a usage line. Returns False when nothing changed."""
        if usage.quantity == quantity:
            return False
        inv = self._stock(record, [usage.part_id])[usage.part_id]
        increase = quantity - usage.quantity
        if increase > 0:
            self._enough(inv, increase)
        before_stock, before_usage = snapshot(inv), snapshot(usage)
        usage.quantity = quantity
        self.db.flush()                 # trigger: stock -= (new - old)
        self.repo.refresh(inv)
        self.audit.updated(actor_id, usage, before_usage, organization_id=record.organization_id)
        self.ledger.changed(actor_id, inv, before_stock, MovementKind.USAGE_CHANGE, maintenance_record_id=record.id)
        return True

    def remove(self, actor_id: uuid.UUID, record: MaintenanceRecord, usage: MaintenancePart) -> None:
        """Remove a usage line (recorded by mistake): its quantity goes back to stock."""
        inv = self._stock(record, [usage.part_id])[usage.part_id]
        before = snapshot(inv)
        self.audit.deleted(actor_id, usage, organization_id=record.organization_id)
        self.repo.delete(usage)         # trigger: stock += quantity
        self.repo.refresh(inv)
        self.ledger.changed(actor_id, inv, before, MovementKind.USAGE_RETURN, maintenance_record_id=record.id)
