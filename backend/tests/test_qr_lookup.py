"""QR lookup query shape - checked WITHOUT a database.

Review finding 1: the old lookup fell back to `upper(qr_identifier) = ...`. No index
exists on upper(qr_identifier), so PostgreSQL could not use the unique index for it and
had to scan the organization's devices, for every unknown or lower-case scan. The lookup
must only ever compare the column itself, which keeps the unique index usable. (Whether
the planner then picks it is a cost decision; these tests check the query shape only.)
"""
import uuid

from sqlalchemy.dialects import postgresql

from app.repositories.device_repository import DeviceRepository


def _sql(qr: str) -> str:
    stmt = DeviceRepository.qr_lookup_statement(uuid.uuid4(), DeviceRepository.qr_candidates(qr))
    return str(stmt.compile(dialect=postgresql.dialect())).lower()


def test_candidates_are_exact_then_upper_then_lower():
    assert DeviceRepository.qr_candidates("  Qr-Cmc-Dev-001 ") == ["Qr-Cmc-Dev-001", "QR-CMC-DEV-001", "qr-cmc-dev-001"]


def test_candidates_have_no_duplicates_for_already_normalised_codes():
    assert DeviceRepository.qr_candidates("QR-CMC-DEV-001") == ["QR-CMC-DEV-001", "qr-cmc-dev-001"]
    assert DeviceRepository.qr_candidates("12345") == ["12345"]


def test_blank_input_gives_no_candidates():
    assert DeviceRepository.qr_candidates("   ") == []


def test_query_compares_the_indexed_column_directly():
    sql = _sql("qr-cmc-dev-001")
    assert "devices.qr_identifier in" in sql
    assert "upper(" not in sql and "lower(" not in sql


def test_query_is_always_organization_scoped():
    assert "devices.organization_id =" in _sql("QR-1")
