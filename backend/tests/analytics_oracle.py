"""Independent expected values for the B10 tests: the AI package's metric rules
(`ai/services/analytics/metrics.py` on main) re-implemented in plain Python over the scene's dataset
(tests/analytics_scene.py). Nothing here touches the database or the code under test.
"""
from collections import Counter
from datetime import date, timedelta
from statistics import mean, median
from zoneinfo import ZoneInfo

from tests.analytics_scene import DEVICES, INVENTORY, QA, RECORDS, SCHEDULES, TICKETS

STATUSES = ["active", "under_maintenance", "out_of_service", "decommissioned"]
LEVELS = ["low", "medium", "high", "critical"]
TICKET_STATUSES = ["open", "assigned", "in_progress", "waiting_for_parts", "resolved", "closed", "cancelled"]
OPEN_STATUSES = ["open", "assigned", "in_progress", "waiting_for_parts"]
DEPT_NAMES = {"icu": "ICU", "lab": "Lab", "rad": "Radiology", "odept": "Other Dept"}


class Oracle:
    def __init__(self, db_tz: str, today: date, hospitals, department=None, include_archived=False):
        self.tz = ZoneInfo(db_tz)
        self.today = today
        self.devices = [k for k, (h, d, _m, _s, _c, _r, archived) in DEVICES.items()
                        if h in hospitals and (department is None or d == department)
                        and (include_archived or not archived)]

    def day(self, dt) -> date:
        return dt.astimezone(self.tz).date()

    def in_period(self, dt, period) -> bool:
        return dt is not None and date.fromisoformat(period[0]) <= self.day(dt) <= date.fromisoformat(period[1])

    @staticmethod
    def dist(values, keys):
        c = Counter(values)
        counts = {k: c.get(k, 0) for k in keys}
        total = sum(counts.values())
        return {"total": total, "counts": counts,
                "percentages": {k: (round(v / total * 100, 1) if total else None) for k, v in counts.items()}}

    # ---- devices ----------------------------------------------------------------------------------
    def device_stats(self, category_names):
        rows = [DEVICES[k] for k in self.devices]
        by_dept = Counter(DEPT_NAMES[r[1]] for r in rows)
        by_cat = Counter(category_names[r[2]] for r in rows)
        order = lambda c: sorted(([n, v] for n, v in c.items()), key=lambda x: (-x[1], x[0]))  # noqa: E731
        return {
            "total": len(rows),
            "by_status": self.dist([r[3] for r in rows], STATUSES),
            "by_risk_level": self.dist([r[5] or "unassessed" for r in rows], LEVELS + ["unassessed"]),
            "by_criticality": self.dist([r[4] for r in rows], LEVELS),
            "by_department": order(by_dept),
            "by_category": order(by_cat),
        }

    # ---- tickets ----------------------------------------------------------------------------------
    def tickets(self):
        """Tickets of the visible devices, admin-deleted ones never."""
        return {k: t for k, t in TICKETS.items() if t[0] in self.devices and not t[5]}

    def failures(self, period):
        return {k: t for k, t in self.tickets().items() if t[2] != "cancelled" and self.in_period(t[1], period)}

    def mttr(self, period):
        hours = [(t[4] - t[1]).total_seconds() / 3600 for t in self.tickets().values()
                 if t[2] in ("resolved", "closed") and t[4] is not None and self.in_period(t[4], period)]
        if not hours:
            return None
        return {"mttr_hours": round(mean(hours), 2), "median_hours": round(median(hours), 2),
                "min_hours": round(min(hours), 2), "max_hours": round(max(hours), 2), "sample_size": len(hours)}

    def ticket_stats(self, period):
        created = {k: t for k, t in self.tickets().items() if self.in_period(t[1], period)}
        return {
            "created": self.dist([t[2] for t in created.values()], TICKET_STATUSES),
            "by_priority": self.dist([t[3] for t in created.values()], LEVELS),
            "failures": len(self.failures(period)),
            "resolved": sum(1 for t in self.tickets().values()
                            if t[2] in ("resolved", "closed") and self.in_period(t[4], period)),
            "open_now": self.dist([t[2] for t in self.tickets().values() if t[2] in OPEN_STATUSES], OPEN_STATUSES),
            "mttr": self.mttr(period),
        }

    # ---- maintenance ------------------------------------------------------------------------------
    def records(self, period):
        return {k: r for k, r in RECORDS.items() if r[0] in self.devices and self.in_period(r[2], period)}

    def by_type(self, period, type_names):
        c = Counter(type_names[r[1]] for r in self.records(period).values())
        return sorted(([n, v] for n, v in c.items()), key=lambda x: (-x[1], x[0]))

    def compliance(self, due_soon_days=30):
        counts = {"overdue": 0, "due_soon": 0, "on_track": 0, "no_schedule": 0, "unknown_due_date": 0}
        overdue = []
        evaluated = 0
        for k in self.devices:
            if DEVICES[k][3] == "decommissioned":
                continue
            evaluated += 1
            sched = [s for s in SCHEDULES if s[0] == k and s[1] == "preventive" and s[3]]
            if not sched:
                counts["no_schedule"] += 1
                continue
            days = sched[0][2]
            if days < 0:
                counts["overdue"] += 1
                overdue.append((k, -days))
            elif days <= due_soon_days:
                counts["due_soon"] += 1
            else:
                counts["on_track"] += 1
        scheduled = counts["overdue"] + counts["due_soon"] + counts["on_track"]
        overdue.sort(key=lambda x: (-x[1], x[0]))
        return {"devices_evaluated": evaluated, "counts": counts,
                "compliance_rate_pct": round((counts["due_soon"] + counts["on_track"]) / scheduled * 100, 1)
                if scheduled else None,
                "overdue": overdue}

    def schedules_due(self, due_soon_days=30):
        """Active schedules (any type) of visible, not decommissioned devices: overdue / due soon."""
        rows = [s for s in SCHEDULES if s[0] in self.devices and s[3] and DEVICES[s[0]][3] != "decommissioned"]
        return {"overdue": sum(1 for s in rows if s[2] < 0),
                "due_soon": sum(1 for s in rows if 0 <= s[2] <= due_soon_days)}

    # ---- problem devices --------------------------------------------------------------------------
    def problem_devices(self, period, min_tickets=0):
        t_counts = Counter(t[0] for t in self.failures(period).values())
        c_counts = Counter(r[0] for r in self.records(period).values() if r[1] == "corrective")
        last = {}
        for t in self.failures(period).values():
            last[t[0]] = max(last.get(t[0], t[1]), t[1])
        rows = [(k, t_counts.get(k, 0), c_counts.get(k, 0)) for k in set(t_counts) | set(c_counts)
                if t_counts.get(k, 0) >= min_tickets]
        rows.sort(key=lambda r: (-r[1], -r[2], r[0]))
        return rows, last

    # ---- inventory --------------------------------------------------------------------------------
    @staticmethod
    def inventory(hospitals):
        rows = [r for r in INVENTORY if r[0] in hospitals]
        low = [r for r in rows if r[3] is not None and r[2] <= r[3]]
        return {"items_tracked": len(rows), "parts_tracked": len({r[1] for r in rows}),
                "total_units_on_hand": sum(r[2] for r in rows), "low_stock_count": len(low),
                "out_of_stock_count": sum(1 for r in rows if r[2] == 0), "low": low}

    @staticmethod
    def low_stock(hospitals, part_numbers, hospital_names):
        """Low rows as (part key, hospital key, qty, threshold), emptiest first, then part number, hospital."""
        low = Oracle.inventory(hospitals)["low"]
        return sorted(((r[1], r[0], r[2], r[3]) for r in low),
                      key=lambda r: (r[2], part_numbers[r[0]], hospital_names[r[1]]))

    # ---- trends -------------------------------------------------------------------------------------
    def trend(self, metric, interval, period):
        """[start, end, value, sample_size] per bucket: the same rule as the period endpoints, applied to each
        bucket's days (the AI package's metric_value per sub-period)."""
        start, end = date.fromisoformat(period[0]), date.fromisoformat(period[1])
        if interval == "day":
            first, step = start, lambda d: d + timedelta(days=1)
        elif interval == "week":
            first, step = week_start(start), lambda d: d + timedelta(days=7)
        else:
            first = start.replace(day=1)
            step = lambda d: (d.replace(day=28) + timedelta(days=4)).replace(day=1)  # noqa: E731
        points, b = [], first
        while b <= end:
            nxt = step(b)
            lo, hi = max(b, start), min(nxt - timedelta(days=1), end)
            sub = (lo.isoformat(), hi.isoformat())
            if metric == "tickets":
                value = n = len(self.failures(sub))
            elif metric == "mttr_hours":
                m = self.mttr(sub)
                value, n = (m["mttr_hours"], m["sample_size"]) if m else (None, 0)
            else:
                kinds = {"corrective_maintenance": {"corrective"}, "preventive_maintenance": {"preventive"},
                         "total_maintenance": {"corrective", "preventive", "other"}}[metric]
                value = n = sum(1 for r in self.records(sub).values() if r[1] in kinds)
            points.append([lo.isoformat(), hi.isoformat(), value, n])
            b = nxt
        return points

    # ---- QA -----------------------------------------------------------------------------------------
    def qa(self):
        return Counter(s for d, s in QA if d in self.devices)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())
