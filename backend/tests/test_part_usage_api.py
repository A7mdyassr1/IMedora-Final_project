"""B5 CP2 - spare parts used in maintenance against REAL PostgreSQL: the database trigger moves the
stock, the API checks under row locks, a record and its parts are one transaction, who may add or
correct usage, hospital isolation, the usage report, the stock history, and concurrent consumption.
Skipped unless TEST_DATABASE_URL is set; everything created here is removed (tests/ticket_scene.py).
"""
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.database import get_session_factory
from app.core.db_errors import describe_integrity_error, describe_trigger_error
from tests.parts_scene import stock  # noqa: F401
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API


def _err(r, status, code=None):
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text
    return r.json()["error"]


def _me(client, headers):
    return client.get(f"{API}/auth/me", headers=headers).json()["id"]


def _ticket_in_progress(client, s, device="icu", tech="tech_h1"):
    h = s["h"]
    tid = s["report"](h["dept_icu"], device).json()["id"]
    assert client.post(f"{API}/tickets/{tid}/assignments", headers=h["eng_h1"],
                       json={"user_id": _me(client, h[tech])}).status_code == 201
    assert client.patch(f"{API}/tickets/{tid}/status", headers=h[tech], json={"status": "in_progress"}).status_code == 200
    return tid


@pytest.fixture
def work(stock, client):
    """Two parts stocked at H1 (5 and 2), one only at H2, a corrective type, a ticket in progress."""
    a, b, only_h2 = stock["part"]("Power Supply"), stock["part"]("Fuse"), stock["part"]("Bellows")
    inv_a, inv_b = stock["stock_row"](a["id"], "h1", 5), stock["stock_row"](b["id"], "h1", 2)
    stock["stock_row"](only_h2["id"], "h2", 9)
    mtype = stock["mtype"]("corrective")
    tid = _ticket_in_progress(client, stock)

    def record(headers=None, parts=(), ticket_id=tid, device="icu"):
        return client.post(f"{API}/maintenance-records", headers=headers or stock["h"]["tech_h1"], json={
            "device_id": stock["d"][device]["id"], "maintenance_type_id": mtype, "description": "Replaced the PSU",
            "ticket_id": ticket_id, "parts": [{"part_id": p, "quantity": q} for p, q in parts]})

    return dict(stock, a=a, b=b, only_h2=only_h2, inv_a=inv_a, inv_b=inv_b, mtype=mtype, tid=tid, record=record)


# ---- a record and its parts -----------------------------------------------------------------------
def test_record_with_parts_takes_them_from_the_hospital_stock(client, work):
    r = work["record"](parts=[(work["a"]["id"], 2), (work["b"]["id"], 1)])
    assert r.status_code == 201, r.text
    rec = r.json()
    assert sorted((p["part"]["part_number"], p["quantity"]) for p in rec["parts"]) == sorted(
        [(work["a"]["part_number"], 2), (work["b"]["part_number"], 1)])
    assert work["quantity"](work["inv_a"]["id"]) == 3 and work["quantity"](work["inv_b"]["id"]) == 1

    moves = client.get(f"{API}/inventory/{work['inv_a']['id']}/movements", headers=work["h"]["tech_h1"]).json()
    assert [(m["kind"], m["quantity_change"], m["quantity_after"], m["maintenance_record_id"]) for m in moves["movements"]] == [
        ("opening", 5, 5, None), ("usage", -2, 3, rec["id"])]
    assert moves["untracked_change"] == 0 and moves["movements"][1]["by"]["role"] == "technician"

    # the record, its usage lines, the stock change and their audit rows are ONE transaction
    (xmin, ), = work["sql"]("SELECT xmin::text FROM maintenance_records WHERE id = :r", r=rec["id"])
    usage_x = work["sql"]("SELECT DISTINCT xmin::text FROM maintenance_parts WHERE maintenance_record_id = :r", r=rec["id"])
    audit_x = work["sql"]("SELECT DISTINCT a.xmin::text FROM audit_logs a WHERE (a.table_name = 'maintenance_parts' AND "
                          "a.new_values->>'maintenance_record_id' = :r) OR (a.table_name = 'part_inventory' AND "
                          "a.new_values->'movement'->>'maintenance_record_id' = :r)", r=rec["id"])
    assert usage_x == [(xmin,)] and audit_x == [(xmin,)]

    # the record list and detail show the parts; the ticket can now be resolved through the API alone
    listed = client.get(f"{API}/maintenance-records", headers=work["h"]["eng_h1"], params={"ticket_id": work["tid"]}).json()
    assert len(listed["items"][0]["parts"]) == 2
    assert client.patch(f"{API}/tickets/{work['tid']}/status", headers=work["h"]["tech_h1"],
                        json={"status": "resolved"}).status_code == 200


