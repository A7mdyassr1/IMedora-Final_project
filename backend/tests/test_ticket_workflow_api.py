"""B4 CP2 - ticket workflow against REAL PostgreSQL: status transitions, assignments, priority,
soft delete, the approved permission rules (Q4-Q8), audit in the same transaction, timeline v2,
and row locking under concurrent requests. Skipped unless TEST_DATABASE_URL is set.

Maintenance records are inserted directly (tests/ticket_scene.py `record`): their API arrives in CP3.
"""
import threading
import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import get_session_factory
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API


def _me(client, headers):
    return client.get(f"{API}/auth/me", headers=headers).json()["id"]


def _status(client, headers, tid, status):
    return client.patch(f"{API}/tickets/{tid}/status", headers=headers, json={"status": status})


def _assign(client, headers, tid, user_id):
    return client.post(f"{API}/tickets/{tid}/assignments", headers=headers, json={"user_id": user_id})


def _unassign(client, headers, tid, user_id):
    return client.delete(f"{API}/tickets/{tid}/assignments/{user_id}", headers=headers)


def _err(r, status, code=None, message=None):
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text
    if message:
        assert r.json()["error"]["message"] == message, r.text


def _assigned_ticket(tickets, client, device="icu", reporter="dept_icu"):
    h = tickets["h"]
    tid = tickets["report"](h[reporter], device).json()["id"]
    assert _assign(client, h["eng_h1" if device != "h2" else "eng_h2"], tid,
                   tickets["world"]["tech_id"] if device != "h2" else _me(client, h["tech_h2"])).status_code == 201
    return tid


# ---- the whole life of a ticket -------------------------------------------------------------------
def test_full_lifecycle_report_assign_work_resolve_close(client, tickets):
    h, w, sql = tickets["h"], tickets["world"], tickets["sql"]
    device_before = client.get(f"{API}/devices/{tickets['d']['icu']['id']}", headers=h["admin"]).json()["status"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]

    r = _assign(client, h["eng_h1"], tid, w["tech_id"])
    assert r.status_code == 201 and r.json()["status"] == "assigned"
    assert [a["id"] for a in r.json()["assignees"]] == [w["tech_id"]]
    for status in ("in_progress", "waiting_for_parts", "in_progress"):
        r = _status(client, h["tech_h1"], tid, status)
        assert r.status_code == 200 and r.json()["status"] == status
    _err(_status(client, h["tech_h1"], tid, "resolved"), 409, "maintenance_record_required",
         "Add a maintenance record for this ticket before resolving it.")
    tickets["record"](tid)
    r = _status(client, h["tech_h1"], tid, "resolved")
    assert r.status_code == 200 and r.json()["resolved_at"] is not None
    resolved_at = r.json()["resolved_at"]
    r = _status(client, h["eng_h1"], tid, "closed")
    assert r.status_code == 200 and r.json()["status"] == "closed" and r.json()["resolved_at"] == resolved_at
    assert r.json()["assignees"][0]["id"] == w["tech_id"]  # assignments stay as history

    staff = [(i["kind"], i["status"]) for i in r.json()["timeline"]]
    # B4 CP3 (timeline v3): the linked maintenance record now appears as "work_performed"
    assert staff == [("created", "open"), ("assigned", "assigned"), ("status_changed", "in_progress"),
                     ("status_changed", "waiting_for_parts"), ("status_changed", "in_progress"),
                     ("work_performed", "in_progress"), ("status_changed", "resolved"), ("status_changed", "closed")]
    assert r.json()["timeline"][5]["message"] == "Work performed: Replaced the power supply"
    # Q8: the device's status is never changed by the ticket workflow
    assert client.get(f"{API}/devices/{tickets['d']['icu']['id']}", headers=h["admin"]).json()["status"] == device_before
    # the reporter follows it all - with roles instead of staff names (Q9)
    own = client.get(f"{API}/tickets/{tid}", headers=h["dept_icu"]).json()
    assert own["timeline"][1]["message"] == "Assigned to Technician." and own["timeline"][1]["actor"] == "Biomedical engineer"
    assert own["timeline"][2]["actor"] == "Technician" and own["status"] == "closed"
    assert w["tech"].split("@")[0] not in client.get(f"{API}/tickets/{tid}", headers=h["dept_icu"]).text
    rows = sql("SELECT action::text, new_values->>'status' FROM audit_logs WHERE table_name = 'maintenance_tickets' "
               "AND record_id = :t ORDER BY created_at", t=tid)
    assert [r[1] for r in rows] == ["open", "assigned", "in_progress", "waiting_for_parts", "in_progress", "resolved", "closed"]


