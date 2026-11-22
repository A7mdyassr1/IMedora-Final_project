"""
Audit logging against REAL PostgreSQL (B3.1 CP2). Skipped unless TEST_DATABASE_URL is set.

Covers: the ORM mirror matches the live audit_logs table; one correct row per supported change;
the audit row is written in the SAME transaction as the change (same PostgreSQL xmin); failed
changes leave no audit row; no password, hash or token ever reaches audit_logs.
"""
import uuid

import pytest
from sqlalchemy import inspect as sa_inspect, select, text

from app.core.database import get_engine, get_session_factory
from app.core.enums import AuditAction
from app.models import AuditLog, Hospital
from app.services.audit_service import AuditService
from tests.test_devices_flow import cat, eng, make_device  # noqa: F401  (pytest fixtures)
from tests.world import API, PW, auth


def rows(table: str, record_id) -> list:
    with get_session_factory()() as db:
        stmt = (select(AuditLog).where(AuditLog.table_name == table, AuditLog.record_id == uuid.UUID(str(record_id)))
                .order_by(AuditLog.created_at, AuditLog.id))
        return list(db.scalars(stmt))


def one(table: str, record_id, action: AuditAction) -> AuditLog:
    found = [r for r in rows(table, record_id) if r.action == action]
    assert len(found) == 1, f"expected one {action} row for {table}/{record_id}, got {len(found)}"
    return found[0]


def admin_id(client, headers) -> uuid.UUID:
    return uuid.UUID(client.get(f"{API}/auth/me", headers=headers).json()["id"])


# ---- schema compatibility ------------------------------------------------------------------
def test_audit_log_model_matches_the_live_table(real_db_url):
    insp = sa_inspect(get_engine())
    live = {c["name"]: c for c in insp.get_columns("audit_logs")}
    model = AuditLog.__table__
    assert set(live) == set(model.columns.keys())
    expected = {  # column: (type as PostgreSQL reports it, nullable, has server default)
        "id": ("UUID", False, True), "organization_id": ("UUID", False, False), "user_id": ("UUID", True, False),
        "table_name": ("VARCHAR(100)", False, False), "record_id": ("UUID", False, False),
        "action": ("AUDIT_ACTION", False, False), "old_values": ("JSONB", True, False),
        "new_values": ("JSONB", True, False), "created_at": ("TIMESTAMP", False, True),
    }
    for name, (typ, nullable, has_default) in expected.items():
        col = live[name]
        reported = getattr(col["type"], "name", None) if name == "action" else str(col["type"])
        assert str(reported).upper().startswith(typ), (name, col["type"])
        assert col["nullable"] is nullable, name
        assert (col["default"] is not None) is has_default, name
        assert model.c[name].nullable is nullable, f"ORM nullability differs for {name}"
    assert live["created_at"]["type"].timezone is True
    with get_session_factory()() as db:
        labels = db.execute(text("SELECT enum_range(NULL::audit_action)::text")).scalar()
    assert labels == "{insert,update,delete}"
    fks = {fk["constrained_columns"][0]: (fk["referred_table"], fk["options"].get("ondelete")) for fk in insp.get_foreign_keys("audit_logs")}
    assert fks == {"organization_id": ("organizations", "RESTRICT"), "user_id": ("users", "RESTRICT")}
    model_fks = {fk.parent.name: (fk.column.table.name, fk.ondelete) for fk in model.foreign_keys}
    assert model_fks == fks


