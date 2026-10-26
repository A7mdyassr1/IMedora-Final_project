import uuid
from typing import Optional

from pydantic import BaseModel, model_validator

from app.schemas.common import Name100, Name255, reject_explicit_nulls


class CategoryCreate(BaseModel):
    name: Name100


class CategoryUpdate(BaseModel):
    name: Name100


class CategoryResponse(BaseModel):
    id: uuid.UUID
    name: str


class ManufacturerCreate(BaseModel):
    name: Name255


class ManufacturerUpdate(BaseModel):
    name: Name255


class ManufacturerResponse(BaseModel):
    id: uuid.UUID
    name: str


class DeviceModelCreate(BaseModel):
    manufacturer_id: uuid.UUID
    device_category_id: uuid.UUID
    name: Name255


class DeviceModelUpdate(BaseModel):
    manufacturer_id: Optional[uuid.UUID] = None
    device_category_id: Optional[uuid.UUID] = None
    name: Optional[Name255] = None

    @model_validator(mode="after")
    def _nulls(self):
        reject_explicit_nulls(self, ("manufacturer_id", "device_category_id", "name"))
        return self


class DeviceModelResponse(BaseModel):
    id: uuid.UUID
    name: str
    manufacturer_id: uuid.UUID
    manufacturer_name: str
    device_category_id: uuid.UUID
    category_name: str