def test_not_enough_stock_records_nothing(client, work):
    before = work["sql"]("SELECT count(*) FROM audit_logs WHERE organization_id = :o", o=work["world"]["org"])[0][0]
    err = _err(work["record"](parts=[(work["a"]["id"], 1), (work["b"]["id"], 3)]), 409, "insufficient_stock")
    assert err["details"] == [{"part_id": work["b"]["id"], "available": 2, "requested": 3}]
    assert work["quantity"](work["inv_a"]["id"]) == 5 and work["quantity"](work["inv_b"]["id"]) == 2
    assert not work["sql"]("SELECT 1 FROM maintenance_records WHERE ticket_id = :t", t=work["tid"])
    assert work["sql"]("SELECT count(*) FROM audit_logs WHERE organization_id = :o", o=work["world"]["org"])[0][0] == before


def test_parts_must_exist_and_be_stocked_at_the_devices_hospital(client, work):
    _err(work["record"](parts=[(work["only_h2"]["id"], 1)]), 409, "part_not_stocked")   # stocked elsewhere only
    _err(work["record"](parts=[(str(uuid.uuid4()), 1)]), 400)
    _err(work["record"](parts=[(work["a"]["id"], 1), (work["a"]["id"], 1)]), 422)        # one line per part
    _err(work["record"](parts=[(work["a"]["id"], 0)]), 422)
    _err(work["record"](parts=[(str(uuid.uuid4()), 1) for _ in range(21)]), 422)       # at most 20 lines
    assert not work["sql"]("SELECT 1 FROM maintenance_records WHERE ticket_id = :t", t=work["tid"])


# ---- adding to and correcting a record --------------------------------------------------------------
def test_who_may_add_and_correct_parts(client, work):
    h = work["h"]
    rec = work["record"]().json()
    url = f"{API}/maintenance-records/{rec['id']}/parts"
    other_tech = work["add_user"]("tech-two", "technician", "h1")

    _err(client.post(url, headers=other_tech, json={"part_id": work["a"]["id"], "quantity": 1}), 403)  # not the performer
    _err(client.post(url, headers=h["dept_icu"], json={"part_id": work["a"]["id"], "quantity": 1}), 403)
    _err(client.post(url, headers=h["eng_h2"], json={"part_id": work["a"]["id"], "quantity": 1}), 404)
    _err(client.post(url, headers=h["tech_h2"], json={"part_id": work["a"]["id"], "quantity": 1}), 404)

    r = client.post(url, headers=h["tech_h1"], json={"part_id": work["a"]["id"], "quantity": 1})  # the performer
    assert r.status_code == 201 and [p["quantity"] for p in r.json()["parts"]] == [1]
    _err(client.post(url, headers=h["eng_h1"], json={"part_id": work["a"]["id"], "quantity": 1}), 409, "conflict")
    assert client.post(url, headers=h["eng_h1"], json={"part_id": work["b"]["id"], "quantity": 2}).status_code == 201
    assert work["quantity"](work["inv_a"]["id"]) == 4 and work["quantity"](work["inv_b"]["id"]) == 0

    line = f"{url}/{work['a']['id']}"
    _err(client.patch(line, headers=h["tech_h1"], json={"quantity": 2}), 403)  # corrections: engineers / admins
    _err(client.delete(line, headers=h["tech_h1"]), 403)
    r = client.patch(line, headers=h["eng_h1"], json={"quantity": 4})
    assert r.status_code == 200 and work["quantity"](work["inv_a"]["id"]) == 1
    _err(client.patch(line, headers=h["eng_h1"], json={"quantity": 6}), 409, "insufficient_stock")  # needs 2 more, 1 left
    assert client.patch(line, headers=h["admin"], json={"quantity": 1}).status_code == 200
    assert work["quantity"](work["inv_a"]["id"]) == 4
    assert client.patch(line, headers=h["admin"], json={"quantity": 1}).status_code == 200            # no change
    r = client.delete(f"{url}/{work['b']['id']}", headers=h["eng_h1"])
    assert r.status_code == 200 and [p["part"]["id"] for p in r.json()["parts"]] == [work["a"]["id"]]
    assert work["quantity"](work["inv_b"]["id"]) == 2
    _err(client.delete(f"{url}/{work['b']['id']}", headers=h["eng_h1"]), 404)

    kinds = [(m["kind"], m["quantity_change"]) for m in
             client.get(f"{API}/inventory/{work['inv_a']['id']}/movements", headers=h["admin"]).json()["movements"]]
    assert kinds == [("opening", 5), ("usage", -1), ("usage_change", -3), ("usage_change", 3)]
    kinds_b = [m["kind"] for m in client.get(f"{API}/inventory/{work['inv_b']['id']}/movements", headers=h["admin"]).json()["movements"]]
    assert kinds_b == ["opening", "usage", "usage_return"]
    assert work["sql"]("SELECT action::text FROM audit_logs WHERE table_name = 'maintenance_parts' AND "
                       "old_values->>'part_id' = :p", p=work["b"]["id"]) == [("delete",)]