# ---- one row per supported change ----------------------------------------------------------
def test_user_changes_are_audited(client, world):
    admin = auth(client, world["admin"])
    me = admin_id(client, admin)
    email = f"audited-{world['sfx']}@b2.test"
    r = client.post(f"{API}/users", headers=admin, json=dict(
        email=email, full_name="Audited", password=PW, role="technician", hospital_id=world["h1"]))
    uid = r.json()["id"]
    ins = one("users", uid, AuditAction.INSERT)
    assert ins.user_id == me and str(ins.organization_id) == world["org"]
    assert ins.new_values["email"] == email and "password_hash" not in ins.new_values

    client.patch(f"{API}/users/{uid}", headers=admin, json={"full_name": "Renamed", "is_active": False})
    upd = [r for r in rows("users", uid) if r.action == AuditAction.UPDATE][-1]
    assert upd.old_values == {"full_name": "Audited", "is_active": True}
    assert upd.new_values == {"full_name": "Renamed", "is_active": False}

    client.post(f"{API}/users/{uid}/reset-password", headers=admin, json={"new_password": "Reset-Pass-123"})
    reset = [r for r in rows("users", uid) if r.action == AuditAction.UPDATE][-1]
    assert reset.old_values is None and reset.new_values == {"password_changed": True} and reset.user_id == me


def test_own_password_change_is_audited_as_a_marker(client, world):
    h = auth(client, world["staff"])
    me = admin_id(client, h)
    assert client.post(f"{API}/auth/change-password", headers=h,
                       json={"current_password": PW, "new_password": "Brand-New-Pass-1"}).status_code == 204
    row = [r for r in rows("users", me) if r.action == AuditAction.UPDATE][-1]
    assert row.user_id == me and row.new_values == {"password_changed": True}


def test_structure_changes_are_audited(client, world):
    admin = auth(client, world["admin"])
    me = admin_id(client, admin)

    client.patch(f"{API}/organizations/current", headers=admin, json={"name": f"Renamed Org {world['sfx']}"})
    org_upd = [r for r in rows("organizations", world["org"]) if r.action == AuditAction.UPDATE][-1]
    assert org_upd.new_values == {"name": f"Renamed Org {world['sfx']}"} and org_upd.user_id == me

    h = client.post(f"{API}/hospitals", headers=admin, json={"name": "Audit Hospital", "code": f"AH-{world['sfx']}"}).json()
    assert one("hospitals", h["id"], AuditAction.INSERT).new_values["code"] == f"AH-{world['sfx']}"
    client.patch(f"{API}/hospitals/{h['id']}", headers=admin, json={"is_active": False})
    assert one("hospitals", h["id"], AuditAction.UPDATE).new_values == {"is_active": False}

    d = client.post(f"{API}/departments", headers=admin, json={"hospital_id": world["h1"], "name": "Audit Dept"}).json()
    ins = one("departments", d["id"], AuditAction.INSERT)
    assert str(ins.organization_id) == world["org"] and ins.new_values["name"] == "Audit Dept"
    client.patch(f"{API}/departments/{d['id']}", headers=admin, json={"name": "Audit Dept 2"})
    assert one("departments", d["id"], AuditAction.UPDATE).old_values == {"name": "Audit Dept"}
    assert client.delete(f"{API}/departments/{d['id']}", headers=admin).status_code == 204
    assert one("departments", d["id"], AuditAction.DELETE).old_values["name"] == "Audit Dept 2"

    loc = client.post(f"{API}/locations", headers=admin, json={"hospital_id": world["h1"], "building": "B", "room": "1"}).json()
    assert one("locations", loc["id"], AuditAction.INSERT).new_values["room"] == "1"
    client.patch(f"{API}/locations/{loc['id']}", headers=admin, json={"room": "2"})
    assert one("locations", loc["id"], AuditAction.UPDATE).new_values == {"room": "2"}
    assert client.delete(f"{API}/locations/{loc['id']}", headers=admin).status_code == 204
    assert one("locations", loc["id"], AuditAction.DELETE).old_values["room"] == "2"


