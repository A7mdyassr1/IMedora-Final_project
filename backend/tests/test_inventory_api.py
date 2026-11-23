"""B5 CP1 - parts catalog and hospital stock against REAL PostgreSQL: permissions, hospital isolation,
stock adjustments that never go below zero, the stock history, audit in the same transaction, and
row locking under concurrent adjustments. Skipped unless TEST_DATABASE_URL is set; everything
created here is removed (tests/ticket_scene.py).
"""
import threading
import time

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import get_session_factory
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


# ---- catalog --------------------------------------------------------------------------------------
def test_catalog_permissions_normalisation_and_duplicates(client, stock):
    h, sfx = stock["h"], stock["world"]["sfx"]
    r = client.post(f"{API}/parts", headers=h["eng_h1"],
                    json={"name": "  Oxygen Sensor ", "part_number": f" pn-o2-{sfx} ", "unit": " Piece "})
    assert r.status_code == 201, r.text
    part = r.json()
    assert (part["name"], part["part_number"], part["unit"]) == ("Oxygen Sensor", f"PN-O2-{sfx.upper()}", "piece")

    _err(client.post(f"{API}/parts", headers=h["eng_h1"], json={"name": "Dup", "part_number": f"PN-O2-{sfx}"}),
         409, "conflict")
    _err(client.post(f"{API}/parts", headers=h["tech_h1"], json={"name": "X", "part_number": f"PN-X-{sfx}"}), 403)
    _err(client.post(f"{API}/parts", headers=h["dept_icu"], json={"name": "X", "part_number": f"PN-X-{sfx}"}), 403)
    _err(client.post(f"{API}/parts", headers=h["admin"], json={"name": "X", "part_number": "HAS SPACE"}), 422)
    _err(client.post(f"{API}/parts", headers=h["admin"],
                     json={"name": "X", "part_number": f"PN-Y-{sfx}", "organization_id": "x"}), 422)

    # technicians read the catalog; department users do not
    assert client.get(f"{API}/parts/{part['id']}", headers=h["tech_h2"]).status_code == 200
    listed = client.get(f"{API}/parts", headers=h["tech_h1"], params={"q": f"o2-{sfx}"}).json()
    assert [p["id"] for p in listed["items"]] == [part["id"]]
    _err(client.get(f"{API}/parts", headers=h["dept_icu"]), 403)
    # LIKE wildcards in q are matched literally, not as patterns
    assert client.get(f"{API}/parts", headers=h["admin"], params={"q": f"%{sfx}%_"}).json()["total"] == 0

    r = client.patch(f"{API}/parts/{part['id']}", headers=h["admin"], json={"description": "Paramagnetic", "unit": "PIECE"})
    assert r.status_code == 200 and r.json()["description"] == "Paramagnetic"
    _err(client.patch(f"{API}/parts/{part['id']}", headers=h["admin"], json={"name": None}), 422)
    _err(client.patch(f"{API}/parts/{part['id']}", headers=h["admin"], json={}), 422)
    other = stock["part"]("Fuse")
    _err(client.patch(f"{API}/parts/{other['id']}", headers=h["admin"], json={"part_number": part["part_number"].lower()}),
         409)
    _err(client.patch(f"{API}/parts/{part['id']}", headers=h["tech_h1"], json={"name": "Nope"}), 403)

    audit = stock["sql"]("SELECT action::text FROM audit_logs WHERE table_name = 'parts' AND record_id = :p ORDER BY created_at",
                         p=part["id"])
    assert [a[0] for a in audit] == ["insert", "update"]


