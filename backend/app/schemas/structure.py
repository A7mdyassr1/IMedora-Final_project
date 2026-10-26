import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import Code50, Name255, reject_explicit_nulls


# ---- organization ------------------------------------------------------------
class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    is_active: bool


class OrganizationUpdate(BaseModel):
    name: Name255


# ---- hospitals -----------------------------------------------------------------
class HospitalCreate(BaseModel):
    name: Name255
    code: Code50
    address: Optional[str] = Field(default=None, max_length=500)


class HospitalUpdate(BaseModel):
    name: Optional[Name255] = None
    code: Optional[Code50] = None
    address: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def _nulls(self):
        reject_explicit_nulls(self, ("name", "code", "is_active"))
        return self


class HospitalResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    code: str
    address: Optional[str] = None
    is_active: bool
    created_at: datetime


# ---- departments -----------------------------------------------------------------
class DepartmentCreate(BaseModel):
    hospital_id: uuid.UUID
    name: Name255


class DepartmentUpdate(BaseModel):
    name: Name255


class DepartmentResponse(BaseModel):
    id: uuid.UUID
    hospital_id: uuid.UUID
    name: str
    created_at: datetime


# ---- locations ----------------------------------------------------------------------
class LocationCreate(BaseModel):
    hospital_id: uuid.UUID
    building: Optional[str] = Field(default=None, max_length=100)
    floor: Optional[str] = Field(default=None, max_length=50)
    room: Optional[str] = Field(default=None, max_length=50)

    @field_validator("building", "floor", "room", mode="before")
    @classmethod
    def clean_location_fields(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value


    @model_validator(mode="after")
    def _something_given(self):
        if not any((v or "").strip() for v in (self.building, self.floor, self.room)):
            raise ValueError("Provide at least one of building, floor or room")
        return self


class LocationUpdate(BaseModel):
    building: Optional[str] = Field(default=None, max_length=100)
    floor: Optional[str] = Field(default=None, max_length=50)
    room: Optional[str] = Field(default=None, max_length=50)

    @field_validator("building", "floor", "room", mode="before")
    @classmethod
    def clean_location_fields(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

class LocationResponse(BaseModel):
    id: uuid.UUID
    hospital_id: uuid.UUID
    building: Optional[str] = None
    floor: Optional[str] = None
    room: Optional[str] = None
    label: Optional[str] = None  # "Building - Floor - Room", the form the mobile app shows