def test_usage_on_a_closed_ticket_is_final(client, work):
    h = work["h"]
    rec = work["record"](parts=[(work["a"]["id"], 1)]).json()
    assert client.patch(f"{API}/tickets/{work['tid']}/status", headers=h["tech_h1"], json={"status": "resolved"}).status_code == 200
    # resolved: still correctable
    assert client.patch(f"{API}/maintenance-records/{rec['id']}/parts/{work['a']['id']}", headers=h["eng_h1"],
                        json={"quantity": 2}).status_code == 200
    assert client.patch(f"{API}/tickets/{work['tid']}/status", headers=h["eng_h1"], json={"status": "closed"}).status_code == 200
    url = f"{API}/maintenance-records/{rec['id']}/parts"
    _err(client.post(url, headers=h["eng_h1"], json={"part_id": work["b"]["id"], "quantity": 1}), 409)
    _err(client.patch(f"{url}/{work['a']['id']}", headers=h["eng_h1"], json={"quantity": 1}), 409)
    _err(client.delete(f"{url}/{work['a']['id']}", headers=h["admin"]), 409)
    assert work["quantity"](work["inv_a"]["id"]) == 3


def test_archived_device_and_inactive_hospital(client, work):
    h, world = work["h"], work["world"]
    rec = work["record"](parts=[(work["a"]["id"], 1)]).json()
    url = f"{API}/maintenance-records/{rec['id']}/parts"
    work["sql"]("UPDATE devices SET deleted_at = now() WHERE id = :d", d=work["d"]["icu"]["id"])
    try:
        _err(client.post(url, headers=h["eng_h1"], json={"part_id": work["b"]["id"], "quantity": 1}), 400)
        assert client.patch(f"{url}/{work['a']['id']}", headers=h["eng_h1"], json={"quantity": 2}).status_code == 200
    finally:
        work["sql"]("UPDATE devices SET deleted_at = NULL WHERE id = :d", d=work["d"]["icu"]["id"])
    # inactive hospital (H2: its own staff can no longer log in, the H1 admin acts): stock is read-only
    h2_rec = client.post(f"{API}/maintenance-records", headers=h["eng_h2"], json={
        "device_id": work["d"]["h2"]["id"], "maintenance_type_id": work["mtype"], "description": "Service",
        "parts": [{"part_id": work["only_h2"]["id"], "quantity": 1}]}).json()
    h2_url = f"{API}/maintenance-records/{h2_rec['id']}/parts/{work['only_h2']['id']}"
    work["sql"]("UPDATE hospitals SET is_active = false WHERE id = :h", h=world["h2"])
    try:
        _err(client.patch(h2_url, headers=h["admin"], json={"quantity": 2}), 400)
        _err(client.delete(h2_url, headers=h["admin"]), 400)
    finally:
        work["sql"]("UPDATE hospitals SET is_active = true WHERE id = :h", h=world["h2"])
    assert client.patch(h2_url, headers=h["admin"], json={"quantity": 2}).status_code == 200


