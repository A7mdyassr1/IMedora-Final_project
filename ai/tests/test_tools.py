"""
Phase AI-3 tests: tools + registry.

Run with:
    python -m pytest ai/tests/test_tools.py -v
"""
import pytest

from ai.models.agent import ToolResult
from ai.services.data.mock_provider import MockDataProvider
from ai.tools.registry import ALL_TOOLS, build_registry


@pytest.fixture
def registry():
    return build_registry(MockDataProvider())


# ---------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------
def _provider_tool_names(registry):
    return {n for n in registry.names() if registry.get(n).category != "analytics"}


def test_registry_exposes_one_tool_per_provider_method(registry):
    assert len(_provider_tool_names(registry)) == 34
    assert len(registry.by_category("analytics")) == 8  # Phase AI-4
    assert len(ALL_TOOLS) == 34 + 8


def test_every_tool_has_a_description_and_category(registry):
    for spec in registry.describe():
        assert spec["description"], f"{spec['name']} has no description"
        assert spec["category"] in {"device", "maintenance", "ticket", "risk", "qa", "inventory", "analytics"}


def test_expected_tool_names_from_the_project_brief_all_exist(registry):
    required = [
        "search_devices", "get_device", "get_device_profile", "get_devices_by_status", "get_devices_by_risk",
        "get_devices_by_category", "get_devices_by_department", "get_devices_by_location",
        "get_maintenance_history", "get_last_maintenance", "get_next_maintenance",
        "get_preventive_maintenance_status", "get_corrective_maintenance_history", "get_maintenance_statistics",
        "search_tickets", "get_ticket", "get_device_tickets", "get_open_tickets", "get_resolved_tickets",
        "get_ticket_statistics",
        "get_device_risk", "get_risk_history", "get_high_risk_devices", "get_critical_risk_devices",
        "get_risk_statistics",
        "get_device_qa_history", "get_calibration_history", "get_failed_qa_records", "get_upcoming_calibrations",
        "get_qa_statistics",
        "get_part_inventory", "get_low_stock_parts", "get_part_usage", "get_inventory_statistics",
    ]
    for name in required:
        assert registry.has(name), f"missing tool: {name}"


def test_unknown_tool_is_a_failed_result_not_an_exception(registry):
    result = registry.call("make_up_data")
    assert result.success is False
    assert "Unknown tool" in result.error


# ---------------------------------------------------------------------
# Every tool runs and returns a ToolResult
# ---------------------------------------------------------------------
SAMPLE_CALLS = [
    ("search_devices", {"query": "vent"}), ("get_device", {"device_id": "dev-001"}),
    ("get_device_profile", {"device_id": "dev-001"}), ("get_devices_by_status", {"status": "active"}),
    ("get_devices_by_risk", {"risk_level": "critical"}), ("get_devices_by_category", {"category": "Ventilator"}),
    ("get_devices_by_department", {"department": "ICU"}), ("get_devices_by_location", {"location": "Floor 2"}),
    ("get_maintenance_history", {"device_id": "dev-001"}), ("get_last_maintenance", {"device_id": "dev-001"}),
    ("get_next_maintenance", {"device_id": "dev-001"}), ("get_preventive_maintenance_status", {"device_id": "dev-001"}),
    ("get_corrective_maintenance_history", {"device_id": "dev-001"}), ("get_maintenance_statistics", {}),
    ("search_tickets", {"query": "battery"}), ("get_ticket", {"ticket_id": "tkt-001"}),
    ("get_device_tickets", {"device_id": "dev-001"}), ("get_open_tickets", {}), ("get_resolved_tickets", {}),
    ("get_ticket_statistics", {}), ("get_device_risk", {"device_id": "dev-001"}),
    ("get_risk_history", {"device_id": "dev-001"}), ("get_high_risk_devices", {}),
    ("get_critical_risk_devices", {}), ("get_risk_statistics", {}), ("get_device_qa_history", {"device_id": "dev-001"}),
    ("get_calibration_history", {"device_id": "dev-001"}), ("get_failed_qa_records", {}),
    ("get_upcoming_calibrations", {}), ("get_qa_statistics", {}), ("get_part_inventory", {"hospital_id": "h1"}),
    ("get_low_stock_parts", {"hospital_id": "h1"}), ("get_part_usage", {"part_id": "part-sensor"}),
    ("get_inventory_statistics", {"hospital_id": "h1"}),
]