def test_assignment_and_its_status_change_are_audited_in_one_transaction(client, tickets):
    h, w, sql = tickets["h"], tickets["world"], tickets["sql"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    eng_id = _me(client, h["eng_h1"])
    assert _assign(client, h["eng_h1"], tid, w["tech_id"]).status_code == 201
    a_id, a_xmin = sql("SELECT id::text, xmin::text FROM ticket_assignments WHERE ticket_id = :t", t=tid)[0]
    t_xmin = sql("SELECT xmin::text FROM maintenance_tickets WHERE id = :t", t=tid)[0][0]
    audits = sql("SELECT table_name, action::text, user_id::text, xmin::text FROM audit_logs WHERE record_id IN (:a, :t) "
                 "AND action = 'insert' AND table_name = 'ticket_assignments' OR (record_id = :t AND action = 'update')", a=a_id, t=tid)
    assert sorted((r[0], r[1], r[2]) for r in audits) == [("maintenance_tickets", "update", eng_id),
                                                         ("ticket_assignments", "insert", eng_id)]
    assert {r[3] for r in audits} == {a_xmin} == {t_xmin}


# ---- status rules ---------------------------------------------------------------------------------
def test_who_may_change_status(client, tickets):
    h = tickets["h"]
    h["tech_b"] = tickets["add_user"]("tech-h1-b", "technician", "h1")
    tid = _assigned_ticket(tickets, client)
    _err(_status(client, h["tech_b"], tid, "in_progress"), 403, "forbidden")      # not assigned to them (Q5)
    _err(_status(client, h["dept_icu"], tid, "in_progress"), 403, "forbidden")    # the reporter
    for outsider in ("eng_h2", "tech_h2", "dept_none"):
        _err(_status(client, h[outsider], tid, "in_progress"), 404)              # cannot even see it
    assert _status(client, h["eng_h1"], tid, "in_progress").status_code == 200    # engineer of the hospital
    assert _status(client, h["admin"], tid, "waiting_for_parts").status_code == 200
    # an engineer reporting in ANOTHER hospital sees the ticket (own report) but cannot run it
    eng_report = tickets["report"](h["admin"], "h2").json()["id"]
    tickets["sql"]("UPDATE maintenance_tickets SET reported_by = :u WHERE id = :t", u=_me(client, h["eng_h1"]), t=eng_report)
    assert client.get(f"{API}/tickets/{eng_report}", headers=h["eng_h1"]).status_code == 200
    assert _assign(client, h["eng_h2"], eng_report, _me(client, h["tech_h2"])).status_code == 201
    _err(_status(client, h["eng_h1"], eng_report, "in_progress"), 403)  # not their hospital
    _err(_status(client, h["eng_h1"], eng_report, "cancelled"), 403)    # reporter, but no longer open (Q4)


def test_invalid_transitions_are_409_with_the_allowed_targets(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    for target in ("in_progress", "assigned", "open", "resolved", "closed", "waiting_for_parts"):
        r = _status(client, h["eng_h1"], tid, target)
        _err(r, 409, "invalid_status_transition")
        assert r.json()["error"]["details"] == [{"from": "open", "to": target, "allowed": ["cancelled"]}]
    assert _status(client, h["eng_h1"], tid, "cancelled").status_code == 200
    for target in ("open", "in_progress", "resolved", "closed", "cancelled"):
        r = _status(client, h["admin"], tid, target)
        _err(r, 409, "invalid_status_transition")
        assert r.json()["error"]["details"][0]["allowed"] == []                  # cancelled is final
    for body in ({"status": "fixed"}, {}, {"status": "closed", "note": "x"}):
        assert client.patch(f"{API}/tickets/{tid}/status", headers=h["admin"], json=body).status_code == 422


def test_reporter_may_cancel_only_while_open_and_unassigned(client, tickets):
    """Approved decision Q4."""
    h, w, sql = tickets["h"], tickets["world"], tickets["sql"]
    own = tickets["report"](h["dept_icu"], "icu").json()["id"]
    r = _status(client, h["dept_icu"], own, "cancelled")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assigned = _assigned_ticket(tickets, client)
    _err(_status(client, h["dept_icu"], assigned, "cancelled"), 403)
    legacy = tickets["report"](h["dept_icu"], "icu").json()["id"]   # open, but with an active assignment
    sql("INSERT INTO ticket_assignments (ticket_id, user_id) VALUES (:t, :u)", t=legacy, u=w["tech_id"])
    _err(_status(client, h["dept_icu"], legacy, "cancelled"), 403)
    others = tickets["report"](h["tech_h1"], "icu").json()["id"]
    _err(_status(client, h["dept_icu"], others, "cancelled"), 404)                # not theirs: not even visible
    assert _status(client, h["tech_h1"], others, "cancelled").status_code == 200  # staff reporter, same rule


def test_close_and_reopen_rules(client, tickets):
    """Approved decision Q6, plus: reopening needs an active assignee."""
    h, sql = tickets["h"], tickets["sql"]
    tid = _assigned_ticket(tickets, client)
    tickets["record"](tid)
    assert _status(client, h["tech_h1"], tid, "in_progress").status_code == 200
    assert _status(client, h["tech_h1"], tid, "resolved").status_code == 200
    _err(_status(client, h["tech_h1"], tid, "closed"), 403)       # even the assignee
    _err(_status(client, h["tech_h1"], tid, "in_progress"), 403)  # reopen
    r = _status(client, h["eng_h1"], tid, "in_progress")
    assert r.status_code == 200 and r.json()["resolved_at"] is None
    assert _status(client, h["tech_h1"], tid, "resolved").status_code == 200   # the record still counts
    sql("UPDATE ticket_assignments SET unassigned_at = now() WHERE ticket_id = :t", t=tid)
    _err(_status(client, h["eng_h1"], tid, "in_progress"), 409, "conflict", "Assign someone before reopening the ticket.")
    assert _status(client, h["admin"], tid, "closed").status_code == 200
    _err(_status(client, h["admin"], tid, "in_progress"), 409, "invalid_status_transition")  # closed is terminal


def test_a_record_of_another_ticket_does_not_satisfy_resolution(client, tickets):
    h = tickets["h"]
    a, b = _assigned_ticket(tickets, client), _assigned_ticket(tickets, client)
    tickets["record"](a)
    assert _status(client, h["tech_h1"], b, "in_progress").status_code == 200
    _err(_status(client, h["tech_h1"], b, "resolved"), 409, "maintenance_record_required")


# ---- assignments ----------------------------------------------------------------------------------
def test_assignment_rules_and_eligibility(client, tickets):
    h, w, sql = tickets["h"], tickets["world"], tickets["sql"]
    h["tech_b"] = tickets["add_user"]("tech-h1-c", "technician", "h1")
    tech_b = _me(client, h["tech_b"])
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    _err(_assign(client, h["tech_h1"], tid, tech_b), 403, message="Technicians can only assign themselves.")
    r = _assign(client, h["tech_h1"], tid, w["tech_id"])                       # Q5: self-assign
    assert r.status_code == 201 and r.json()["status"] == "assigned"
    _err(_assign(client, h["tech_h1"], tid, w["tech_id"]), 409, message="This user is already assigned to this ticket.")
    assert _assign(client, h["tech_b"], tid, tech_b).status_code == 201          # second taker while still `assigned`
    assert _status(client, h["tech_h1"], tid, "in_progress").status_code == 200
    h["tech_c"] = tickets["add_user"]("tech-h1-d", "technician", "h1")
    _err(_assign(client, h["tech_c"], tid, _me(client, h["tech_c"])), 403,
         message="Technicians can only take tickets that are open or assigned.")
    assert _assign(client, h["eng_h1"], tid, _me(client, h["tech_c"])).status_code == 201  # engineers may add helpers
    _err(_assign(client, h["dept_icu"], tid, w["tech_id"]), 403)
    _err(_assign(client, h["tech_h2"], tid, _me(client, h["tech_h2"])), 404)

    fresh = tickets["report"](h["dept_icu"], "icu").json()["id"]
    not_eligible = {
        "department user": _me(client, h["dept_icu"]), "admin": w["admin_id"], "other hospital": _me(client, h["tech_h2"]),
        "unknown": str(uuid.uuid4()),
    }
    for label, user_id in not_eligible.items():
        _err(_assign(client, h["eng_h1"], fresh, user_id), 400,
             message="Only active technicians and biomedical engineers of the ticket's hospital can be assigned.")
    sql("UPDATE users SET is_active = false WHERE id = :u", u=tech_b)
    _err(_assign(client, h["eng_h1"], fresh, tech_b), 400)
    assert client.post(f"{API}/tickets/{fresh}/assignments", headers=h["eng_h1"], json={"user_id": "x"}).status_code == 422
    assert tickets["sql"]("SELECT status::text FROM maintenance_tickets WHERE id = :t", t=fresh)[0][0] == "open"


def test_no_assignment_changes_on_finished_tickets_or_in_inactive_hospitals(client, tickets):
    h, w = tickets["h"], tickets["world"]
    tid = _assigned_ticket(tickets, client)
    tickets["record"](tid)
    assert _status(client, h["tech_h1"], tid, "in_progress").status_code == 200
    assert _status(client, h["tech_h1"], tid, "resolved").status_code == 200
    _err(_assign(client, h["eng_h1"], tid, _me(client, h["eng_h1"])), 409,
         message="Resolved, closed or cancelled tickets cannot be assigned.")
    _err(_unassign(client, h["eng_h1"], tid, w["tech_id"]), 409)
    h2_ticket = tickets["report"](h["eng_h2"], "h2").json()["id"]
    tech_h2 = _me(client, h["tech_h2"])
    assert client.patch(f"{API}/hospitals/{w['h2']}", headers=h["admin"], json={"is_active": False}).status_code == 200
    _err(_assign(client, h["admin"], h2_ticket, tech_h2), 400, message="Hospital is inactive; tickets cannot be assigned in it.")
    assert _status(client, h["admin"], h2_ticket, "cancelled").status_code == 200   # can still be closed out


def test_unassignment_rules(client, tickets):
    h, w, sql = tickets["h"], tickets["world"], tickets["sql"]
    eng_id = _me(client, h["eng_h1"])
    tid = _assigned_ticket(tickets, client)
    r = _unassign(client, h["eng_h1"], tid, w["tech_id"])
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["assignees"] == []
    assert [i["kind"] for i in r.json()["timeline"]][-2:] == ["assigned", "unassigned"]
    assert r.json()["timeline"][-1]["status"] == "open"
    rows = sql("SELECT unassigned_at IS NOT NULL FROM ticket_assignments WHERE ticket_id = :t", t=tid)
    assert rows == [(True,)]                                                       # history row kept
    _err(_unassign(client, h["eng_h1"], tid, w["tech_id"]), 404, message="This user is not assigned to this ticket.")

    assert _assign(client, h["tech_h1"], tid, w["tech_id"]).status_code == 201
    _err(_unassign(client, h["tech_h2"], tid, w["tech_id"]), 404)
    assert _assign(client, h["eng_h1"], tid, eng_id).status_code == 201
    _err(_unassign(client, h["tech_h1"], tid, eng_id), 403, message="Technicians can only unassign themselves.")
    assert _status(client, h["tech_h1"], tid, "in_progress").status_code == 200
    r = _unassign(client, h["tech_h1"], tid, w["tech_id"])                        # self, another assignee remains
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    _err(_unassign(client, h["eng_h1"], tid, eng_id), 409,
         message="A ticket that is in progress must keep at least one assignee.")


# ---- priority and soft delete ---------------------------------------------------------------------
def test_priority_changes(client, tickets):
    h, sql = tickets["h"], tickets["sql"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    count = lambda: sql("SELECT count(*) FROM audit_logs WHERE record_id = :t", t=tid)[0][0]  # noqa: E731
    r = client.patch(f"{API}/tickets/{tid}", headers=h["eng_h1"], json={"priority": "critical"})
    assert r.status_code == 200 and r.json()["priority"] == "critical"
    assert r.json()["timeline"][-1]["message"] == "Priority changed from Medium to Critical."
    before = count()
    assert client.patch(f"{API}/tickets/{tid}", headers=h["admin"], json={"priority": "critical"}).status_code == 200
    assert count() == before                                                        # no-op: no audit row
    for who in ("tech_h1", "dept_icu"):
        _err(client.patch(f"{API}/tickets/{tid}", headers=h[who], json={"priority": "low"}), 403)
    for body in ({}, {"priority": "urgent"}, {"priority": "low", "description": "edited"}, {"status": "closed"}):
        assert client.patch(f"{API}/tickets/{tid}", headers=h["eng_h1"], json=body).status_code == 422, body
    assert _status(client, h["eng_h1"], tid, "cancelled").status_code == 200
    _err(client.patch(f"{API}/tickets/{tid}", headers=h["eng_h1"], json={"priority": "low"}), 409,
         message="Closed or cancelled tickets cannot be changed.")


def test_soft_delete_is_admin_only_idempotent_and_freezes_the_ticket(client, tickets):
    """Decision 6: deleted_at is admin-only, for mistaken or duplicate tickets."""
    h, sql = tickets["h"], tickets["sql"]
    tid = _assigned_ticket(tickets, client)
    for who in ("eng_h1", "tech_h1", "dept_icu"):
        _err(client.delete(f"{API}/tickets/{tid}", headers=h[who]), 403)
    assert client.delete(f"{API}/tickets/{tid}", headers=h["admin"]).status_code == 204
    assert client.delete(f"{API}/tickets/{tid}", headers=h["admin"]).status_code == 204          # idempotent
    rows = sql("SELECT count(*) FROM audit_logs WHERE record_id = :t AND new_values->>'deleted_at' IS NOT NULL", t=tid)
    assert rows[0][0] == 1
    for who in ("eng_h1", "tech_h1", "dept_icu"):
        assert client.get(f"{API}/tickets/{tid}", headers=h[who]).status_code == 404
        _err(_status(client, h[who], tid, "in_progress"), 404)
    t = client.get(f"{API}/tickets/{tid}", headers=h["admin"]).json()
    assert t["is_deleted"] and t["status"] == "assigned" and t["timeline"][-1]["kind"] == "deleted"
    for r in (_status(client, h["admin"], tid, "cancelled"), _assign(client, h["admin"], tid, _me(client, h["eng_h1"])),
              client.patch(f"{API}/tickets/{tid}", headers=h["admin"], json={"priority": "low"})):
        _err(r, 409, message="Deleted tickets cannot be modified.")
    _err(client.delete(f"{API}/tickets/{uuid.uuid4()}", headers=h["admin"]), 404)


def test_tickets_of_an_archived_device_can_still_be_completed(client, tickets):
    h = tickets["h"]
    tid = _assigned_ticket(tickets, client)
    assert client.delete(f"{API}/devices/{tickets['d']['icu']['id']}", headers=h["admin"]).status_code == 200
    tickets["record"](tid)
    assert _status(client, h["tech_h1"], tid, "in_progress").status_code == 200
    assert _status(client, h["tech_h1"], tid, "resolved").status_code == 200
    _err(tickets["report"](h["dept_icu"], "icu"), 400)                    # but no new tickets


def test_workflow_endpoints_require_authentication_and_are_documented(client, tickets):
    tid = tickets["report"](tickets["h"]["tech_h1"], "icu").json()["id"]
    for method, url, body in (("patch", f"/tickets/{tid}/status", {"status": "cancelled"}),
                              ("post", f"/tickets/{tid}/assignments", {"user_id": str(uuid.uuid4())}),
                              ("delete", f"/tickets/{tid}/assignments/{uuid.uuid4()}", None),
                              ("patch", f"/tickets/{tid}", {"priority": "low"}), ("delete", f"/tickets/{tid}", None)):
        kwargs = {"json": body} if body else {}
        assert getattr(client, method)(f"{API}{url}", **kwargs).status_code == 401, url
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths[f"{API}/tickets/{{ticket_id}}"]) == {"get", "patch", "delete"}
    assert set(paths[f"{API}/tickets/{{ticket_id}}/status"]) == {"patch"}
    assert set(paths[f"{API}/tickets/{{ticket_id}}/assignments"]) == {"post"}
    assert set(paths[f"{API}/tickets/{{ticket_id}}/assignments/{{user_id}}"]) == {"delete"}


# ---- concurrency: the row lock ------------------------------------------------------------------------
def _race(client, tid, calls):
    """Holds the ticket's row lock in another transaction, starts the requests in parallel, checks
    they WAIT for that lock (proof the service locks the row), then releases it and returns the
    responses. Each request uses its own TestClient."""
    results = [None] * len(calls)
    with get_session_factory()() as holder:
        holder.execute(text("SELECT id FROM maintenance_tickets WHERE id = :t FOR UPDATE"), {"t": tid})

        def run(i, call):
            with TestClient(client.app) as c:
                results[i] = call(c)

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for t in threads:
            t.start()
        time.sleep(1.0)
        blocked = [t.is_alive() for t in threads]
        holder.rollback()  # release
    for t in threads:
        t.join(timeout=30)
    assert blocked == [True] * len(calls), "requests did not wait for the ticket's row lock"
    return results


def test_concurrent_self_assignments_of_one_user_one_wins(client, tickets):
    h, w = tickets["h"], tickets["world"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    results = _race(client, tid, [lambda c: _assign(c, h["tech_h1"], tid, w["tech_id"])] * 2)
    assert sorted(r.status_code for r in results) == [201, 409]
    rows = tickets["sql"]("SELECT count(*) FROM ticket_assignments WHERE ticket_id = :t", t=tid)
    status_changes = tickets["sql"]("SELECT count(*) FROM audit_logs WHERE record_id = :t AND new_values->>'status' = 'assigned'", t=tid)
    assert rows[0][0] == 1 and status_changes[0][0] == 1


def test_concurrent_takers_change_the_status_once(client, tickets):
    h = tickets["h"]
    h["tech_b"] = tickets["add_user"]("tech-h1-e", "technician", "h1")
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    me_a, me_b = tickets["world"]["tech_id"], _me(client, h["tech_b"])
    results = _race(client, tid, [lambda c: _assign(c, h["tech_h1"], tid, me_a), lambda c: _assign(c, h["tech_b"], tid, me_b)])
    assert [r.status_code for r in results] == [201, 201]
    status_changes = tickets["sql"]("SELECT count(*) FROM audit_logs WHERE record_id = :t AND new_values->>'status' = 'assigned'", t=tid)
    assert status_changes[0][0] == 1  # the second taker saw `assigned` and did not change it again


def test_concurrent_resolve_and_cancel_one_wins_cleanly(client, tickets):
    h = tickets["h"]
    tid = _assigned_ticket(tickets, client)
    tickets["record"](tid)
    assert _status(client, h["tech_h1"], tid, "in_progress").status_code == 200
    results = _race(client, tid, [lambda c: _status(c, h["tech_h1"], tid, "resolved"),
                                  lambda c: _status(c, h["eng_h1"], tid, "cancelled")])
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "invalid_status_transition"
    final = tickets["sql"]("SELECT status::text FROM maintenance_tickets WHERE id = :t", t=tid)[0][0]
    winner = next(r for r in results if r.status_code == 200).json()["status"]
    assert final == winner
