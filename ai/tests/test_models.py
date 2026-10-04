"""
Phase AI-1 tests: core models + interfaces.

Run with (from the ai/ parent directory, so `ai` is importable):
    python -m pytest ai/tests/test_models.py -v
"""
import pytest
from pydantic import ValidationError

from ai.config import AISettings, get_settings
from ai.models import (
    AgentResult,
    AnalyticsResult,
    ChatMessage,
    ChatResponse,
    ChatRole,
    DeviceContext,
    DeviceProfile,
    InventoryContext,
    Intent,
    MaintenanceEvent,
    QAContext,
    RAGChunk,
    RAGDocument,
    ReportRequest,
    ReportResult,
    RiskContext,
    SearchResult,
    SourceType,
    TicketContext,
    ToolResult,
)
from ai.services.data.base import DataProvider
from ai.services.llm.base import LLMService
from ai.services.rag.base import EmbeddingService, VectorStore


# ---------------------------------------------------------------------
# Models: valid data constructs cleanly
# ---------------------------------------------------------------------
def test_device_profile_valid():
    profile = DeviceProfile(
        device_id="d1", device_code="DEV-001", name="Ventilator", qr_identifier="QR-1",
        status="active", criticality="critical", current_risk_level="high",
    )
    assert profile.status == "active"
    assert profile.current_risk_level == "high"


def test_device_context_valid():
    ctx = DeviceContext(device_id="d1", device_code="DEV-001", name="Ventilator", hospital_id="h1", status="active")
    assert ctx.device_code == "DEV-001"


def test_maintenance_event_valid():
    event = MaintenanceEvent(
        record_id="r1", device_id="d1", maintenance_type="corrective",
        description="Replaced sensor", performed_at="2026-01-01T10:00:00Z", parts_used=["Pressure Sensor"],
    )
    assert event.maintenance_type == "corrective"
    assert event.parts_used == ["Pressure Sensor"]


def test_ticket_context_valid():
    t = TicketContext(
        ticket_id="t1", device_id="d1", problem_description="Not powering on",
        priority="high", status="open", created_at="2026-01-01T10:00:00Z",
    )
    assert t.status == "open"


def test_risk_context_valid():
    r = RiskContext(assessment_id="ra1", device_id="d1", risk_level="critical", assessed_at="2026-01-01T10:00:00Z")
    assert r.risk_level == "critical"


def test_qa_context_valid():
    qa = QAContext(
        qa_id="qa1", device_id="d1", record_type="calibration", status="pass",
        performed_at="2026-01-01T10:00:00Z",
    )
    assert qa.record_type == "calibration"


def test_inventory_context_reorder_flag():
    inv = InventoryContext(part_id="p1", part_name="HEPA Filter", part_number="PN-1", hospital_id="h1",
                            quantity_on_hand=2, reorder_threshold=5)
    assert inv.below_reorder_threshold is True
    inv2 = InventoryContext(part_id="p1", part_name="HEPA Filter", part_number="PN-1", hospital_id="h1",
                             quantity_on_hand=10, reorder_threshold=5)
    assert inv2.below_reorder_threshold is False


def test_search_result_valid():
    sr = SearchResult(result_type="device", id="d1", title="DEV-001 Ventilator")
    assert sr.result_type == "device"


def test_rag_document_and_chunk():
    doc = RAGDocument(document_id="doc1", document_name="Ventilator Manual", document_type="pdf")
    chunk = RAGChunk(chunk_id="c1", document_id="doc1", text="Section 3: maintenance...")
    assert chunk.document_id == doc.document_id


def test_chat_response_requires_source_type():
    resp = ChatResponse(message="DEV-001 is active.", source_type=SourceType.structured_data, sources=["get_device"])
    assert resp.data_available is True
    msg = ChatMessage(role=ChatRole.user, content="What's the status of DEV-001?")
    assert msg.role == ChatRole.user


def test_chat_response_unavailable_source_type():
    resp = ChatResponse(
        message="I don't have maintenance history for that device.",
        source_type=SourceType.unavailable,
        data_available=False,
    )
    assert resp.data_available is False


def test_analytics_result_accepts_dict_value():
    result = AnalyticsResult(metric_name="risk_distribution", value={"low": 10, "high": 3})
    assert result.value["low"] == 10


def test_report_request_defaults_and_result():
    req = ReportRequest(device_id="d1")
    assert "device_profile" in req.include_sections
    res = ReportResult(device_id="d1", sections={"device_profile": "..."}, missing_data=["risk_assessment"])
    assert res.missing_data == ["risk_assessment"]


def test_tool_result_and_agent_result():
    tr = ToolResult(tool_name="get_device", success=True, data={"device_id": "d1"})
    ar = AgentResult(agent_name="chatbot", success=True, output="DEV-001 is active.", tool_results=[tr])
    assert ar.tool_results[0].tool_name == "get_device"


