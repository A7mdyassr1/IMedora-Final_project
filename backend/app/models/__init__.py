# Import every model so SQLAlchemy can resolve all ForeignKey/relationship targets.
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.catalog import DeviceCategory, DeviceModel, Manufacturer
from app.models.department import Department
from app.models.device import Device
from app.models.hospital import Hospital
from app.models.location import Location
from app.models.maintenance import MaintenanceRecord, MaintenanceSchedule, MaintenanceType
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.part import MaintenancePart, Part, PartInventory
from app.models.role import Role
from app.models.ticket import MaintenanceTicket, TicketAssignment
from app.models.user import User

__all__ = [
    "AuditLog", "Base", "Department", "Device", "DeviceCategory", "DeviceModel", "Hospital",
    "Location", "MaintenancePart", "MaintenanceRecord", "MaintenanceSchedule", "MaintenanceTicket", "MaintenanceType", "Manufacturer",
    "Notification", "Organization", "Part", "PartInventory", "Role", "TicketAssignment", "User",
]
