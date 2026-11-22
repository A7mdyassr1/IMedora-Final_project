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


class TicketStatus(StrEnum):
    """Mirror of the PostgreSQL `ticket_status` enum (migration 0002), in database order."""
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_PARTS = "waiting_for_parts"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TicketPriority(StrEnum):
    """Mirror of the PostgreSQL `ticket_priority` enum (migration 0002). Database order is
    low < medium < high < critical, so ORDER BY priority sorts by urgency."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