def test_sample_calls_cover_every_tool(registry):
    assert {name for name, _ in SAMPLE_CALLS} == _provider_tool_names(registry)


@pytest.mark.parametrize("name,kwargs", SAMPLE_CALLS)
def test_every_tool_succeeds_and_returns_structured_data(registry, name, kwargs):
    result = registry.call(name, **kwargs)
    assert isinstance(result, ToolResult)
    assert result.tool_name == name
    assert result.success is True, result.error
    assert isinstance(result.data, dict)


# ---------------------------------------------------------------------
# Anti-fabrication semantics
# ---------------------------------------------------------------------
def test_missing_device_is_found_false_not_a_failure(registry):
    result = registry.call("get_device", device_id="no-such-device")
    assert result.success is True
    assert result.data["found"] is False
    assert result.data["item"] is None


def test_empty_list_says_so_explicitly(registry):
    result = registry.call("get_maintenance_history", device_id="dev-006")  # no history in the dataset
    assert result.success is True
    assert result.data["count"] == 0
    assert "No maintenance records found" in result.data["message"]


def test_known_device_data_comes_straight_from_the_provider(registry):
    item = registry.call("get_device", device_id="dev-001").data["item"]
    assert item["device_code"] == "DEV-001"
    assert item["status"] == "active"
    assert item["current_risk_level"] == "critical"


def test_current_risk_and_risk_history_are_distinct(registry):
    current = registry.call("get_device_risk", device_id="dev-001").data
    history = registry.call("get_risk_history", device_id="dev-001").data
    assert current["scope"] == "current"
    assert history["scope"] == "history"
    assert current["item"]["risk_level"] == "critical"
    assert [a["risk_level"] for a in history["items"]] == ["high", "critical"]


def test_unassessed_device_risk_is_not_inferred(registry):
    result = registry.call("get_device_risk", device_id="no-such-device")
    assert result.data["found"] is False


def test_inventory_in_stock_flag_reflects_real_quantities(registry):
    assert registry.call("get_part_inventory", hospital_id="h1").data["in_stock"] is True
    # hospital with no inventory rows at all -> not "in stock", and says so
    nothing = registry.call("get_part_inventory", hospital_id="h-unknown").data
    assert nothing["in_stock"] is False
    assert nothing["count"] == 0


# ---------------------------------------------------------------------
# Filters: strings from an LLM work, and applied filters are echoed back
# ---------------------------------------------------------------------
def test_date_filters_accept_iso_strings(registry):
    result = registry.call("get_maintenance_history", device_id="dev-001", date_from="2026-05-01")
    assert result.data["count"] == 1


def test_statistics_echo_the_filters_that_were_applied(registry):
    result = registry.call("get_maintenance_statistics", department="ICU")
    assert result.data["filters_applied"] == {"department": "ICU"}
    assert result.data["statistics"]["total"] == 3


def test_ticket_statistics_filtering_by_priority(registry):
    result = registry.call("get_ticket_statistics", priority="critical")
    assert result.data["statistics"]["total"] == 2


def test_maintenance_history_filter_by_technician(registry):
    result = registry.call("get_maintenance_history", device_id="dev-001", technician="Mostafa Hassan")
    assert result.data["count"] == 2


# ---------------------------------------------------------------------
# A real fault becomes a failed ToolResult - never an exception
# ---------------------------------------------------------------------
class ExplodingProvider(MockDataProvider):
    def get_device(self, device_id):
        raise ConnectionError("backend unreachable")


def test_provider_exception_becomes_failed_toolresult():
    registry = build_registry(ExplodingProvider())
    result = registry.call("get_device", device_id="dev-001")
    assert result.success is False
    assert "ConnectionError" in result.error
    assert "backend unreachable" in result.error


def test_bad_date_string_becomes_failed_toolresult(registry):
    result = registry.call("get_maintenance_history", device_id="dev-001", date_from="not-a-date")
    assert result.success is False
    assert result.error