def test_a_part_can_only_be_deleted_while_unused(client, stock):
    h = stock["h"]
    unused, stocked = stock["part"]("Spare Bulb"), stock["part"]("Cuff")
    stock["stock_row"](stocked["id"])
    _err(client.delete(f"{API}/parts/{stocked['id']}", headers=h["eng_h1"]), 409, "in_use")
    assert client.get(f"{API}/parts/{stocked['id']}", headers=h["admin"]).status_code == 200  # still there
    # the refused delete wrote no audit row (same transaction)
    assert not stock["sql"]("SELECT 1 FROM audit_logs WHERE record_id = :p AND action = 'delete'", p=stocked["id"])
    _err(client.delete(f"{API}/parts/{unused['id']}", headers=h["tech_h1"]), 403)
    assert client.delete(f"{API}/parts/{unused['id']}", headers=h["eng_h1"]).status_code == 204
    _err(client.get(f"{API}/parts/{unused['id']}", headers=h["admin"]), 404)
    assert stock["sql"]("SELECT 1 FROM audit_logs WHERE record_id = :p AND action = 'delete'", p=unused["id"])


# ---- stock rows -----------------------------------------------------------------------------------
def test_stock_rows_are_created_per_hospital_by_engineers_and_admins(client, stock):
    h, world = stock["h"], stock["world"]
    part = stock["part"]("Bellows Kit", unit="kit")
    r = client.post(f"{API}/inventory", headers=h["eng_h1"], json={"part_id": part["id"], "quantity_on_hand": 4,
                                                                  "reorder_threshold": 2, "reason": "initial count"})
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["hospital"]["id"] == world["h1"] and row["quantity_on_hand"] == 4 and row["is_low_stock"] is False
    assert row["part"]["unit"] == "kit"

    _err(client.post(f"{API}/inventory", headers=h["eng_h1"], json={"part_id": part["id"]}), 409, "conflict")
    _err(client.post(f"{API}/inventory", headers=h["eng_h1"], json={"part_id": part["id"], "hospital_id": world["h2"]}), 400)
    _err(client.post(f"{API}/inventory", headers=h["eng_h1"], json={"part_id": part["id"], "hospital_id": world["oh"]}), 400)
    _err(client.post(f"{API}/inventory", headers=h["tech_h1"], json={"part_id": part["id"]}), 403)
    _err(client.post(f"{API}/inventory", headers=h["dept_icu"], json={"part_id": part["id"]}), 403)
    _err(client.post(f"{API}/inventory", headers=h["admin"], json={"part_id": world["org"], "hospital_id": world["h2"]}), 400)
    _err(client.post(f"{API}/inventory", headers=h["admin"], json={"part_id": part["id"], "hospital_id": world["h2"],
                                                                   "quantity_on_hand": -1}), 422)
    r = client.post(f"{API}/inventory", headers=h["admin"], json={"part_id": part["id"], "hospital_id": world["h2"]})
    assert r.status_code == 201 and r.json()["quantity_on_hand"] == 0

    # nothing new in an inactive hospital (Decision 6)
    other = stock["part"]("Probe")
    stock["sql"]("UPDATE hospitals SET is_active = false WHERE id = :h", h=world["h2"])
    try:
        _err(client.post(f"{API}/inventory", headers=h["admin"], json={"part_id": other["id"], "hospital_id": world["h2"]}),
             400)
    finally:
        stock["sql"]("UPDATE hospitals SET is_active = true WHERE id = :h", h=world["h2"])


def test_stock_is_isolated_per_hospital(client, stock):
    h = stock["h"]
    part = stock["part"]("Screen Module")
    h1_row, h2_row = stock["stock_row"](part["id"], "h1", 3), stock["stock_row"](part["id"], "h2", 7)

    for who, visible in (("tech_h1", h1_row), ("eng_h1", h1_row), ("tech_h2", h2_row), ("eng_h2", h2_row)):
        ids = {i["id"] for i in client.get(f"{API}/inventory", headers=h[who], params={"part_id": part["id"]}).json()["items"]}
        assert ids == {visible["id"]}, who
        hidden = h2_row if visible is h1_row else h1_row
        _err(client.get(f"{API}/inventory/{hidden['id']}", headers=h[who]), 404)
        _err(client.get(f"{API}/inventory/{hidden['id']}/movements", headers=h[who]), 404)
        _err(client.post(f"{API}/inventory/{hidden['id']}/adjustments", headers=h[who],
                         json={"kind": "restock", "quantity_change": 1, "reason": "x"}), 404)
    admin_ids = {i["id"] for i in client.get(f"{API}/inventory", headers=h["admin"], params={"part_id": part["id"]}).json()["items"]}
    assert admin_ids == {h1_row["id"], h2_row["id"]}
    _err(client.get(f"{API}/inventory", headers=h["dept_icu"]), 403)
    _err(client.get(f"{API}/inventory/{h1_row['id']}", headers=h["dept_icu"]), 403)