def test_intent_enum_values():
    assert Intent.DEVICE_QUERY == "DEVICE_QUERY"
    assert Intent.REPORT_QUERY == "REPORT_QUERY"


# ---------------------------------------------------------------------
# Models: invalid data is REJECTED (these fields mirror real Postgres
# enums - a value the DB could never produce must fail here too)
# ---------------------------------------------------------------------
def test_device_status_rejects_invalid_value():
    with pytest.raises(ValidationError):
        DeviceProfile(
            device_id="d1", device_code="DEV-001", name="X", qr_identifier="QR-1",
            status="deleted_forever",  # not a real status
            criticality="critical",
        )


def test_ticket_priority_rejects_invalid_value():
    with pytest.raises(ValidationError):
        TicketContext(
            ticket_id="t1", device_id="d1", problem_description="x",
            priority="urgent",  # not a real priority value
            status="open", created_at="2026-01-01T10:00:00Z",
        )


def test_qa_status_rejects_invalid_value():
    with pytest.raises(ValidationError):
        QAContext(qa_id="qa1", device_id="d1", record_type="calibration", status="ok",  # not a real status
                   performed_at="2026-01-01T10:00:00Z")


# ---------------------------------------------------------------------
# Interfaces: genuinely abstract - cannot be instantiated directly
# ---------------------------------------------------------------------
def test_data_provider_is_abstract():
    with pytest.raises(TypeError):
        DataProvider()  # type: ignore[abstract]


def test_llm_service_is_abstract():
    with pytest.raises(TypeError):
        LLMService()  # type: ignore[abstract]


def test_embedding_service_and_vector_store_are_abstract():
    with pytest.raises(TypeError):
        EmbeddingService()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        VectorStore()  # type: ignore[abstract]


def test_data_provider_can_be_subclassed_once_fully_implemented():
    """A minimal concrete subclass implementing every abstract method
    must be instantiable - proves the interface isn't accidentally
    over-constrained for Phase AI-2's MockDataProvider."""

    class TinyProvider(DataProvider):
        def search_devices(self, query, limit=20):
            return []

        def get_device(self, device_id):
            return None

        def get_device_profile(self, device_id):
            return None

        def get_devices_by_status(self, status):
            return []

        def get_devices_by_risk(self, risk_level):
            return []

        def get_devices_by_category(self, category):
            return []

        def get_devices_by_department(self, department):
            return []

        def get_devices_by_location(self, location):
            return []

        def get_maintenance_history(self, device_id, date_from=None, date_to=None, maintenance_type=None, technician=None):
            return []

        def get_last_maintenance(self, device_id):
            return None

        def get_next_maintenance(self, device_id):
            return None

        def get_preventive_maintenance_status(self, device_id):
            return None

        def get_corrective_maintenance_history(self, device_id):
            return []

        def get_maintenance_statistics(self, hospital_id=None, department=None, date_from=None, date_to=None):
            return {}

        def search_tickets(self, query, limit=20):
            return []

        def get_ticket(self, ticket_id):
            return None

        def get_device_tickets(self, device_id):
            return []

        def get_open_tickets(self, hospital_id=None, department=None):
            return []

        def get_resolved_tickets(self, hospital_id=None, date_from=None):
            return []

        def get_ticket_statistics(self, priority=None, status=None, department=None, date_from=None, date_to=None):
            return {}

        def get_device_risk(self, device_id):
            return None

        def get_risk_history(self, device_id):
            return []

        def get_high_risk_devices(self):
            return []

        def get_critical_risk_devices(self):
            return []

        def get_risk_statistics(self, hospital_id=None):
            return {}

        def get_device_qa_history(self, device_id):
            return []

        def get_calibration_history(self, device_id):
            return []

        def get_failed_qa_records(self, hospital_id=None):
            return []

        def get_upcoming_calibrations(self, within_days=30):
            return []

        def get_qa_statistics(self, hospital_id=None):
            return {}

        def get_part_inventory(self, hospital_id, part_name=None):
            return []

        def get_low_stock_parts(self, hospital_id):
            return []

        def get_part_usage(self, part_id, date_from=None):
            return []

        def get_inventory_statistics(self, hospital_id):
            return {}

    provider = TinyProvider()
    assert provider.get_device("anything") is None


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
def test_settings_default_to_mock_everything():
    settings = AISettings(_env_file=None)
    assert settings.data_provider == "mock"
    assert settings.llm_provider == "mock"
    assert settings.embedding_provider == "mock"
    assert settings.vector_store_type == "local"


def test_get_settings_is_cached_singleton():
    assert get_settings() is get_settings()
