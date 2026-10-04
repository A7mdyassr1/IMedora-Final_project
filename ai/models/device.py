"""
Device models - lean AI-facing views of the `devices` table and its
lookups (device_models, manufacturers, device_categories, departments,
locations). These deliberately do NOT mirror every database column -
only what an agent or tool actually needs to reason about or display.

Field choices (status/criticality/risk) are typed as Literal unions that
match the real Postgres enums exactly (see database/schemas/schema.sql),
so a value the database could never produce can never silently appear
here either.
"""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

DeviceStatus = Literal["active", "under_maintenance", "out_of_service", "decommissioned"]
DeviceCriticality = Literal["low", "medium", "high", "critical"]
RiskLevel = Literal["low", "medium", "high", "critical"]


class DeviceContext(BaseModel):
    """Minimal device identity - enough to reference a device across
    tools and agents without pulling the full profile every time."""

    device_id: str
    device_code: str
    name: str
    hospital_id: str
    hospital_name: Optional[str] = None
    department_name: Optional[str] = None
    status: DeviceStatus


class DeviceProfile(BaseModel):
    """Fuller device profile for chatbot answers and report sections."""

    device_id: str
    device_code: str
    name: str
    serial_number: Optional[str] = None
    qr_identifier: str
    manufacturer: Optional[str] = None
    model_name: Optional[str] = None
    category: Optional[str] = None
    status: DeviceStatus
    criticality: DeviceCriticality
    current_risk_level: Optional[RiskLevel] = None
    hospital_name: Optional[str] = None
    department_name: Optional[str] = None
    location: Optional[str] = None
    installation_date: Optional[date] = None
    warranty_expiry: Optional[date] = None
    next_maintenance_due_date: Optional[date] = None
    data_as_of: Optional[str] = Field(
        default=None,
        description="Timestamp this profile was fetched, so stale data is never presented as live.",
    )
