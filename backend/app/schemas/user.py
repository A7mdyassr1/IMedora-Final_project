import re
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.roles import Role

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128

# Deliberately not EmailStr: its validator rejects reserved domains such as
# .local / .example, which the project's own seed data and demo account use.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 255 or not _EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address")
    return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    full_name: str
    role: str = Field(validation_alias="role_name")
    hospital_id: uuid.UUID
    hospital_name: str
    department_id: Optional[uuid.UUID] = None
    department_name: Optional[str] = None
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: str
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    role: Role
    hospital_id: uuid.UUID
    department_id: Optional[uuid.UUID] = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name must not be blank")
        return v


class UserUpdate(BaseModel):
    """PATCH body: only the fields that are sent are changed."""

    email: Optional[str] = None
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    role: Optional[Role] = None
    hospital_id: Optional[uuid.UUID] = None
    department_id: Optional[uuid.UUID] = None  # explicit null clears it
    is_active: Optional[bool] = None

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return normalize_email(v) if v is not None else v

    @model_validator(mode="after")
    def _no_null_for_required_fields(self):
        for name in ("email", "full_name", "role", "hospital_id", "is_active"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
