"""
Phase AI-4 tests: deterministic analytics.

Run with:
    python -m pytest ai/tests/test_analytics.py -v

Two layers:
  1. A small hand-built provider with KNOWN data -> exact expected numbers.
  2. The real MockDataProvider -> consistency with the provider's own
     statistics methods (so we don't hardcode dataset values we can't see).
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ai.models.device import DeviceContext, DeviceProfile
from ai.models.maintenance import MaintenanceEvent
from ai.models.ticket import TicketContext
from ai.services.data.mock_provider import MockDataProvider
from ai.tools.registry import build_registry


def utc(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


# ---------------------------------------------------------------------
# Known dataset (as of 2026-10-04)
# ---------------------------------------------------------------------
DEVICES = [
    DeviceContext(device_id="d1", device_code="DEV-A", name="Ventilator", hospital_id="h1", hospital_name="Hosp One", department_name="ICU", status="active"),
    DeviceContext(device_id="d2", device_code="DEV-B", name="CT Scanner", hospital_id="h1", hospital_name="Hosp One", department_name="Radiology", status="under_maintenance"),
    DeviceContext(device_id="d3", device_code="DEV-C", name="Monitor", hospital_id="h2", hospital_name="Hosp Two", department_name="ICU", status="active"),
    DeviceContext(device_id="d4", device_code="DEV-D", name="Old Pump", hospital_id="h2", hospital_name="Hosp Two", department_name="ICU", status="decommissioned"),
    DeviceContext(device_id="d5", device_code="DEV-E", name="Defibrillator", hospital_id="h1", hospital_name="Hosp One", department_name="ICU", status="active"),
]


def _t(tid, dev, created, status, priority, resolved=None):
    return TicketContext(ticket_id=tid, device_id=dev, problem_description="x", priority=priority,
                         status=status, created_at=created, resolved_at=resolved)


TICKETS = [
    _t("t1", "d1", utc(2026, 8, 1, 8), "resolved", "high", utc(2026, 8, 1, 20)),    # 12h
    _t("t2", "d1", utc(2026, 9, 1, 8), "closed", "medium", utc(2026, 9, 2, 8)),     # 24h
    _t("t3", "d1", utc(2026, 9, 20, 8), "open", "critical"),
    _t("t4", "d2", utc(2026, 9, 10, 0), "resolved", "low", utc(2026, 9, 10, 6)),    # 6h
    _t("t5", "d2", utc(2026, 9, 15, 0), "cancelled", "medium"),
    _t("t6", "d3", utc(2026, 7, 5, 8), "resolved", "high", utc(2026, 7, 5, 18)),    # 10h
]

MAINT = [
    MaintenanceEvent(record_id="m1", device_id="d1", maintenance_type="preventive", description="x", performed_at=utc(2026, 9, 1)),
    MaintenanceEvent(record_id="m2", device_id="d1", maintenance_type="corrective", description="x", performed_at=utc(2026, 9, 2)),
    MaintenanceEvent(record_id="m3", device_id="d2", maintenance_type="corrective", description="x", performed_at=utc(2026, 9, 12)),
    MaintenanceEvent(record_id="m4", device_id="d3", maintenance_type="preventive", description="x", performed_at=utc(2026, 7, 6)),
]

# next_due_date per device; d5 has no schedule, d4 is decommissioned (excluded)
SCHEDULE_DUE = {"d1": "2026-09-20", "d2": "2026-10-20", "d3": "2027-01-01"}
RISK = {"d1": "critical", "d2": "high", "d3": "low"}


class KnownProvider(MockDataProvider):
    def get_devices_by_status(self, status):
        return [d for d in DEVICES if d.status == status]

    def get_device_tickets(self, device_id):
        return [t for t in TICKETS if t.device_id == device_id]

    def get_maintenance_history(self, device_id, *args, **kwargs):
        return [m for m in MAINT if m.device_id == device_id]

    def get_preventive_maintenance_status(self, device_id):
        if device_id not in SCHEDULE_DUE:
            return None
        from datetime import date
        # Duck-typed schedule: analytics only reads next_due_date / is_active.
        return SimpleNamespace(device_id=device_id, next_due_date=date.fromisoformat(SCHEDULE_DUE[device_id]), is_active=True)

    def get_devices_by_risk(self, risk_level):
        return [d for d in DEVICES if RISK.get(d.device_id) == risk_level]

    def get_device(self, device_id):
        d = next((x for x in DEVICES if x.device_id == device_id), None)
        if d is None:
            return None
        return DeviceProfile(device_id=d.device_id, device_code=d.device_code, name=d.name, qr_identifier="QR",
                             status=d.status, criticality="medium", data_as_of="2026-10-04T00:00:00")


@pytest.fixture
def reg():
    return build_registry(KnownProvider())


def value(res):
    assert res.success is True, res.error
    assert res.data["found"] is True, res.data
    return res.data["result"]["value"]


# ---------------------------------------------------------------------
# MTTR
# ---------------------------------------------------------------------
def test_mttr_overall(reg):
    v = value(reg.call("get_mttr"))
    assert v == {"mttr_hours": 13.0, "median_hours": 11.0, "min_hours": 6.0, "max_hours": 24.0, "sample_size": 4}


def test_mttr_filters_by_hospital_and_period(reg):
    assert value(reg.call("get_mttr", hospital_id="h1"))["mttr_hours"] == 14.0  # (12+24+6)/3
    v = value(reg.call("get_mttr", date_from="2026-09-01", date_to="2026-09-30"))
    assert (v["mttr_hours"], v["sample_size"]) == (15.0, 2)


def test_mttr_with_no_resolved_tickets_is_found_false(reg):
    res = reg.call("get_mttr", date_from="2030-01-01")
    assert res.success is True and res.data["found"] is False and res.data["result"] is None
    assert "cannot be computed" in res.data["message"]


# ---------------------------------------------------------------------
# Repeated failures / top problem devices (cancelled tickets don't count)
# ---------------------------------------------------------------------
def test_repeated_failures_default_threshold(reg):
    v = value(reg.call("get_repeated_failures"))
    assert [d["device_code"] for d in v["devices"]] == ["DEV-A"]
    assert v["devices"][0]["ticket_count"] == 3
    assert v["tickets_analyzed"] == 5  # 6 tickets minus 1 cancelled


def test_repeated_failures_threshold_and_period(reg):
    v = value(reg.call("get_repeated_failures", min_tickets=1, date_from="2026-09-01"))
    assert [(d["device_code"], d["ticket_count"]) for d in v["devices"]] == [("DEV-A", 2), ("DEV-B", 1)]


def test_no_repeated_failures_is_an_empty_list_not_found_false(reg):
    v = value(reg.call("get_repeated_failures", min_tickets=10))
    assert v["devices"] == [] and v["count"] == 0


def test_top_problem_devices_ranking_and_limit(reg):
    v = value(reg.call("get_top_problem_devices"))
    assert [(d["device_code"], d["ticket_count"], d["corrective_maintenance_count"]) for d in v["devices"]] == [
        ("DEV-A", 3, 1), ("DEV-B", 1, 1), ("DEV-C", 1, 0)]
    assert len(value(reg.call("get_top_problem_devices", limit=1))["devices"]) == 1


# ---------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------
def test_ticket_distribution_by_status_includes_cancelled(reg):
    v = value(reg.call("get_ticket_distribution", group_by="status"))
    assert v["total"] == 6
    assert v["counts"] == {"resolved": 3, "cancelled": 1, "closed": 1, "open": 1}


def test_ticket_distribution_by_priority_percentages(reg):
    v = value(reg.call("get_ticket_distribution", group_by="priority"))
    assert v["counts"] == {"high": 2, "medium": 2, "critical": 1, "low": 1}
    assert v["percentages"]["high"] == 33.3 and v["percentages"]["low"] == 16.7


def test_ticket_distribution_by_department_and_hospital(reg):
    assert value(reg.call("get_ticket_distribution", group_by="department"))["counts"] == {"ICU": 4, "Radiology": 2}
    assert value(reg.call("get_ticket_distribution", group_by="hospital"))["counts"] == {"Hosp One": 5, "Hosp Two": 1}


def test_ticket_distribution_filters(reg):
    assert value(reg.call("get_ticket_distribution", department="ICU"))["total"] == 4
    res = reg.call("get_ticket_distribution", date_from="2030-01-01")
    assert res.data["found"] is False


def test_device_status_distribution(reg):
    v = value(reg.call("get_device_status_distribution"))
    assert v["counts"] == {"active": 3, "decommissioned": 1, "under_maintenance": 1}
    assert value(reg.call("get_device_status_distribution", hospital_id="h2"))["total"] == 2


def test_risk_distribution_reports_unassessed(reg):
    v = value(reg.call("get_risk_distribution"))
    assert v["counts"] == {"unassessed": 2, "critical": 1, "high": 1, "low": 1}
    assert v["percentages"]["unassessed"] == 40.0


# ---------------------------------------------------------------------
# Preventive compliance
# ---------------------------------------------------------------------
def test_preventive_compliance_uses_provider_as_of(reg):
    v = value(reg.call("get_preventive_compliance"))
    assert v["as_of"] == "2026-10-04"
    assert v["devices_evaluated"] == 4  # decommissioned d4 excluded
    assert v["counts"] == {"overdue": 1, "due_soon": 1, "on_track": 1, "no_schedule": 1, "unknown_due_date": 0}
    assert v["compliance_rate_pct"] == 66.7
    assert [(d["device_code"], d["days_overdue"]) for d in v["overdue_devices"]] == [("DEV-A", 14)]


def test_preventive_compliance_explicit_as_of_and_hospital(reg):
    v = value(reg.call("get_preventive_compliance", hospital_id="h1", as_of="2026-10-04"))
    assert v["compliance_rate_pct"] == 50.0
    later = value(reg.call("get_preventive_compliance", as_of="2026-12-01"))
    assert later["counts"]["overdue"] == 2  # DEV-B's 2026-10-20 is now overdue too


def test_preventive_compliance_accepts_string_due_dates():
    """Regression: the real MaintenanceSchedule exposes next_due_date as an ISO string."""
    from datetime import date
    from ai.services.analytics.metrics import preventive_compliance

    schedules = {
        "d1": SimpleNamespace(next_due_date="2026-09-20"),
        "d2": SimpleNamespace(next_due_date="2026-10-20T00:00:00"),
        "d3": SimpleNamespace(next_due_date=""),
    }
    v = preventive_compliance(DEVICES[:3], schedules, date(2026, 10, 4))
    assert v["counts"] == {"overdue": 1, "due_soon": 1, "on_track": 0, "no_schedule": 0, "unknown_due_date": 1}


# ---------------------------------------------------------------------
# Period comparison
# ---------------------------------------------------------------------
PERIODS = dict(baseline_from="2026-08-01", baseline_to="2026-08-31", current_from="2026-09-01", current_to="2026-09-30")


def test_compare_tickets(reg):
    v = value(reg.call("get_period_comparison", metric="tickets", **PERIODS))
    assert v == {"baseline": 1, "current": 3, "absolute_change": 2, "percent_change": 200.0, "direction": "increased"}


def test_compare_with_zero_baseline_has_no_percent(reg):
    v = value(reg.call("get_period_comparison", metric="corrective_maintenance", **PERIODS))
    assert (v["baseline"], v["current"], v["percent_change"], v["direction"]) == (0, 2, None, "increased")


def test_compare_mttr(reg):
    v = value(reg.call("get_period_comparison", metric="mttr_hours", **PERIODS))
    assert (v["baseline"], v["current"], v["absolute_change"], v["percent_change"]) == (12.0, 15.0, 3.0, 25.0)


def test_compare_without_data_in_a_period_is_insufficient(reg):
    v = value(reg.call("get_period_comparison", metric="mttr_hours", **{**PERIODS, "baseline_from": "2020-01-01", "baseline_to": "2020-01-31"}))
    assert v["direction"] == "insufficient_data" and v["percent_change"] is None


# ---------------------------------------------------------------------
# Guarantees shared with every tool
# ---------------------------------------------------------------------
def test_unknown_hospital_is_found_false(reg):
    for name in ("get_mttr", "get_risk_distribution", "get_device_status_distribution", "get_preventive_compliance"):
        res = reg.call(name, hospital_id="nope")
        assert res.success is True and res.data["found"] is False, name
        assert res.data["message"] == "No devices match the given filters."


def test_filters_are_echoed_back(reg):
    res = reg.call("get_ticket_distribution", group_by="priority", department="ICU")
    assert res.data["result"]["filters_applied"] == {"group_by": "priority", "department": "ICU"}


@pytest.mark.parametrize("name,kwargs", [
    ("get_ticket_distribution", {"group_by": "color"}),
    ("get_repeated_failures", {"min_tickets": 0}),
    ("get_top_problem_devices", {"limit": 0}),
    ("get_mttr", {"date_from": "not-a-date"}),
    ("get_period_comparison", {"metric": "vibes", **PERIODS}),
    ("get_period_comparison", {"metric": "tickets", **{**PERIODS, "current_from": "2026-10-01", "current_to": "2026-09-01"}}),
])
def test_bad_arguments_become_failed_toolresults(reg, name, kwargs):
    res = reg.call(name, **kwargs)
    assert res.success is False and res.error


def test_provider_fault_becomes_failed_toolresult():
    class Down(KnownProvider):
        def get_devices_by_status(self, status):
            raise ConnectionError("backend unreachable")

    res = build_registry(Down()).call("get_mttr")
    assert res.success is False and "backend unreachable" in res.error


# ---------------------------------------------------------------------
# Against the real mock dataset: must agree with the provider's own stats
# ---------------------------------------------------------------------
@pytest.fixture
def mock_reg():
    return build_registry(MockDataProvider())


def test_ticket_total_matches_provider_statistics(mock_reg):
    expected = mock_reg.call("get_ticket_statistics").data["statistics"]
    v = value(mock_reg.call("get_ticket_distribution", group_by="status"))
    assert v["total"] == expected["total"]
    assert v["counts"] == expected["by_status"]


def test_risk_distribution_matches_provider_statistics(mock_reg):
    expected = mock_reg.call("get_risk_statistics").data["statistics"]
    assert value(mock_reg.call("get_risk_distribution"))["counts"] == expected


def test_total_maintenance_matches_provider_statistics(mock_reg):
    expected = mock_reg.call("get_maintenance_statistics").data["statistics"]["total"]
    v = value(mock_reg.call("get_period_comparison", metric="total_maintenance",
                            baseline_from="2000-01-01", baseline_to="2000-12-31",
                            current_from="2000-01-01", current_to="2100-01-01"))
    assert v["current"] == expected


def test_every_analytics_tool_runs_on_mock_data(mock_reg):
    calls = [
        ("get_mttr", {}), ("get_repeated_failures", {}), ("get_top_problem_devices", {}),
        ("get_ticket_distribution", {}), ("get_device_status_distribution", {}), ("get_risk_distribution", {}),
        ("get_preventive_compliance", {}),
        ("get_period_comparison", {"metric": "tickets", **PERIODS}),
    ]
    assert len(calls) == len(mock_reg.by_category("analytics"))
    for name, kwargs in calls:
        res = mock_reg.call(name, **kwargs)
        assert res.success is True, f"{name}: {res.error}"