def test_adjustments_never_go_below_zero_and_build_the_history(client, stock):
    h = stock["h"]
    part = stock["part"]("Filter Cartridge")
    row = stock["stock_row"](part["id"], "h1", 5, threshold=2)
    url = f"{API}/inventory/{row['id']}/adjustments"

    r = client.post(url, headers=h["eng_h1"], json={"kind": "restock", "quantity_change": 10, "reason": "PO-1001 received"})
    assert r.status_code == 200 and r.json()["quantity_on_hand"] == 15
    r = client.post(url, headers=h["admin"], json={"kind": "correction", "quantity_change": -14, "reason": "stock count"})
    assert r.status_code == 200 and r.json()["quantity_on_hand"] == 1 and r.json()["is_low_stock"] is True
    err = _err(client.post(url, headers=h["eng_h1"], json={"kind": "correction", "quantity_change": -2, "reason": "lost"}),
               409, "insufficient_stock")
    assert err["details"] == [{"available": 1, "requested": 2}]
    assert stock["quantity"](row["id"]) == 1

    _err(client.post(url, headers=h["eng_h1"], json={"kind": "restock", "quantity_change": -1, "reason": "x"}), 422)
    _err(client.post(url, headers=h["eng_h1"], json={"kind": "correction", "quantity_change": 0, "reason": "x"}), 422)
    _err(client.post(url, headers=h["eng_h1"], json={"kind": "correction", "quantity_change": 1, "reason": "  "}), 422)
    _err(client.post(url, headers=h["eng_h1"], json={"kind": "restock", "quantity_change": 1}), 422)
    _err(client.post(url, headers=h["tech_h1"], json={"kind": "restock", "quantity_change": 1, "reason": "x"}), 403)
    _err(client.patch(f"{API}/inventory/{row['id']}", headers=h["eng_h1"], json={"quantity_on_hand": 99}), 422)

    history = client.get(f"{API}/inventory/{row['id']}/movements", headers=h["tech_h1"]).json()
    moves = [(m["kind"], m["quantity_change"], m["quantity_after"], m["reason"]) for m in history["movements"]]
    assert moves == [("opening", 5, 5, "opening stock"), ("restock", 10, 15, "PO-1001 received"),
                     ("correction", -14, 1, "stock count")]
    assert history["untracked_change"] == 0 and history["inventory"]["quantity_on_hand"] == 1
    assert history["movements"][2]["by"]["role"] == "admin"

    # a change made directly in the database (seed data, imports) is reported, not hidden
    stock["sql"]("UPDATE part_inventory SET quantity_on_hand = quantity_on_hand + 3 WHERE id = :i", i=row["id"])
    assert client.get(f"{API}/inventory/{row['id']}/movements", headers=h["admin"]).json()["untracked_change"] == 3


def test_threshold_is_a_setting_not_a_movement(client, stock):
    h = stock["h"]
    part = stock["part"]("Temperature Probe")
    row = stock["stock_row"](part["id"], "h1", 3)
    r = client.patch(f"{API}/inventory/{row['id']}", headers=h["eng_h1"], json={"reorder_threshold": 3})
    assert r.status_code == 200 and r.json()["is_low_stock"] is True
    low = client.get(f"{API}/inventory", headers=h["tech_h1"], params={"low_stock": True, "part_id": part["id"]}).json()
    assert low["total"] == 1
    r = client.patch(f"{API}/inventory/{row['id']}", headers=h["eng_h1"], json={"reorder_threshold": None})
    assert r.status_code == 200 and r.json()["reorder_threshold"] is None and r.json()["is_low_stock"] is False
    _err(client.patch(f"{API}/inventory/{row['id']}", headers=h["eng_h1"], json={}), 422)
    _err(client.patch(f"{API}/inventory/{row['id']}", headers=h["eng_h2"], json={"reorder_threshold": 1}), 404)
    _err(client.patch(f"{API}/inventory/{row['id']}", headers=h["tech_h1"], json={"reorder_threshold": 1}), 403)
    moves = client.get(f"{API}/inventory/{row['id']}/movements", headers=h["admin"]).json()["movements"]
    assert [m["kind"] for m in moves] == ["opening"]


