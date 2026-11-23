"""
ORM models vs the LIVE database schema (B3.1 CP3, T7). PostgreSQL only: skipped unless
TEST_DATABASE_URL is set (the `real_db_url` fixture). Read-only: it reflects the schema and never
creates, alters or migrates anything (no create_all, no autogenerate).

The database layer (database/migrations) owns the schema; the ORM is a mirror. Only the tables the
backend actually maps are compared; tables of later phases (parts, risk, QA, attachments,
notifications) are not treated as implemented models until they are mapped. B4 CP1 added the
five ticket / maintenance tables, with a stricter check (constraint and index names) for them. A mismatch FAILS with a description; it is
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
    # B4 CP1
    "maintenance_records", "maintenance_schedules", "maintenance_tickets", "maintenance_types", "ticket_assignments",
    # B5
    "maintenance_parts", "part_inventory", "parts",
])
B4_TABLES = ["maintenance_records", "maintenance_schedules", "maintenance_tickets", "maintenance_types", "ticket_assignments",
             # B5: the same exact-name checks for the new mirrors
             "maintenance_parts", "part_inventory", "parts"]


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
    from app.core.enums import AuditAction, Criticality, DeviceStatus, RiskLevel, TicketPriority, TicketStatus
    live = {e["name"]: e["labels"] for e in insp.get_enums()}
    for name, enum in (("device_status", DeviceStatus), ("device_criticality", Criticality),
                       ("risk_level", RiskLevel), ("audit_action", AuditAction),
                       ("ticket_status", TicketStatus), ("ticket_priority", TicketPriority)):
        assert live.get(name) == [m.value for m in enum], name


def test_role_names_the_backend_relies_on_are_valid_enum_free_text(insp):
    """roles.name is plain text in the DB; the backend's Role values must fit its length."""
    from app.core.roles import Role
    col = {c["name"]: c for c in insp.get_columns("roles")}["name"]
    length = getattr(col["type"], "length", None)
    assert length is None or all(len(r.value) <= length for r in Role)


@pytest.mark.parametrize("table", B4_TABLES)
def test_b4_unique_constraints_indexes_and_checks_match(insp, table):
    """B4 mirrors also declare every unique constraint, index (incl. the partial unique
    uq_active_assignment) and CHECK constraint of their table, by name: the services rely on
    these names to turn database errors into clear API errors."""
    t = Base.metadata.tables[table]
    live_uq = {(u["name"], tuple(u["column_names"])) for u in insp.get_unique_constraints(table)}
    orm_uq = {(u.name or f"{table}_{'_'.join(c.name for c in u.columns)}_key", tuple(c.name for c in u.columns))
              for u in t.constraints if u.__class__.__name__ == "UniqueConstraint"}
    orm_uq |= {(f"{table}_{c.name}_key", (c.name,)) for c in t.columns if c.unique}
    assert live_uq == orm_uq, f"{table} unique: only in DB {sorted(live_uq - orm_uq)}, only in ORM {sorted(orm_uq - live_uq)}"

    live_ix = {(i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in insp.get_indexes(table)
               if not i.get("duplicates_constraint")}
    orm_ix = {(i.name, tuple(c.name for c in i.columns), bool(i.unique)) for i in t.indexes}
    assert live_ix == orm_ix, f"{table} indexes: only in DB {sorted(live_ix - orm_ix)}, only in ORM {sorted(orm_ix - live_ix)}"

    live_ck = {c["name"] for c in insp.get_check_constraints(table)}
    orm_ck = {c.name for c in t.constraints if c.__class__.__name__ == "CheckConstraint"}
    assert live_ck == orm_ck, f"{table} checks: only in DB {sorted(live_ck - orm_ck)}, only in ORM {sorted(orm_ck - live_ck)}"


def test_active_assignment_index_is_partial_on_unassigned_rows(insp):
    live = {i["name"]: i for i in insp.get_indexes("ticket_assignments")}["uq_active_assignment"]
    where = (live.get("dialect_options") or {}).get("postgresql_where")
    assert live["unique"] and where is not None and "unassigned_at IS NULL" in str(where)
    orm = {i.name: i for i in Base.metadata.tables["ticket_assignments"].indexes}["uq_active_assignment"]
    assert "unassigned_at IS NULL" in str(orm.dialect_options["postgresql"]["where"])