def test_catalog_changes_are_audited_under_the_actors_organization(client, world, cat, eng):
    me = admin_id(client, eng)
    sfx = world["sfx"]
    c = client.post(f"{API}/device-categories", headers=eng, json={"name": f"AuditCat-{sfx}"}).json()
    m = client.post(f"{API}/manufacturers", headers=eng, json={"name": f"AuditMfr-{sfx}"}).json()
    for table, obj in (("device_categories", c), ("manufacturers", m)):
        ins = one(table, obj["id"], AuditAction.INSERT)
        assert ins.user_id == me and str(ins.organization_id) == world["org"]
    client.patch(f"{API}/device-categories/{c['id']}", headers=eng, json={"name": f"AuditCat2-{sfx}"})
    assert one("device_categories", c["id"], AuditAction.UPDATE).new_values == {"name": f"AuditCat2-{sfx}"}
    client.patch(f"{API}/manufacturers/{m['id']}", headers=eng, json={"name": f"AuditMfr2-{sfx}"})
    assert one("manufacturers", m["id"], AuditAction.UPDATE).old_values == {"name": f"AuditMfr-{sfx}"}

    mdl = client.post(f"{API}/device-models", headers=eng, json={
        "manufacturer_id": m["id"], "device_category_id": c["id"], "name": "AuditModel"}).json()
    assert one("device_models", mdl["id"], AuditAction.INSERT).new_values["name"] == "AuditModel"
    client.patch(f"{API}/device-models/{mdl['id']}", headers=eng, json={"name": "AuditModel2"})
    assert one("device_models", mdl["id"], AuditAction.UPDATE).new_values == {"name": "AuditModel2"}
    for url, table, oid in ((f"device-models/{mdl['id']}", "device_models", mdl["id"]),
                            (f"device-categories/{c['id']}", "device_categories", c["id"]),
                            (f"manufacturers/{m['id']}", "manufacturers", m["id"])):
        assert client.delete(f"{API}/{url}", headers=eng).status_code == 204
        assert one(table, oid, AuditAction.DELETE).user_id == me


def test_device_changes_are_audited(client, world, cat, eng):
    me = admin_id(client, eng)
    d = make_device(client, eng, world, cat)
    ins = one("devices", d["id"], AuditAction.INSERT)
    assert ins.user_id == me and ins.new_values["device_code"] == d["device_code"]
    client.patch(f"{API}/devices/{d['id']}", headers=eng, json={"name": "Renamed device"})
    upd = one("devices", d["id"], AuditAction.UPDATE)
    assert upd.old_values == {"name": "Ventilator 1"} and upd.new_values == {"name": "Renamed device"}
    client.delete(f"{API}/devices/{d['id']}", headers=eng)  # archive = soft delete = UPDATE
    archive = [r for r in rows("devices", d["id"]) if r.action == AuditAction.UPDATE][-1]
    assert archive.new_values["status"] == "decommissioned" and archive.new_values["deleted_at"]
    assert archive.old_values == {"status": "active", "deleted_at": None}
    client.delete(f"{API}/devices/{d['id']}", headers=eng)  # idempotent repeat changes nothing...
    assert len([r for r in rows("devices", d["id"]) if r.action == AuditAction.UPDATE]) == 2  # ...so no new row


# ---- transactions --------------------------------------------------------------------------
def test_audit_row_is_written_in_the_same_transaction_as_the_change(client, world):
    admin = auth(client, world["admin"])
    h = client.post(f"{API}/hospitals", headers=admin, json={"name": "Tx Hospital", "code": f"TX-{world['sfx']}"}).json()
    with get_session_factory()() as db:  # xmin = id of the transaction that wrote the row
        business = db.execute(text("SELECT xmin::text FROM hospitals WHERE id = :i"), {"i": h["id"]}).scalar()
        audit = db.execute(text("SELECT xmin::text FROM audit_logs WHERE table_name = 'hospitals' AND record_id = :i"),
                           {"i": h["id"]}).scalar()
    assert business == audit