def test_inactive_hospital_stock_is_read_only(client, stock):
    h, world = stock["h"], stock["world"]
    part = stock["part"]("Speaker Module")
    row = stock["stock_row"](part["id"], "h2", 2)
    stock["sql"]("UPDATE hospitals SET is_active = false WHERE id = :h", h=world["h2"])
    try:
        _err(client.post(f"{API}/inventory/{row['id']}/adjustments", headers=h["admin"],
                         json={"kind": "restock", "quantity_change": 1, "reason": "x"}), 400)
        _err(client.patch(f"{API}/inventory/{row['id']}", headers=h["admin"], json={"reorder_threshold": 1}), 400)
        assert client.get(f"{API}/inventory/{row['id']}", headers=h["admin"]).status_code == 200
    finally:
        stock["sql"]("UPDATE hospitals SET is_active = true WHERE id = :h", h=world["h2"])


def test_adjustment_and_its_audit_row_commit_together(client, stock):
    h = stock["h"]
    part = stock["part"]("Circuit Board")
    row = stock["stock_row"](part["id"], "h1", 1)
    client.post(f"{API}/inventory/{row['id']}/adjustments", headers=h["eng_h1"],
                json={"kind": "restock", "quantity_change": 2, "reason": "delivery"})
    (xmin_row, ), = stock["sql"]("SELECT xmin::text FROM part_inventory WHERE id = :i", i=row["id"])
    audit = stock["sql"]("SELECT xmin::text, new_values->'movement'->>'kind' FROM audit_logs WHERE table_name = 'part_inventory' "
                         "AND record_id = :i AND action = 'update'", i=row["id"])
    assert audit == [(xmin_row, "restock")]


def test_concurrent_withdrawals_never_oversell(client, stock):
    """Ten parallel corrections of -1 on a stock of 4: the stock row is locked, so exactly 4 succeed,
    6 get 409 insufficient_stock, and the stock ends at 0 with 4 recorded movements."""
    h = stock["h"]
    part = stock["part"]("Fuse Five")
    row = stock["stock_row"](part["id"], "h1", 4)
    url = f"{API}/inventory/{row['id']}/adjustments"
    results = [None] * 10
    with get_session_factory()() as holder:
        holder.execute(text("SELECT id FROM part_inventory WHERE id = :i FOR UPDATE"), {"i": row["id"]})

        def run(i):
            with TestClient(client.app) as c:
                results[i] = c.post(url, headers=h["eng_h1"],
                                    json={"kind": "correction", "quantity_change": -1, "reason": f"take {i}"})

        threads = [threading.Thread(target=run, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        time.sleep(1.0)
        blocked = [t.is_alive() for t in threads]
        holder.rollback()
    for t in threads:
        t.join(timeout=30)
    assert blocked == [True] * 10, "adjustments did not wait for the stock row lock"
    codes = sorted(r.status_code for r in results)
    assert codes == [200] * 4 + [409] * 6
    assert all(r.json()["error"]["code"] == "insufficient_stock" for r in results if r.status_code == 409)
    assert stock["quantity"](row["id"]) == 0
    moves = client.get(f"{API}/inventory/{row['id']}/movements", headers=h["admin"]).json()
    assert [m["quantity_after"] for m in moves["movements"]] == [4, 3, 2, 1, 0] and moves["untracked_change"] == 0
