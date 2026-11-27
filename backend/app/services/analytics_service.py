"""Dashboard & analytics (B10). Business rules on top of AnalyticsRepository's SQL aggregates.

- **Who:** staff only (team decision 2026-11-27): administrators (organization), biomedical engineers
  and technicians (own hospital). Department users get 403, as on risk and QA (B6). The role is
  checked before anything is read.
- **Archived devices:** only for administrators who ask (`include_archived`); otherwise 403.
- **Metric rules:** those of the AI package (`ai/services/analytics/metrics.py` on main), so the
  dashboard and the AI assistant give the same numbers (see `docs/api/analytics.md`).
"""
from datetime import date, timedelta
import uuid
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import Criticality, DeviceStatus, QAStatus, RiskLevel, TicketPriority, TicketStatus
from app.core.exceptions import AppError
from app.repositories.analytics_repository import CORRECTIVE, OPEN, PREVENTIVE, AnalyticsFilters, AnalyticsRepository
from app.services.risk_service import require_archived_access, require_reader

WHAT = "Dashboard and analytics"
UNASSESSED = "unassessed"
DEFAULT_PERIOD_DAYS = 30
COMPLIANCE_KEYS = ("overdue", "due_soon", "on_track", "no_schedule", "unknown_due_date")
RANKED_BY = "ticket_count, then corrective_maintenance_count, then device_code"
MAX_DAY_BUCKETS = 366          # team decision 2026-11-27: day trends cover at most 366 days,
MAX_MONTHS = 24                # week / month trends at most 24 calendar months


class AnalyticsQueryError(AppError):
    """A query value the schema cannot check on its own (e.g. date_from after date_to): the normal 422."""
    status_code = 422
    code = "validation_error"
    default_message = "Request validation failed."


def distribution(counts: Dict[str, int], keys: Iterable[str]) -> dict:
    """Every key present (zeros included), in the given order; percentages of the total, 1 decimal."""
    ordered = {k: counts.get(k, 0) for k in keys}
    total = sum(ordered.values())
    return {"total": total, "counts": ordered,
            "percentages": {k: (round(v / total * 100, 1) if total else None) for k, v in ordered.items()}}


# Accepted dates. Far beyond any real data; keeps the date arithmetic (end + 1 day, the default start, the next
# month) inside Python's date range, so an extreme date is a 422 instead of an OverflowError (500).
MIN_DATE, MAX_DATE = date(1900, 1, 1), date(2999, 12, 31)


def check_dates(date_from: Optional[date], date_to: Optional[date]) -> None:
    for field, value in (("date_from", date_from), ("date_to", date_to)):
        if value is not None and not MIN_DATE <= value <= MAX_DATE:
            raise AnalyticsQueryError(details=[{"field": f"query.{field}", "message":
                                                f"{field} must be between {MIN_DATE} and {MAX_DATE}"}])


def resolve_period(today: date, date_from: Optional[date], date_to: Optional[date]) -> Tuple[date, date]:
    """Default: the last 30 days ending today (database date). date_from after date_to is a 422."""
    check_dates(date_from, date_to)
    end = date_to or today
    start = date_from or end - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    if start > end:
        raise AnalyticsQueryError(details=[{"field": "query.date_from",
                                            "message": "date_from must not be after date_to"}])
    return start, end


def bucket_start(interval: str, d: date) -> date:
    """date_trunc() in Python: the day, the ISO week's Monday, or the 1st of the month."""
    if interval == "week":
        return d - timedelta(days=d.weekday())
    if interval == "month":
        return d.replace(day=1)
    return d


def next_bucket(interval: str, d: date) -> date:
    if interval == "week":
        return d + timedelta(days=7)
    if interval == "month":
        return date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return d + timedelta(days=1)