def test_a_failed_change_leaves_no_audit_row(client, world, cat, eng):
    d = make_device(client, eng, world, cat)
    before = len(rows("devices", d["id"]))
    with get_session_factory()() as db:
        count = lambda: db.execute(text("SELECT count(*) FROM audit_logs WHERE organization_id = :o"), {"o": world["org"]}).scalar()  # noqa: E731
        n0 = count()
        # Duplicate device code: rejected by PostgreSQL at commit -> 409, and the staged audit row rolls back.
        dup = client.post(f"{API}/devices", headers=eng, json=dict(
            hospital_id=world["h1"], department_id=world["icu"], device_model_id=cat["model_a"],
            device_code=d["device_code"], name="Dup"))
        assert dup.status_code == 409
        # Deleting a department that devices still use: blocked by RESTRICT -> 409, no DELETE row kept.
        admin = auth(client, world["admin"])
        assert client.delete(f"{API}/departments/{world['icu']}", headers=admin).status_code == 409
        db.rollback()  # fresh snapshot
        assert count() == n0
    assert len(rows("devices", d["id"])) == before
    assert [r for r in rows("departments", world["icu"]) if r.action == AuditAction.DELETE] == []


def test_rolled_back_session_discards_both_rows(world):
    """AuditService never commits: if the caller rolls back, neither row survives."""
    with get_session_factory()() as db:
        h = Hospital(organization_id=uuid.UUID(world["org"]), name="Ghost", code=f"GH-{world['sfx']}", is_active=True)
        db.add(h)
        db.flush()
        AuditService(db).inserted(None, h)
        db.flush()  # both rows exist inside the transaction...
        assert db.execute(text("SELECT count(*) FROM audit_logs WHERE record_id = :i"), {"i": h.id}).scalar() == 1
        db.rollback()  # ...and both disappear with it
        assert db.execute(text("SELECT count(*) FROM hospitals WHERE id = :i"), {"i": h.id}).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM audit_logs WHERE record_id = :i"), {"i": h.id}).scalar() == 0


# ---- secrets -------------------------------------------------------------------------------
def test_no_password_hash_or_token_ever_reaches_audit_logs(client, world):
    admin = auth(client, world["admin"])
    token = admin["Authorization"].split()[1]
    r = client.post(f"{API}/users", headers=admin, json=dict(
        email=f"secret-{world['sfx']}@b2.test", full_name="Secret", password="Plain-Text-Pass-9",
        role="technician", hospital_id=world["h1"]))
    uid = r.json()["id"]
    client.post(f"{API}/users/{uid}/reset-password", headers=admin, json={"new_password": "Another-Pass-77"})
    staff = auth(client, world["staff"])
    client.post(f"{API}/auth/change-password", headers=staff, json={"current_password": PW, "new_password": "Third-Pass-555"})
    with get_session_factory()() as db:
        dump = " ".join(db.execute(text(
            "SELECT coalesce(old_values::text, '') || ' ' || coalesce(new_values::text, '') FROM audit_logs "
            "WHERE organization_id = :o"), {"o": world["org"]}).scalars())
        hashes = db.execute(text("SELECT password_hash FROM users WHERE organization_id = :o"), {"o": world["org"]}).scalars().all()
    assert dump  # rows exist
    for secret in ("Plain-Text-Pass-9", "Another-Pass-77", "Third-Pass-555", PW, token, "$argon2", "password_hash", *hashes):
        assert secret not in dump


# ---- command-line script (no acting user) ---------------------------------------------------
def _run_script(monkeypatch, *argv, password="Script-Pass-123"):
    import sys
    from scripts import create_user
    monkeypatch.setenv("IMEDORA_USER_PASSWORD", password)
    monkeypatch.setattr(sys, "argv", ["create_user", *argv])
    create_user.main()


def test_create_user_script_changes_are_audited_without_an_acting_user(world, monkeypatch, capsys):
    sfx = world["sfx"]
    email = f"cli-{sfx}@b2.test"
    _run_script(monkeypatch, "--email", email, "--organization-code", f"B2-{sfx}",
                "--full-name", "Cli User", "--role", "technician", "--hospital-code", "H1")
    with get_session_factory()() as db:
        uid = db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar()
    ins = one("users", uid, AuditAction.INSERT)
    assert ins.user_id is None and str(ins.organization_id) == world["org"]

    _run_script(monkeypatch, "--email", email, "--organization-code", f"B2-{sfx}", "--reset-password")
    reset = [r for r in rows("users", uid) if r.action == AuditAction.UPDATE][-1]
    assert reset.user_id is None and reset.new_values == {"password_changed": True}
