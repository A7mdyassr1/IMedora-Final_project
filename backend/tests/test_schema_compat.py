"""
ORM models vs the LIVE database schema (B3.1 CP3, T7). PostgreSQL only: skipped unless
TEST_DATABASE_URL is set (the `real_db_url` fixture). Read-only: it reflects the schema and never
creates, alters or migrates anything (no create_all, no autogenerate).

The database layer (database/migrations) owns the schema; the ORM is a mirror. Only the tables the
backend actually maps are compared - the B4+ tables (tickets, maintenance, parts, ...) are listed
for information but not treated as implemented models. A mismatch FAILS with a description; it is
never "fixed" automatically.
"""
import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

from app.core.database import get_engine
from app.models import Base

MAPPED = sorted(Base.metadata.tables)
EXPECTED_MAPPED = sorted([
    "audit_logs", "departments", "device_categories", "device_models", "devices", "hospitals",
    "locations", "manufacturers", "organizations", "roles", "users",
])


@pytest.fixture
def insp(real_db_url):
    return inspect(get_engine())


def _norm_type(t) -> str:
    s = str(t.compile(dialect=postgresql.dialect())).upper()
    return s.replace("CHARACTER VARYING", "VARCHAR").replace("DATETIME", "TIMESTAMP")


def test_the_backend_maps_exactly_the_expected_tables(insp):
    assert MAPPED == EXPECTED_MAPPED
    live = set(insp.get_table_names())
    missing = sorted(set(MAPPED) - live)
    assert not missing, f"ORM tables missing from the database: {missing}"


@pytest.mark.parametrize("table", EXPECTED_MAPPED)
def test_columns_types_nullability_and_defaults_match(insp, table):
    t = Base.metadata.tables[table]
    live = {c["name"]: c for c in insp.get_columns(table)}
    problems = []
    if set(live) != set(t.columns.keys()):
        problems.append(f"columns differ: only in DB {sorted(set(live) - set(t.columns.keys()))}, "
                        f"only in ORM {sorted(set(t.columns.keys()) - set(live))}")
    for c in t.columns:
        d = live.get(c.name)
        if d is None:
            continue
        lt, ot = d["type"], c.type
        if getattr(lt, "enums", None):  # PostgreSQL enum: name and labels in order
            if (getattr(ot, "name", None), list(getattr(ot, "enums", []) or [])) != (lt.name, list(lt.enums)):
                problems.append(f"{c.name}: enum {getattr(ot, 'name', None)}{getattr(ot, 'enums', None)} vs DB {lt.name}{lt.enums}")
        elif "TIMESTAMP" in _norm_type(lt) and "TIMESTAMP" in _norm_type(ot):
            if bool(getattr(lt, "timezone", False)) != bool(getattr(ot, "timezone", False)):
                problems.append(f"{c.name}: timezone ORM={getattr(ot, 'timezone', False)} DB={lt.timezone}")
        elif _norm_type(lt) != _norm_type(ot):
            problems.append(f"{c.name}: type ORM={_norm_type(ot)} DB={_norm_type(lt)}")
        if not c.primary_key and d["nullable"] != c.nullable:
            problems.append(f"{c.name}: nullable ORM={c.nullable} DB={d['nullable']}")
        # a DB default the ORM does not know about would make the ORM send NULL / explicit values
        if d["default"] is not None and not c.primary_key and c.server_default is None and c.default is None:
            problems.append(f"{c.name}: DB default {d['default']!r} not declared in the ORM")
    assert not problems, f"{table}: " + "; ".join(problems)


@pytest.mark.parametrize("table", EXPECTED_MAPPED)
def test_primary_and_foreign_keys_match_including_ondelete(insp, table):
    t = Base.metadata.tables[table]
    assert set(insp.get_pk_constraint(table)["constrained_columns"]) == {c.name for c in t.primary_key}, table
    live = {(tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]),
             (f["options"].get("ondelete") or "NO ACTION").upper()) for f in insp.get_foreign_keys(table)}
    orm = {(tuple(c.name for c in fk.columns), fk.referred_table.name, tuple(e.column.name for e in fk.elements),
            (fk.ondelete or "NO ACTION").upper()) for fk in t.foreign_key_constraints}
    assert live == orm, f"{table}: only in DB {sorted(live - orm)}, only in ORM {sorted(orm - live)}"


def test_enum_labels_match_the_backend_enums(insp):
    from app.core.enums import AuditAction, Criticality, DeviceStatus, RiskLevel
    live = {e["name"]: e["labels"] for e in insp.get_enums()}
    for name, enum in (("device_status", DeviceStatus), ("device_criticality", Criticality),
                       ("risk_level", RiskLevel), ("audit_action", AuditAction)):
        assert live.get(name) == [m.value for m in enum], name


def test_role_names_the_backend_relies_on_are_valid_enum_free_text(insp):
    """roles.name is plain text in the DB; the backend's Role values must fit its length."""
    from app.core.roles import Role
    col = {c["name"]: c for c in insp.get_columns("roles")}["name"]
    length = getattr(col["type"], "length", None)
    assert length is None or all(len(r.value) <= length for r in Role)