def months_spanned(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def trend_period(today: date, interval: str, date_from: Optional[date], date_to: Optional[date]) -> Tuple[date, date]:
    """Default: the last 30 days (day), the last 12 weeks from a Monday (week) or the last 12 months from the
    1st (month), ending on date_to (default today). Bounded so a response stays small."""
    check_dates(date_from, date_to)
    end = date_to or today
    start = date_from
    if start is None:
        if interval == "day":
            start = end - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
        elif interval == "week":
            start = bucket_start("week", end) - timedelta(weeks=11)
        else:
            first = end.replace(day=1)
            start = date(first.year - (1 if first.month <= 11 else 0), (first.month - 12) % 12 + 1, 1)
    start, end = resolve_period(today, start, end)
    if interval == "day" and (end - start).days + 1 > MAX_DAY_BUCKETS:
        raise AnalyticsQueryError(details=[{"field": "query.date_from", "message":
                                            f"a day trend covers at most {MAX_DAY_BUCKETS} days"}])
    if interval != "day" and months_spanned(start, end) > MAX_MONTHS:
        raise AnalyticsQueryError(details=[{"field": "query.date_from", "message":
                                            f"a {interval} trend covers at most {MAX_MONTHS} calendar months"}])
    return start, end


class AnalyticsService:
    def __init__(self, db: Session):
        self.repo = AnalyticsRepository(db)

    @staticmethod
    def _check(scope: AccessScope, f: AnalyticsFilters) -> None:
        require_reader(scope, WHAT)                       # role first: 403 before anything is read
        require_archived_access(scope, f.include_archived)

    @staticmethod
    def _filters(f: AnalyticsFilters) -> dict:
        return {"hospital_id": f.hospital_id, "department_id": f.department_id, "include_archived": f.include_archived}

    # ---- CP1 -------------------------------------------------------------------------------------
    def _device_counts(self, scope: AccessScope, f: AnalyticsFilters) -> Tuple[dict, dict, dict]:
        status: Dict[str, int] = {}
        risk: Dict[str, int] = {}
        criticality: Dict[str, int] = {}
        for s, r, c, n in self.repo.device_breakdown(scope, f):
            status[s] = status.get(s, 0) + n
            risk[r or UNASSESSED] = risk.get(r or UNASSESSED, 0) + n
            criticality[c] = criticality.get(c, 0) + n
        return status, risk, criticality

    def devices(self, scope: AccessScope, f: AnalyticsFilters) -> dict:
        self._check(scope, f)
        status, risk, criticality = self._device_counts(scope, f)
        return {
            "filters": self._filters(f),
            "total": sum(status.values()),
            "by_status": distribution(status, [s.value for s in DeviceStatus]),
            "by_risk_level": distribution(risk, [*(r.value for r in RiskLevel), UNASSESSED]),
            "by_criticality": distribution(criticality, [c.value for c in Criticality]),
            "by_department": [{"id": i, "name": n, "count": c} for i, n, c in self.repo.devices_by_department(scope, f)],
            "by_category": [{"id": i, "name": n, "count": c} for i, n, c in self.repo.devices_by_category(scope, f)],
        }

    # ---- CP2 -------------------------------------------------------------------------------------
    def _period(self, date_from: Optional[date], date_to: Optional[date]) -> Tuple[date, date, date]:
        today = self.repo.today()
        start, end = resolve_period(today, date_from, date_to)
        return today, start, end

    def _compliance(self, scope: AccessScope, f: AnalyticsFilters, today: date,
                    due_soon_days: int) -> Tuple[dict, Optional[float]]:
        buckets = self.repo.preventive_buckets(scope, f, today, due_soon_days)
        counts = {k: buckets.get(k, 0) for k in COMPLIANCE_KEYS}
        scheduled = counts["overdue"] + counts["due_soon"] + counts["on_track"]
        rate = round((counts["due_soon"] + counts["on_track"]) / scheduled * 100, 1) if scheduled else None
        return counts, rate

    def maintenance(self, scope: AccessScope, f: AnalyticsFilters, date_from: Optional[date], date_to: Optional[date],
                    due_soon_days: int, limit: int) -> dict:
        self._check(scope, f)
        today, start, end = self._period(date_from, date_to)
        by_type = self.repo.records_by_type(scope, f, start, end)
        counts, rate = self._compliance(scope, f, today, due_soon_days)
        overdue = self.repo.preventive_overdue(scope, f, today, limit) if counts["overdue"] else []
        return {
            "filters": self._filters(f), "period": {"date_from": start, "date_to": end},
            "total": sum(n for _, _, n in by_type),
            "preventive": sum(n for _, name, n in by_type if name.lower() == PREVENTIVE),
            "corrective": sum(n for _, name, n in by_type if name.lower() == CORRECTIVE),
            "by_type": [{"id": i, "name": name, "count": n} for i, name, n in by_type],
            "preventive_compliance": {
                "as_of": today, "due_soon_days": due_soon_days, "devices_evaluated": sum(counts.values()),
                "counts": counts,
                "compliance_rate_pct": rate,
                "overdue_total": counts["overdue"],
                "overdue_devices": [
                    {"device_id": i, "device_code": code, "name": name, "department": dept, "hospital": hosp,
                     "next_due_date": due, "days_overdue": (today - due).days}
                    for i, code, name, dept, hosp, due in overdue],
            },
        }

    def tickets(self, scope: AccessScope, f: AnalyticsFilters, date_from: Optional[date], date_to: Optional[date]) -> dict:
        self._check(scope, f)
        _, start, end = self._period(date_from, date_to)
        status: Dict[str, int] = {}
        priority: Dict[str, int] = {}
        for s, p, n in self.repo.tickets_created(scope, f, start, end):
            status[s] = status.get(s, 0) + n
            priority[p] = priority.get(p, 0) + n
        resolved, hours = self.repo.resolution(scope, f, start, end)
        open_now: Dict[str, int] = {}
        for s, _, n in self.repo.tickets_open(scope, f):
            open_now[s] = open_now.get(s, 0) + n
        return {
            "filters": self._filters(f), "period": {"date_from": start, "date_to": end},
            "created": distribution(status, [t.value for t in TicketStatus]),
            "by_priority": distribution(priority, [p.value for p in TicketPriority]),
            "by_department": [{"id": i, "name": n, "count": c}
                              for i, n, c in self.repo.tickets_by_department(scope, f, start, end)],
            "failures": sum(n for s, n in status.items() if s != TicketStatus.CANCELLED.value),
            "resolved": resolved,
            "open_now": distribution(open_now, [t.value for t in OPEN]),
            "mttr": None if hours is None else {
                "mttr_hours": round(hours[0], 2), "median_hours": round(hours[1], 2),
                "min_hours": round(hours[2], 2), "max_hours": round(hours[3], 2), "sample_size": resolved},
        }

    def problem_devices(self, scope: AccessScope, f: AnalyticsFilters, date_from: Optional[date],
                        date_to: Optional[date], min_tickets: int, limit: int) -> dict:
        self._check(scope, f)
        _, start, end = self._period(date_from, date_to)
        total, rows = self.repo.problem_devices(scope, f, start, end, min_tickets, limit)
        return {
            "filters": self._filters(f), "period": {"date_from": start, "date_to": end},
            "ranked_by": RANKED_BY, "min_tickets": min_tickets, "total_devices": total,
            "devices": [{"device_id": i, "device_code": code, "name": name, "department": dept, "hospital": hosp,
                         "ticket_count": t, "corrective_maintenance_count": c, "last_ticket_at": last}
                        for i, code, name, dept, hosp, t, c, last in rows],
        }

    # ---- CP3 -------------------------------------------------------------------------------------
    def inventory(self, scope: AccessScope, hospital_id: Optional[uuid.UUID], limit: int) -> dict:
        """Spare-part stock in the B5 inventory scope (stock belongs to a hospital, not to a department)."""
        require_reader(scope, WHAT)
        rows, parts, units, low, empty = self.repo.stock_totals(scope, hospital_id)
        return {
            "hospital_id": hospital_id, "items_tracked": rows, "parts_tracked": parts, "total_units_on_hand": units,
            "low_stock_count": low, "out_of_stock_count": empty,
            "low_stock": [{"inventory_id": i, "part_id": p, "part_number": pn, "part_name": name, "unit": unit,
                           "hospital_id": h, "hospital": hn, "quantity_on_hand": q, "reorder_threshold": t}
                          for i, p, pn, name, unit, h, hn, q, t in
                          (self.repo.low_stock(scope, hospital_id, limit) if low else [])],
        }

    def trends(self, scope: AccessScope, f: AnalyticsFilters, metric: str, interval: str, date_from: Optional[date],
               date_to: Optional[date]) -> dict:
        self._check(scope, f)
        start, end = trend_period(self.repo.today(), interval, date_from, date_to)
        found = self.repo.trend(scope, f, metric, interval, start, end)
        points: List[dict] = []
        b = bucket_start(interval, start)
        while b <= end:
            nxt = next_bucket(interval, b)
            value, n = found.get(b, (None, 0))
            if metric == "mttr_hours":
                value = None if value is None else round(value, 2)
            else:
                value = n
            points.append({"start": max(b, start), "end": min(nxt - timedelta(days=1), end), "value": value,
                           "sample_size": n})
            b = nxt
        return {"filters": self._filters(f), "metric": metric, "interval": interval,
                "period": {"date_from": start, "date_to": end}, "points": points}

    # ---- CP4 -------------------------------------------------------------------------------------
    def overview(self, scope: AccessScope, f: AnalyticsFilters, date_from: Optional[date], date_to: Optional[date],
                 due_soon_days: int) -> dict:
        """The dashboard's first screen: the same numbers as the detail endpoints, in one call (a fixed number
        of aggregate queries)."""
        self._check(scope, f)
        today, start, end = self._period(date_from, date_to)
        status, risk, _ = self._device_counts(scope, f)
        open_status: Dict[str, int] = {}
        open_priority: Dict[str, int] = {}
        for s, p, n in self.repo.tickets_open(scope, f):
            open_status[s] = open_status.get(s, 0) + n
            open_priority[p] = open_priority.get(p, 0) + n
        stock_rows, _, _, low, empty = self.repo.stock_totals(scope, f.hospital_id)
        created = self.repo.tickets_created(scope, f, start, end)
        resolved, hours = self.repo.resolution(scope, f, start, end)
        by_type = self.repo.records_by_type(scope, f, start, end)
        _, rate = self._compliance(scope, f, today, due_soon_days)
        return {
            "filters": self._filters(f), "period": {"date_from": start, "date_to": end},
            "devices": {"total": sum(status.values()),
                        "by_status": distribution(status, [s.value for s in DeviceStatus]),
                        "by_risk_level": distribution(risk, [*(r.value for r in RiskLevel), UNASSESSED])},
            "open_tickets": {"by_status": distribution(open_status, [t.value for t in OPEN]),
                             "by_priority": distribution(open_priority, [p.value for p in TicketPriority])},
            "schedules": {"as_of": today, "due_soon_days": due_soon_days,
                          **self.repo.schedules_due(scope, f, today, due_soon_days)},
            "inventory": {"items_tracked": stock_rows, "low_stock_count": low, "out_of_stock_count": empty},
            "qa": distribution(self.repo.qa_by_status(scope, f), [s.value for s in QAStatus]),
            "activity": {
                "failures": sum(n for s, _, n in created if s != TicketStatus.CANCELLED.value),
                "tickets_resolved": resolved,
                "mttr_hours": None if hours is None else round(hours[0], 2),
                "maintenance_performed": sum(n for _, _, n in by_type),
                "preventive": sum(n for _, name, n in by_type if name.lower() == PREVENTIVE),
                "corrective": sum(n for _, name, n in by_type if name.lower() == CORRECTIVE),
                "preventive_compliance_rate_pct": rate,
            },
        }
