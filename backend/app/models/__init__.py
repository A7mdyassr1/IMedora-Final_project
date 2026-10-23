# Import every model so SQLAlchemy can resolve all ForeignKey/relationship targets.
from app.models.base import Base
from app.models.department import Department
from app.models.hospital import Hospital
from app.models.organization import Organization
from app.models.role import Role
from app.models.user import User

__all__ = ["Base", "Department", "Hospital", "Organization", "Role", "User"]
