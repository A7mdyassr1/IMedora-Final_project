"""
Analytics tools (Phase AI-4). Every number is computed in Python by
ai/services/analytics; the LLM only explains the AnalyticsResult it gets.

Result shape (matches single()): {"found": bool, "result": AnalyticsResult | None, "message": str | None}.
`found=False` means there is nothing to compute from - never a zero invented in its place.
"""
from typing import Any, Dict, Optional

from ai.models.analytics import AnalyticsResult
from ai.services.analytics import metrics
from ai.services.analytics.data_access import (
    collect_maintenance, collect_preventive_schedules, collect_tickets, current_risk_by_device,
    get_all_devices, resolve_as_of,
)
from ai.services.data.base import DataProvider
from ai.tools.base import tool, to_date

NO_DEVICES = "No devices match the given filters."


def _result(metric_name: str, value: Any, unit: Optional[str], /, **filters: Any) -> Dict[str, Any]:
    applied = {k: v for k, v in filters.items() if v is not None}
    result = AnalyticsResult(metric_name=metric_name, value=value, unit=unit, filters_applied=applied)
    return {"found": True, "result": result.model_dump(mode="json"), "message": None}


def _no_data(message: str, **filters: Any) -> Dict[str, Any]:
    return {"found": False, "result": None, "message": message,
            "filters_applied": {k: v for k, v in filters.items() if v is not None}}


