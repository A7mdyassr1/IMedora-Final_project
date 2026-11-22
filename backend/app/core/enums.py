"""Python mirrors of the existing PostgreSQL enum types (values match exactly)."""
from enum import StrEnum


class DeviceStatus(StrEnum):
    ACTIVE = "active"
    UNDER_MAINTENANCE = "under_maintenance"
    OUT_OF_SERVICE = "out_of_service"
    DECOMMISSIONED = "decommissioned"


class Criticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AuditAction(StrEnum):
    """Mirror of the PostgreSQL `audit_action` enum (migration 0005)."""
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
