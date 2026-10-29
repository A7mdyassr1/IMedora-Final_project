"""
Pure analytics computations - lists in, plain dicts out. No provider, no
I/O, no LLM. Conventions (stated so every number is reproducible):

- A "failure" is a ticket that is not cancelled.
- MTTR = mean hours from created_at to resolved_at over resolved/closed
  tickets, bucketed by RESOLUTION date.
- Date filters are inclusive; tickets bucket by created_at, maintenance
  by performed_at.
- Percentages are rounded to 1 decimal, hours to 2.
"""
from collections import Counter
from datetime import date, datetime, timezone
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

RESOLVED_STATUSES = ("resolved", "closed")
GROUP_BY_OPTIONS = ("status", "priority", "department", "hospital")
COMPARISON_METRICS = ("tickets", "corrective_maintenance", "preventive_maintenance", "total_maintenance", "mttr_hours")


def _as_date(value: Union[date, datetime, str]) -> date:
    """Accepts date, datetime or an ISO string (the real schedule model stores due dates as text)."""
    if isinstance(value, str):
        return date.fromisoformat(value.strip()[:10])
    return value.date() if isinstance(value, datetime) else value


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def in_period(value: Optional[Union[date, datetime]], date_from: Optional[date], date_to: Optional[date]) -> bool:
    if value is None:
        return False
    d = _as_date(value)
    if date_from and d < date_from:
        return False
    if date_to and d > date_to:
        return False
    return True


def _device_row(dev: Any) -> Dict[str, Any]:
    return {
        "device_id": dev.device_id, "device_code": dev.device_code, "name": dev.name,
        "department": dev.department_name, "hospital": dev.hospital_name or dev.hospital_id,
    }


def failure_tickets(tickets: Sequence[Any], date_from: Optional[date] = None, date_to: Optional[date] = None) -> List[Any]:
    return [t for t in tickets if t.status != "cancelled" and in_period(t.created_at, date_from, date_to)]


def mttr(tickets: Sequence[Any], date_from: Optional[date] = None, date_to: Optional[date] = None) -> Optional[Dict[str, Any]]:
    hours = [
        (_aware(t.resolved_at) - _aware(t.created_at)).total_seconds() / 3600
        for t in tickets
        if t.status in RESOLVED_STATUSES and t.resolved_at is not None and in_period(t.resolved_at, date_from, date_to)
    ]
    if not hours:
        return None
    return {
        "mttr_hours": round(mean(hours), 2), "median_hours": round(median(hours), 2),
        "min_hours": round(min(hours), 2), "max_hours": round(max(hours), 2), "sample_size": len(hours),
    }


def repeated_failures(
    tickets: Sequence[Any], devices: Sequence[Any], min_tickets: int = 2,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
) -> Dict[str, Any]:
    by_dev = {d.device_id: d for d in devices}
    counts: Counter = Counter()
    last: Dict[str, datetime] = {}
    for t in failure_tickets(tickets, date_from, date_to):
        if t.device_id not in by_dev:
            continue
        counts[t.device_id] += 1
        ts = _aware(t.created_at)
        if t.device_id not in last or ts > last[t.device_id]:
            last[t.device_id] = ts
    rows = [
        {**_device_row(by_dev[did]), "ticket_count": c, "last_ticket_at": last[did].isoformat()}
        for did, c in counts.items() if c >= min_tickets
    ]
    rows.sort(key=lambda r: (-r["ticket_count"], r["device_code"]))
    return {"min_tickets": min_tickets, "devices": rows, "count": len(rows), "tickets_analyzed": sum(counts.values())}


def rank_problem_devices(
    tickets: Sequence[Any], maintenance: Sequence[Any], devices: Sequence[Any], limit: int = 5,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
) -> Dict[str, Any]:
    by_dev = {d.device_id: d for d in devices}
    t_counts = Counter(t.device_id for t in failure_tickets(tickets, date_from, date_to))
    c_counts = Counter(
        m.device_id for m in maintenance
        if m.maintenance_type == "corrective" and in_period(m.performed_at, date_from, date_to)
    )
    rows = [
        {**_device_row(by_dev[did]), "ticket_count": t_counts.get(did, 0), "corrective_maintenance_count": c_counts.get(did, 0)}
        for did in set(t_counts) | set(c_counts) if did in by_dev
    ]
    rows.sort(key=lambda r: (-r["ticket_count"], -r["corrective_maintenance_count"], r["device_code"]))
    return {"ranked_by": "ticket_count, then corrective_maintenance_count", "limit": limit,
            "total_devices_with_problems": len(rows), "devices": rows[:limit]}


