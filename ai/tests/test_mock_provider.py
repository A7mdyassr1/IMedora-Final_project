"""
Phase AI-2 tests: MockDataProvider.

Run with:
    python -m pytest ai/tests/test_mock_provider.py -v
"""
from datetime import date

import pytest

from ai.services.data.mock_provider import MockDataProvider


@pytest.fixture
def provider():
    return MockDataProvider()


# ---------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------
def test_get_device_matches_the_known_example_from_the_project_brief(provider):
    # The project brief's own example: "DEV-001 Philips Ventilator Status:
    # Active Criticality: Critical Risk: Critical"
    profile = provider.get_device("dev-001")
    assert profile is not None
    assert profile.device_code == "DEV-001"
    assert profile.manufacturer == "Philips"
    assert profile.status == "active"
    assert profile.criticality == "critical"
    assert profile.current_risk_level == "critical"


def test_get_device_second_example(provider):
    # "DEV-002 CT Scanner Status: Active Criticality: High Risk: High"
    profile = provider.get_device("dev-002")
    assert profile.category == "CT Scanner"
    assert profile.status == "active"
    assert profile.criticality == "high"
    assert profile.current_risk_level == "high"


def test_get_device_unknown_returns_none_not_an_error(provider):
    assert provider.get_device("does-not-exist") is None


def test_get_device_profile_is_consistent_with_get_device(provider):
    assert provider.get_device_profile("dev-001") == provider.get_device("dev-001")


def test_search_devices_by_name_fragment(provider):
    results = provider.search_devices("ventilator")
    assert any(r.device_code == "DEV-001" for r in results)


def test_search_devices_by_code(provider):
    results = provider.search_devices("DEV-005")
    assert len(results) == 1
    assert results[0].name == "MRI Scanner"


def test_get_devices_by_status(provider):
    out_of_service = provider.get_devices_by_status("out_of_service")
    assert len(out_of_service) == 1
    assert out_of_service[0].device_code == "DEV-007"


def test_get_devices_by_risk(provider):
    critical = provider.get_devices_by_risk("critical")
    codes = {d.device_code for d in critical}
    assert codes == {"DEV-001", "DEV-007"}


def test_get_devices_by_category(provider):
    monitors = provider.get_devices_by_category("Patient Monitor")
    assert len(monitors) == 1
    assert monitors[0].device_code == "DEV-003"


def test_get_devices_by_department(provider):
    icu_devices = provider.get_devices_by_department("ICU")
    codes = {d.device_code for d in icu_devices}
    assert codes == {"DEV-001", "DEV-003"}


def test_get_devices_by_location(provider):
    results = provider.get_devices_by_location("East Wing")
    codes = {d.device_code for d in results}
    assert codes == {"DEV-005", "DEV-006", "DEV-008"}


def test_device_hospital_and_department_names_are_resolved(provider):
    profile = provider.get_device("dev-001")
    assert profile.hospital_name == "Cairo Medical Center"
    assert profile.department_name == "ICU"


# ---------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------
def test_get_maintenance_history_sorted_newest_first(provider):
    history = provider.get_maintenance_history("dev-001")
    assert len(history) == 2
    assert history[0].performed_at > history[1].performed_at


def test_get_last_maintenance(provider):
    last = provider.get_last_maintenance("dev-001")
    assert last.record_id == "mr-002"
    assert last.parts_used == ["Pressure Sensor Tubing"]


def test_get_last_maintenance_no_history_returns_none(provider):
    assert provider.get_last_maintenance("dev-006") is None


def test_get_next_maintenance(provider):
    sched = provider.get_next_maintenance("dev-001")
    assert sched.frequency_days == 365


def test_get_corrective_maintenance_history_filters_type(provider):
    corrective = provider.get_corrective_maintenance_history("dev-001")
    assert len(corrective) == 1
    assert corrective[0].maintenance_type == "corrective"


def test_get_maintenance_history_date_filter(provider):
    history = provider.get_maintenance_history("dev-001", date_from=date(2026, 5, 1))
    assert len(history) == 1
    assert history[0].record_id == "mr-002"


def test_get_maintenance_statistics(provider):
    stats = provider.get_maintenance_statistics()
    assert stats["total"] == 6
    assert stats["preventive"] + stats["corrective"] == 6


# ---------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------
def test_get_ticket(provider):
    t = provider.get_ticket("tkt-001")
    assert t.status == "resolved"
    assert t.device_code == "DEV-001"


