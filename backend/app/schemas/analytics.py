"""Dashboard & analytics responses (B10).

The metric rules are those of the AI package (`ai/services/analytics/metrics.py` on main), so the web
dashboard and the AI assistant report the same numbers. See `docs/api/analytics.md`.
"""
import uuid
from datetime import date, datetime
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class Distribution(BaseModel):
    """Counts per value, with every possible value present (zeros included), and percentages of the
    total rounded to 1 decimal (null when the total is 0)."""
    total: int
    counts: Dict[str, int]
    percentages: Dict[str, Optional[float]]


class NamedCount(BaseModel):
    id: uuid.UUID
    name: str
    count: int


class AppliedFilters(BaseModel):
    hospital_id: Optional[uuid.UUID]
    department_id: Optional[uuid.UUID]
    include_archived: bool


class Period(BaseModel):
    date_from: date = Field(description="Inclusive (database date).")
    date_to: date = Field(description="Inclusive (database date).")


class DeviceAnalytics(BaseModel):
    filters: AppliedFilters
    total: int
    by_status: Distribution
    by_risk_level: Distribution = Field(description="Current risk level (the database's cached value); "
                                                    "`unassessed` = never assessed.")
    by_criticality: Distribution
    by_department: List[NamedCount] = Field(description="Most devices first, then by name.")
    by_category: List[NamedCount] = Field(description="Most devices first, then by name.")


# ---- CP2 -------------------------------------------------------------------------------------------
class DeviceRef(BaseModel):
    device_id: uuid.UUID
    device_code: str
    name: str
    department: str
    hospital: str


class OverdueDevice(DeviceRef):
    next_due_date: date
    days_overdue: int


class PreventiveCompliance(BaseModel):
    as_of: date = Field(description="The database's today.")
    due_soon_days: int
    devices_evaluated: int = Field(description="Devices in scope that are not decommissioned.")
    counts: Dict[str, int] = Field(description="`overdue`, `due_soon`, `on_track`, `no_schedule` (no active preventive "
                                               "schedule), `unknown_due_date` (always 0: the due date is required).")
    compliance_rate_pct: Optional[float] = Field(description="(due_soon + on_track) / devices with a schedule; null "
                                                             "when none has one.")
    overdue_total: int
    overdue_devices: List[OverdueDevice] = Field(description="Most overdue first, then by device code; at most `limit`.")


class MaintenanceAnalytics(BaseModel):
    filters: AppliedFilters
    period: Period
    total: int = Field(description="Maintenance records performed in the period.")
    preventive: int = Field(description="Records of the type named `preventive` (case-insensitive).")
    corrective: int = Field(description="Records of the type named `corrective` (case-insensitive).")
    by_type: List[NamedCount] = Field(description="Every maintenance type with records in the period.")
    preventive_compliance: PreventiveCompliance


class MttrStats(BaseModel):
    mttr_hours: float
    median_hours: float
    min_hours: float
    max_hours: float
    sample_size: int


class TicketAnalytics(BaseModel):
    filters: AppliedFilters
    period: Period
    created: Distribution = Field(description="Tickets created in the period, by current status.")
    by_priority: Distribution = Field(description="Tickets created in the period, by priority.")
    by_department: List[NamedCount] = Field(description="Tickets created in the period, by their device's department.")
    failures: int = Field(description="Tickets created in the period that are not cancelled (the AI rule).")
    resolved: int = Field(description="Tickets resolved or closed whose resolution falls in the period.")
    open_now: Distribution = Field(description="Tickets open right now (any creation date), by status.")
    mttr: Optional[MttrStats] = Field(description="Hours from report to resolution of the tickets resolved in the "
                                                  "period; null when there are none.")


class ProblemDevice(DeviceRef):
    ticket_count: int = Field(description="Failure tickets (not cancelled) created in the period.")
    corrective_maintenance_count: int = Field(description="Corrective records performed in the period.")
    last_ticket_at: Optional[datetime]


