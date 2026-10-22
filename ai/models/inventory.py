"""Inventory models - AI-facing view of `parts` + `part_inventory`."""
from typing import Optional

from pydantic import BaseModel


class InventoryContext(BaseModel):
    part_id: str
    part_name: str
    part_number: str
    hospital_id: str
    hospital_name: Optional[str] = None
    quantity_on_hand: int
    reorder_threshold: Optional[int] = None

    @property
    def below_reorder_threshold(self) -> bool:
        return self.reorder_threshold is not None and self.quantity_on_hand <= self.reorder_threshold
