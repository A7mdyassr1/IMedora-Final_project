"""Spare parts API schemas (B5): catalog, hospital stock, stock movements, part usage.

Requests reject unknown fields. Stock quantities can only change through an adjustment (restock /
correction, with a reason) or through part usage on a maintenance record - never by sending a new
quantity_on_hand.
"""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.schemas.common import reject_explicit_nulls

MAX_QUANTITY = 100_000            # one movement / one usage line
PART_DESCRIPTION_MAX = 2000
REASON_MAX = 500

PartName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
# IMedora's own catalog code: trimmed and upper-cased so "pn-psu-016" and "PN-PSU-016" are one part.
PartNumber = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=100,
                                              pattern=r"^\S+$")]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=20)]
PartDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=PART_DESCRIPTION_MAX)]
Quantity = Annotated[int, Field(ge=1, le=MAX_QUANTITY)]
Threshold = Annotated[int, Field(ge=0, le=MAX_QUANTITY)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=REASON_MAX)]


# ---- catalog ---------------------------------------------------------------------------------------
class PartCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: PartName
    part_number: PartNumber = Field(description="Unique catalog code; stored upper-case, no spaces.")
    unit: Unit = "piece"
    description: Optional[PartDescription] = None


class PartUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[PartName] = None
    part_number: Optional[PartNumber] = None
    unit: Optional[Unit] = None
    description: Optional[PartDescription] = Field(default=None, description="null clears it.")

    @model_validator(mode="after")
    def _check(self):
        reject_explicit_nulls(self, ("name", "part_number", "unit"))
        if not self.model_fields_set:
            raise ValueError("Nothing to change.")
        return self


class PartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    part_number: str
    unit: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PartSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    part_number: str
    unit: str


# ---- stock -----------------------------------------------------------------------------------------
class InventoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_id: uuid.UUID
    hospital_id: Optional[uuid.UUID] = Field(default=None, description="Defaults to the caller's own hospital.")
    quantity_on_hand: Annotated[int, Field(ge=0, le=MAX_QUANTITY)] = Field(
        default=0, description="Opening stock, recorded as the first stock movement.")
    reorder_threshold: Optional[Threshold] = None
    reason: Optional[Reason] = Field(default=None, description="Why / where the opening stock comes from.")


class InventoryUpdate(BaseModel):
    """Settings only. The quantity changes through POST /inventory/{id}/adjustments."""
    model_config = ConfigDict(extra="forbid")
    reorder_threshold: Optional[Threshold] = Field(description="null removes the threshold.")


class AdjustmentKind(StrEnum):
    RESTOCK = "restock"          # stock received: quantity_change > 0
    CORRECTION = "correction"    # stock count, damage, expiry, loss...: either sign


class InventoryAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: AdjustmentKind
    quantity_change: Annotated[int, Field(ge=-MAX_QUANTITY, le=MAX_QUANTITY)] = Field(
        description="Signed change of the quantity on hand (never 0).")
    reason: Reason

    @field_validator("quantity_change")
    @classmethod
    def _not_zero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("quantity_change cannot be 0")
        return v

    @model_validator(mode="after")
    def _restock_adds(self):
        if self.kind is AdjustmentKind.RESTOCK and self.quantity_change < 0:
            raise ValueError("A restock adds stock: quantity_change must be positive (use a correction to remove stock).")
        return self


class HospitalRef(BaseModel):
    id: uuid.UUID
    name: str
    code: str


class InventoryResponse(BaseModel):
    id: uuid.UUID
    hospital: HospitalRef
    part: PartSummary
    quantity_on_hand: int
    reorder_threshold: Optional[int] = None
    is_low_stock: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, inv) -> "InventoryResponse":
        return cls(
            id=inv.id, hospital=HospitalRef(id=inv.hospital.id, name=inv.hospital.name, code=inv.hospital.code),
            part=PartSummary.model_validate(inv.part), quantity_on_hand=inv.quantity_on_hand,
            reorder_threshold=inv.reorder_threshold, is_low_stock=inv.is_low_stock,
            created_at=inv.created_at, updated_at=inv.updated_at,
        )


class MovementKind(StrEnum):
    OPENING = "opening"            # stock row created with an opening quantity
    RESTOCK = "restock"
    CORRECTION = "correction"
    USAGE = "usage"                # part used on a maintenance record
    USAGE_CHANGE = "usage_change"  # quantity of a usage line corrected
    USAGE_RETURN = "usage_return"  # usage line removed: stock given back


class Actor(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class StockMovement(BaseModel):
    at: datetime
    kind: MovementKind
    quantity_change: int
    quantity_after: int
    reason: Optional[str] = None
    maintenance_record_id: Optional[uuid.UUID] = None
    by: Optional[Actor] = None


class StockHistory(BaseModel):
    inventory: InventoryResponse
    movements: List[StockMovement] = Field(description="Oldest first.")
    untracked_change: int = Field(
        description="Part of the current quantity not explained by the recorded movements: stock written "
                    "directly in the database (seed data, imports). 0 when every change went through the API.")


# ---- usage -----------------------------------------------------------------------------------------
class PartUse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_id: uuid.UUID
    quantity: Quantity


class PartUseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: Quantity


class UsedPart(BaseModel):
    id: uuid.UUID
    part: PartSummary
    quantity: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, mp) -> "UsedPart":
        return cls(id=mp.id, part=PartSummary.model_validate(mp.part), quantity=mp.quantity,
                   created_at=mp.created_at, updated_at=mp.updated_at)


class UsageResponse(BaseModel):
    id: uuid.UUID
    part: PartSummary
    quantity: int
    maintenance_record_id: uuid.UUID
    hospital_id: uuid.UUID
    device_id: uuid.UUID
    ticket_id: Optional[uuid.UUID] = None
    ticket_number: Optional[str] = None
    performed_at: datetime
    created_at: datetime