class ProblemDevices(BaseModel):
    filters: AppliedFilters
    period: Period
    ranked_by: str
    min_tickets: int
    total_devices: int = Field(description="Devices that qualify, before `limit`.")
    devices: List[ProblemDevice]


# ---- CP3 ----------------------------------------------------------------------------------------------
class LowStockItem(BaseModel):
    inventory_id: uuid.UUID
    part_id: uuid.UUID
    part_number: str
    part_name: str
    unit: str
    hospital_id: uuid.UUID
    hospital: str
    quantity_on_hand: int
    reorder_threshold: int


class InventoryAnalytics(BaseModel):
    hospital_id: Optional[uuid.UUID] = Field(description="The `hospital_id` filter, if any.")
    items_tracked: int = Field(description="Stock rows (one per hospital and part).")
    parts_tracked: int = Field(description="Distinct parts stocked.")
    total_units_on_hand: int
    low_stock_count: int = Field(description="Stock rows at or below their reorder threshold (no threshold = never low).")
    out_of_stock_count: int = Field(description="Stock rows with nothing on hand.")
    low_stock: List[LowStockItem] = Field(description="Low-stock rows, emptiest first; at most `limit`.")


TrendMetric = Literal["tickets", "corrective_maintenance", "preventive_maintenance", "total_maintenance", "mttr_hours"]
TrendInterval = Literal["day", "week", "month"]


class TrendPoint(BaseModel):
    start: date = Field(description="First day of the bucket inside the period (a bucket may be cut by the period).")
    end: date = Field(description="Last day of the bucket inside the period.")
    value: Union[int, float, None] = Field(description="Count, or mean hours for `mttr_hours` (2 decimals; null "
                                                       "when no ticket was resolved in the bucket).")
    sample_size: int = Field(description="Tickets or records behind the value.")


class TrendAnalytics(BaseModel):
    filters: AppliedFilters
    metric: TrendMetric
    interval: TrendInterval
    period: Period
    points: List[TrendPoint] = Field(description="Every bucket of the period, oldest first, empty ones included.")


# ---- CP4 ----------------------------------------------------------------------------------------------
class OverviewDevices(BaseModel):
    total: int
    by_status: Distribution
    by_risk_level: Distribution = Field(description="Current risk level; `unassessed` = no current assessment.")


class OverviewOpenTickets(BaseModel):
    by_status: Distribution = Field(description="Tickets open now (open, assigned, in progress, waiting for parts).")
    by_priority: Distribution


class OverviewSchedules(BaseModel):
    as_of: date
    due_soon_days: int
    overdue: int = Field(description="Active schedules (any type) due before today; decommissioned devices left out.")
    due_soon: int = Field(description="Active schedules due from today to today + `due_soon_days`.")


class OverviewInventory(BaseModel):
    items_tracked: int
    low_stock_count: int
    out_of_stock_count: int


class OverviewActivity(BaseModel):
    failures: int = Field(description="Tickets created in the period that are not cancelled.")
    tickets_resolved: int = Field(description="Tickets resolved or closed in the period.")
    mttr_hours: Optional[float] = Field(description="Mean hours to resolution of those tickets; null if none.")
    maintenance_performed: int
    preventive: int
    corrective: int
    preventive_compliance_rate_pct: Optional[float] = Field(description="Today, as on /analytics/maintenance.")


class DashboardOverview(BaseModel):
    filters: AppliedFilters
    period: Period
    devices: OverviewDevices
    open_tickets: OverviewOpenTickets
    schedules: OverviewSchedules
    inventory: OverviewInventory = Field(description="Stock belongs to a hospital: `hospital_id` narrows it, "
                                                     "`department_id` and `include_archived` do not apply.")
    qa: Distribution = Field(description="QA records of the devices in scope, by status.")
    activity: OverviewActivity = Field(description="What happened in the period.")