# ---- usage report -----------------------------------------------------------------------------------
def test_usage_report_is_scoped_and_filterable(client, work):
    h = work["h"]
    rec = work["record"](parts=[(work["a"]["id"], 2), (work["b"]["id"], 1)]).json()
    rows = client.get(f"{API}/part-usage", headers=h["tech_h1"], params={"ticket_id": work["tid"]}).json()
    assert rows["total"] == 2 and {r["maintenance_record_id"] for r in rows["items"]} == {rec["id"]}
    assert {r["ticket_number"] for r in rows["items"]} == {rec["ticket_number"]}
    by_part = client.get(f"{API}/part-usage", headers=h["eng_h1"], params={"part_id": work["a"]["id"]}).json()
    assert [(r["quantity"], r["device_id"]) for r in by_part["items"]] == [(2, work["d"]["icu"]["id"])]
    assert client.get(f"{API}/part-usage", headers=h["tech_h2"], params={"ticket_id": work["tid"]}).json()["total"] == 0
    assert client.get(f"{API}/part-usage", headers=h["admin"], params={"part_id": work["a"]["id"]}).json()["total"] == 1
    _err(client.get(f"{API}/part-usage", headers=h["dept_icu"]), 403)


# ---- the database stays the last line of defence --------------------------------------------------------
def test_database_rules_behind_the_api_map_to_the_same_errors(work):
    """Writing usage directly (bypassing the API's checks): the trigger and the CHECK still refuse,
    and their real PostgreSQL errors map to the API's 409 codes."""
    rec = work["record"]().json()
    with get_session_factory()() as db:
        with pytest.raises(DBAPIError) as unstocked:
            db.execute(text("INSERT INTO maintenance_parts (maintenance_record_id, part_id, quantity) VALUES (:r, :p, 1)"),
                       {"r": rec["id"], "p": work["only_h2"]["id"]})
        db.rollback()
        with pytest.raises(IntegrityError) as oversold:
            db.execute(text("INSERT INTO maintenance_parts (maintenance_record_id, part_id, quantity) VALUES (:r, :p, 99)"),
                       {"r": rec["id"], "p": work["a"]["id"]})
        db.rollback()
    assert describe_trigger_error(unstocked.value)[:2] == (409, "part_not_stocked")
    assert describe_integrity_error(oversold.value)[:2] == (409, "insufficient_stock")
    assert work["quantity"](work["inv_a"]["id"]) == 5


# ---- concurrency --------------------------------------------------------------------------------------
def test_concurrent_consumption_never_oversells(client, work):
    """Five technicians' records each use 1 of the last 2 fuses at the same moment: the stock row is
    locked, so exactly 2 records are created, 3 get 409 insufficient_stock, and the stock ends at 0."""
    h = work["h"]
    tickets_ = [_ticket_in_progress(client, work) for _ in range(5)]
    results = [None] * 5
    with get_session_factory()() as holder:
        holder.execute(text("SELECT id FROM part_inventory WHERE id = :i FOR UPDATE"), {"i": work["inv_b"]["id"]})

        def run(i):
            with TestClient(client.app) as c:
                results[i] = c.post(f"{API}/maintenance-records", headers=h["tech_h1"], json={
                    "device_id": work["d"]["icu"]["id"], "maintenance_type_id": work["mtype"], "description": f"fix {i}",
                    "ticket_id": tickets_[i], "parts": [{"part_id": work["b"]["id"], "quantity": 1}]})

        threads = [threading.Thread(target=run, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        time.sleep(1.0)
        blocked = [t.is_alive() for t in threads]
        holder.rollback()
    for t in threads:
        t.join(timeout=30)
    assert blocked == [True] * 5, "usage did not wait for the stock row lock"
    assert sorted(r.status_code for r in results) == [201, 201, 409, 409, 409]
    assert work["quantity"](work["inv_b"]["id"]) == 0
    created = work["sql"]("SELECT count(*) FROM maintenance_records WHERE ticket_id = ANY(:t)",
                          t=[uuid.UUID(t) for t in tickets_])[0][0]
    assert created == 2
    moves = client.get(f"{API}/inventory/{work['inv_b']['id']}/movements", headers=h["admin"]).json()
    assert [m["quantity_after"] for m in moves["movements"]] == [2, 1, 0] and moves["untracked_change"] == 0
