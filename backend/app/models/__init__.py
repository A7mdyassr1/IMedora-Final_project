# Import every model so SQLAlchemy can resolve all ForeignKey/relationship targets.
from app.models.base import Base
from app.models.catalog import DeviceCategory, DeviceModel, Manufacturer
from app.models.department import Department
from app.models.device import Device
from app.models.hospital import Hospital
from app.models.location import Location
from app.models.organization import Organization
from app.models.role import Role
from app.models.user import User

__all__ = [
    "Base", "Department", "Device", "DeviceCategory", "DeviceModel", "Hospital",
    "Location", "Manufacturer", "Organization", "Role", "User",
]