def distribution(values: Iterable[str]) -> Dict[str, Any]:
    counter = Counter(values)
    total = sum(counter.values())
    items = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return {
        "total": total, "counts": dict(items),
        "percentages": {k: round(v / total * 100, 1) for k, v in items},
    }


def ticket_group_keys(tickets: Sequence[Any], devices: Sequence[Any], group_by: str) -> List[str]:
    if group_by not in GROUP_BY_OPTIONS:
        raise ValueError(f"group_by must be one of {list(GROUP_BY_OPTIONS)}, got {group_by!r}")
    by_dev = {d.device_id: d for d in devices}
    keys: List[str] = []
    for t in tickets:
        dev = by_dev.get(t.device_id)
        if group_by == "status":
            keys.append(t.status)
        elif group_by == "priority":
            keys.append(t.priority)
        elif group_by == "department":
            keys.append((dev.department_name if dev else None) or "unknown")
        else:
            keys.append(((dev.hospital_name or dev.hospital_id) if dev else None) or "unknown")
    return keys


def preventive_compliance(
    devices: Sequence[Any], schedules: Dict[str, Any], as_of: date, due_soon_days: int = 30,
) -> Dict[str, Any]:
    """Devices are bucketed by their preventive schedule's next_due_date vs `as_of`.
    Decommissioned devices are excluded. Compliance = not overdue, among devices with a known due date."""
    counts = {"overdue": 0, "due_soon": 0, "on_track": 0, "no_schedule": 0, "unknown_due_date": 0}
    overdue: List[Dict[str, Any]] = []
    evaluated = 0
    for dev in devices:
        if dev.status == "decommissioned":
            continue
        evaluated += 1
        schedule = schedules.get(dev.device_id)
        if schedule is None or getattr(schedule, "is_active", True) is False:
            counts["no_schedule"] += 1
            continue
        due = getattr(schedule, "next_due_date", None)
        if due is None or (isinstance(due, str) and not due.strip()):
            counts["unknown_due_date"] += 1
            continue
        days = (_as_date(due) - as_of).days
        if days < 0:
            counts["overdue"] += 1
            overdue.append({**_device_row(dev), "next_due_date": _as_date(due).isoformat(), "days_overdue": -days})
        elif days <= due_soon_days:
            counts["due_soon"] += 1
        else:
            counts["on_track"] += 1
    scheduled = counts["overdue"] + counts["due_soon"] + counts["on_track"]
    overdue.sort(key=lambda r: (-r["days_overdue"], r["device_code"]))
    return {
        "as_of": as_of.isoformat(), "due_soon_days": due_soon_days, "devices_evaluated": evaluated,
        "counts": counts,
        "compliance_rate_pct": round((counts["due_soon"] + counts["on_track"]) / scheduled * 100, 1) if scheduled else None,
        "overdue_devices": overdue,
    }


def metric_value(
    metric: str, tickets: Sequence[Any], maintenance: Sequence[Any], date_from: date, date_to: date,
) -> Optional[Union[int, float]]:
    if metric not in COMPARISON_METRICS:
        raise ValueError(f"metric must be one of {list(COMPARISON_METRICS)}, got {metric!r}")
    if metric == "tickets":
        return len(failure_tickets(tickets, date_from, date_to))
    if metric == "mttr_hours":
        result = mttr(tickets, date_from, date_to)
        return result["mttr_hours"] if result else None
    events = [m for m in maintenance if in_period(m.performed_at, date_from, date_to)]
    if metric == "corrective_maintenance":
        events = [m for m in events if m.maintenance_type == "corrective"]
    elif metric == "preventive_maintenance":
        events = [m for m in events if m.maintenance_type == "preventive"]
    return len(events)


def compare(baseline: Optional[Union[int, float]], current: Optional[Union[int, float]]) -> Dict[str, Any]:
    if baseline is None or current is None:
        return {"baseline": baseline, "current": current, "absolute_change": None,
                "percent_change": None, "direction": "insufficient_data"}
    delta = round(current - baseline, 2)
    return {
        "baseline": baseline, "current": current, "absolute_change": delta,
        "percent_change": round(delta / baseline * 100, 1) if baseline else None,
        "direction": "increased" if delta > 0 else "decreased" if delta < 0 else "unchanged",
    }