@tool("analytics")
def get_mttr(
    provider: DataProvider, hospital_id: Optional[str] = None, department: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> dict:
    """Mean time to repair (hours) from resolved/closed tickets; filter by hospital, department, resolution date range."""
    f = dict(hospital_id=hospital_id, department=department, date_from=date_from, date_to=date_to)
    devices = get_all_devices(provider, hospital_id, department)
    if not devices:
        return _no_data(NO_DEVICES, **f)
    value = metrics.mttr(collect_tickets(provider, devices), to_date(date_from), to_date(date_to))
    if value is None:
        return _no_data("No resolved tickets match the filters, so MTTR cannot be computed.", **f)
    return _result("mttr", value, "hours", **f)


@tool("analytics")
def get_repeated_failures(
    provider: DataProvider, min_tickets: int = 2, hospital_id: Optional[str] = None,
    department: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> dict:
    """Devices with at least `min_tickets` non-cancelled tickets in the period (repeated failures), most failures first."""
    min_tickets = int(min_tickets)
    if min_tickets < 1:
        raise ValueError("min_tickets must be >= 1")
    f = dict(min_tickets=min_tickets, hospital_id=hospital_id, department=department, date_from=date_from, date_to=date_to)
    devices = get_all_devices(provider, hospital_id, department)
    if not devices:
        return _no_data(NO_DEVICES, **f)
    value = metrics.repeated_failures(collect_tickets(provider, devices), devices, min_tickets, to_date(date_from), to_date(date_to))
    return _result("repeated_failures", value, "devices", **f)


@tool("analytics")
def get_top_problem_devices(
    provider: DataProvider, limit: int = 5, hospital_id: Optional[str] = None,
    department: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> dict:
    """Top `limit` devices by number of tickets, then corrective maintenance records, in the period."""
    limit = int(limit)
    if limit < 1:
        raise ValueError("limit must be >= 1")
    f = dict(limit=limit, hospital_id=hospital_id, department=department, date_from=date_from, date_to=date_to)
    devices = get_all_devices(provider, hospital_id, department)
    if not devices:
        return _no_data(NO_DEVICES, **f)
    value = metrics.rank_problem_devices(
        collect_tickets(provider, devices), collect_maintenance(provider, devices), devices,
        limit, to_date(date_from), to_date(date_to),
    )
    return _result("top_problem_devices", value, "devices", **f)


@tool("analytics")
def get_ticket_distribution(
    provider: DataProvider, group_by: str = "status", hospital_id: Optional[str] = None,
    department: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> dict:
    """Ticket counts and percentages grouped by status, priority, department or hospital (cancelled tickets included)."""
    if group_by not in metrics.GROUP_BY_OPTIONS:
        raise ValueError(f"group_by must be one of {list(metrics.GROUP_BY_OPTIONS)}, got {group_by!r}")
    f = dict(group_by=group_by, hospital_id=hospital_id, department=department, date_from=date_from, date_to=date_to)
    devices = get_all_devices(provider, hospital_id, department)
    if not devices:
        return _no_data(NO_DEVICES, **f)
    d_from, d_to = to_date(date_from), to_date(date_to)
    tickets = [t for t in collect_tickets(provider, devices) if metrics.in_period(t.created_at, d_from, d_to)]
    if not tickets:
        return _no_data("No tickets match the filters.", **f)
    return _result("ticket_distribution", metrics.distribution(metrics.ticket_group_keys(tickets, devices, group_by)), "tickets", **f)


@tool("analytics")
def get_device_status_distribution(
    provider: DataProvider, hospital_id: Optional[str] = None, department: Optional[str] = None,
) -> dict:
    """Device counts and percentages by operational status (active / under_maintenance / out_of_service / decommissioned)."""
    f = dict(hospital_id=hospital_id, department=department)
    devices = get_all_devices(provider, hospital_id, department)
    if not devices:
        return _no_data(NO_DEVICES, **f)
    return _result("device_status_distribution", metrics.distribution(d.status for d in devices), "devices", **f)


@tool("analytics")
def get_risk_distribution(
    provider: DataProvider, hospital_id: Optional[str] = None, department: Optional[str] = None,
) -> dict:
    """Device counts and percentages by CURRENT risk level; devices never assessed are reported as 'unassessed'."""
    f = dict(hospital_id=hospital_id, department=department)
    devices = get_all_devices(provider, hospital_id, department)
    if not devices:
        return _no_data(NO_DEVICES, **f)
    risk = current_risk_by_device(provider)
    return _result("risk_distribution", metrics.distribution(risk.get(d.device_id, "unassessed") for d in devices), "devices", **f)


@tool("analytics")
def get_preventive_compliance(
    provider: DataProvider, hospital_id: Optional[str] = None, department: Optional[str] = None,
    due_soon_days: int = 30, as_of: Optional[str] = None,
) -> dict:
    """Preventive-maintenance compliance: overdue / due soon / on track / no schedule, plus the overdue device list."""
    due_soon_days = int(due_soon_days)
    if due_soon_days < 0:
        raise ValueError("due_soon_days must be >= 0")
    f = dict(hospital_id=hospital_id, department=department, due_soon_days=due_soon_days, as_of=as_of)
    devices = get_all_devices(provider, hospital_id, department)
    if not devices:
        return _no_data(NO_DEVICES, **f)
    value = metrics.preventive_compliance(
        devices, collect_preventive_schedules(provider, devices),
        resolve_as_of(provider, devices, to_date(as_of)), due_soon_days,
    )
    return _result("preventive_compliance", value, "devices", **f)


@tool("analytics")
def get_period_comparison(
    provider: DataProvider, metric: str, baseline_from: str, baseline_to: str, current_from: str, current_to: str,
    hospital_id: Optional[str] = None, department: Optional[str] = None,
) -> dict:
    """Compare a metric (tickets, corrective_maintenance, preventive_maintenance, total_maintenance, mttr_hours) between two date ranges."""
    if metric not in metrics.COMPARISON_METRICS:
        raise ValueError(f"metric must be one of {list(metrics.COMPARISON_METRICS)}, got {metric!r}")
    b_from, b_to, c_from, c_to = (to_date(x) for x in (baseline_from, baseline_to, current_from, current_to))
    if None in (b_from, b_to, c_from, c_to):
        raise ValueError("baseline_from, baseline_to, current_from and current_to are all required")
    if b_from > b_to or c_from > c_to:
        raise ValueError("each period's start date must not be after its end date")
    f = dict(metric=metric, baseline_from=baseline_from, baseline_to=baseline_to,
             current_from=current_from, current_to=current_to, hospital_id=hospital_id, department=department)
    devices = get_all_devices(provider, hospital_id, department)
    if not devices:
        return _no_data(NO_DEVICES, **f)
    tickets, maintenance = collect_tickets(provider, devices), collect_maintenance(provider, devices)
    value = metrics.compare(
        metrics.metric_value(metric, tickets, maintenance, b_from, b_to),
        metrics.metric_value(metric, tickets, maintenance, c_from, c_to),
    )
    return _result(f"period_comparison:{metric}", value, "hours" if metric == "mttr_hours" else "count", **f)


TOOLS = [
    get_mttr, get_repeated_failures, get_top_problem_devices, get_ticket_distribution,
    get_device_status_distribution, get_risk_distribution, get_preventive_compliance, get_period_comparison,
]