def test_get_device_tickets(provider):
    tickets = provider.get_device_tickets("dev-001")
    assert len(tickets) == 1


def test_get_open_tickets_excludes_resolved_and_cancelled(provider):
    open_tickets = provider.get_open_tickets()
    statuses = {t.status for t in open_tickets}
    assert "resolved" not in statuses
    assert "cancelled" not in statuses
    assert len(open_tickets) == 3  # tkt-002, tkt-003, tkt-004


def test_get_open_tickets_filtered_by_hospital(provider):
    open_h2 = provider.get_open_tickets(hospital_id="h2")
    assert open_h2 == []  # all open tickets in the dataset are on h1 devices


def test_get_resolved_tickets(provider):
    resolved = provider.get_resolved_tickets()
    assert len(resolved) == 1
    assert resolved[0].ticket_id == "tkt-001"


def test_get_ticket_statistics(provider):
    stats = provider.get_ticket_statistics()
    assert stats["total"] == 4
    assert stats["by_status"]["resolved"] == 1


# ---------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------
def test_get_device_risk_returns_the_most_recent_only(provider):
    risk = provider.get_device_risk("dev-001")
    assert risk.risk_level == "critical"
    assert risk.assessment_id == "ra-002"  # the later of the two dev-001 assessments


def test_get_risk_history_returns_everything_oldest_first(provider):
    history = provider.get_risk_history("dev-001")
    assert len(history) == 2
    assert history[0].assessment_id == "ra-001"
    assert history[1].assessment_id == "ra-002"


def test_get_high_risk_devices(provider):
    high = provider.get_high_risk_devices()
    codes = {d.device_code for d in high}
    assert codes == {"DEV-002", "DEV-004"}


def test_get_critical_risk_devices(provider):
    critical = provider.get_critical_risk_devices()
    codes = {d.device_code for d in critical}
    assert codes == {"DEV-001", "DEV-007"}


def test_get_risk_statistics(provider):
    stats = provider.get_risk_statistics()
    assert sum(stats.values()) == 8  # every device has at least one assessment


# ---------------------------------------------------------------------
# QA
# ---------------------------------------------------------------------
def test_get_device_qa_history(provider):
    history = provider.get_device_qa_history("dev-001")
    assert len(history) == 1
    assert history[0].status == "pass"


def test_get_failed_qa_records(provider):
    failed = provider.get_failed_qa_records()
    assert len(failed) == 1
    assert failed[0].device_id == "dev-004"


def test_get_upcoming_calibrations_within_window(provider):
    # NOW is 2026-10-04; dev-004's calibration is due 2026-10-15 (11 days away)
    upcoming = provider.get_upcoming_calibrations(within_days=30)
    device_ids = {q.device_id for q in upcoming}
    assert "dev-004" in device_ids


def test_get_qa_statistics(provider):
    stats = provider.get_qa_statistics()
    assert stats["total"] == 5
    assert stats["by_status"]["fail"] == 1


# ---------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------
def test_get_part_inventory_for_hospital(provider):
    inventory = provider.get_part_inventory("h1")
    assert len(inventory) == 3  # sensor, filter, battery are stocked at h1


def test_get_low_stock_parts(provider):
    low_stock = provider.get_low_stock_parts("h1")
    names = {p.part_name for p in low_stock}
    # HEPA Filter (3/5) and Battery Pack (2/4) are both below threshold
    assert names == {"HEPA Filter", "Battery Pack"}


def test_get_part_usage(provider):
    usage = provider.get_part_usage("part-sensor")
    assert len(usage) == 1
    assert usage[0].record_id == "mr-002"


def test_get_part_usage_unknown_part_returns_empty(provider):
    assert provider.get_part_usage("not-a-real-part") == []


def test_get_inventory_statistics(provider):
    stats = provider.get_inventory_statistics("h1")
    assert stats["total_parts_tracked"] == 3
    assert stats["low_stock_count"] == 2


# ---------------------------------------------------------------------
# Determinism: running everything twice gives identical results
# ---------------------------------------------------------------------
def test_results_are_deterministic_across_instances():
    p1, p2 = MockDataProvider(), MockDataProvider()
    assert p1.get_device("dev-001") == p2.get_device("dev-001")
    assert p1.get_maintenance_statistics() == p2.get_maintenance_statistics()
