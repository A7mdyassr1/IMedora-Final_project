"""B6 CP4 - GET /devices/{id}/history against REAL PostgreSQL: the merged feed (order, equal times,
paging, filters) checked against independent SQL; per-role visibility of every entry type (D3, Q3,
Q9); ticket visibility identical to GET /devices/{id}/tickets (incl. deleted tickets); archived
devices readable; role-first 403 for department users asking for other entry types.
"""
import uuid

from sqlalchemy import event, text

from app.core.database import get_engine, get_session_factory

from tests.risk_scene import rq  # noqa: F401
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API

T1, T2, T3 = "2026-03-01T10:00:00+00:00", "2026-06-01T10:00:00+00:00", "2026-07-01T10:00:00+00:00"
ALL = ["ticket_reported", "ticket_resolved", "maintenance_record", "risk_assessment", "qa_record"]


def _err(r, status, code=None):
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text


def _history(client, headers, device_id, **params):
    return client.get(f"{API}/devices/{device_id}/history", headers=headers, params=params)


def _ids(body):
    """(type, id of the underlying row) per entry, in feed order."""
    out = []
    for e in body["items"]:
        detail = e["ticket"] or e["maintenance_record"] or e["risk_assessment"] or e["qa_record"]
        out.append((e["type"], detail["id"]))
    return out


def _sql_feed(rq, device_id, hospital_scoped=True, own_reports_of=None, types=ALL):
    """Independent expectation for staff (or a department user's own reports when own_reports_of)."""
    parts = []
    tickets_where = "device_id = :d AND deleted_at IS NULL" + (" AND reported_by = :u" if own_reports_of else "")
    if "ticket_reported" in types:
        parts.append(f"SELECT 'ticket_reported' AS type, created_at AS at, id FROM maintenance_tickets WHERE {tickets_where}")
    if "ticket_resolved" in types:
        parts.append(f"SELECT 'ticket_resolved' AS type, resolved_at AS at, id FROM maintenance_tickets WHERE {tickets_where} AND resolved_at IS NOT NULL")
    if "maintenance_record" in types:
        parts.append("SELECT 'maintenance_record' AS type, performed_at AS at, id FROM maintenance_records WHERE device_id = :d")
    if "risk_assessment" in types:
        parts.append("SELECT 'risk_assessment' AS type, assessed_at AS at, id FROM risk_assessments WHERE device_id = :d")
    if "qa_record" in types:
        parts.append("SELECT 'qa_record' AS type, performed_at AS at, id FROM qa_records WHERE device_id = :d")
    rows = rq["sql"]("SELECT type, id::text FROM (" + " UNION ALL ".join(parts) + ") f ORDER BY at DESC, type, id",
                     d=device_id, u=own_reports_of)
    return [tuple(r) for r in rows]


def _build(client, rq):
    """On the ICU device: a ticket reported by the department user and fully resolved through the API
    (assignment, work record, resolution), a ticket reported by the technician, two risk assessments,
    and QA records, two of them at the same time as one assessment."""
    h, w, d = rq["h"], rq["world"], rq["d"]
    corrective = rq["mtype"]("corrective")
    own = rq["report"](h["dept_icu"], "icu").json()["id"]
    assert client.post(f"{API}/tickets/{own}/assignments", headers=h["eng_h1"], json={"user_id": w["tech_id"]}).status_code == 201
    assert client.patch(f"{API}/tickets/{own}/status", headers=h["tech_h1"], json={"status": "in_progress"}).status_code == 200
    record = client.post(f"{API}/maintenance-records", headers=h["tech_h1"],
                         json={"device_id": d["icu"]["id"], "maintenance_type_id": corrective,
                               "description": "Replaced the fan", "ticket_id": own}).json()["id"]
    assert client.patch(f"{API}/tickets/{own}/status", headers=h["tech_h1"], json={"status": "resolved"}).status_code == 200
    other = rq["report"](h["tech_h1"], "icu").json()["id"]
    risk1 = rq["assess"](h["eng_h1"], "icu", "high", assessed_at=T1).json()["id"]
    risk2 = rq["assess"](h["eng_h1"], "icu", "medium", assessed_at=T3).json()["id"]
    qa1 = rq["qa"](h["eng_h1"], "icu", "calibration", status="pass", performed_at=T2, next_due_date="2027-06-01").json()["id"]
    qa_same_a = rq["qa"](h["eng_h1"], "icu", "inspection", performed_at=T3).json()["id"]
    qa_same_b = rq["qa"](h["eng_h1"], "icu", "compliance", performed_at=T3).json()["id"]
    return dict(own=own, other=other, record=record, risk1=risk1, risk2=risk2, qa1=qa1, qa_same=(qa_same_a, qa_same_b))


# ---- the feed for staff ------------------------------------------------------------------------------
def test_staff_see_every_entry_type_in_order(client, rq):
    h, d = rq["h"], rq["d"]
    x = _build(client, rq)
    dev = d["icu"]["id"]
    for who in ("admin", "eng_h1", "tech_h1"):
        body = _history(client, h[who], dev).json()
        assert _ids(body) == _sql_feed(rq, dev), who
        assert body["total"] == 9 and {e["type"] for e in body["items"]} == set(ALL)
    body = _history(client, h["tech_h1"], dev).json()
    entries = {(e["type"], (e["ticket"] or e["maintenance_record"] or e["risk_assessment"] or e["qa_record"])["id"]): e
               for e in body["items"]}
    reported = entries[("ticket_reported", x["own"])]["ticket"]
    assert reported["number"].startswith("TKT-") and reported["status"] == "resolved"
    assert reported["reported_by"]["name"] == rq["world"]["staff"].split("@")[0]       # staff see names
    assert entries[("ticket_resolved", x["own"])]["ticket"]["reported_by"] is None
    rec = entries[("maintenance_record", x["record"])]["maintenance_record"]
    assert rec["ticket_id"] == x["own"] and rec["ticket_number"] == reported["number"] and rec["parts_count"] == 0
    assert rec["performed_by"]["id"] == rq["world"]["tech_id"] and rec["maintenance_type"].startswith("corrective-")
    assert entries[("risk_assessment", x["risk1"])]["risk_assessment"]["risk_level"] == "high"
    q = entries[("qa_record", x["qa1"])]["qa_record"]
    assert (q["record_type"], q["status"], q["next_due_date"]) == ("calibration", "pass", "2027-06-01")
    # equal times (T3): qa_record before risk_assessment (type), the two QA records by id
    t3 = [(e["type"], (e["qa_record"] or e["risk_assessment"])["id"]) for e in body["items"]
          if e["type"] in ("qa_record", "risk_assessment") and e["at"].startswith("2026-07-01")]
    assert t3 == [("qa_record", i) for i in sorted(x["qa_same"])] + [("risk_assessment", x["risk2"])]


def test_filters_and_paging(client, rq):
    h, d = rq["h"], rq["d"]
    x = _build(client, rq)
    dev = d["icu"]["id"]
    body = _history(client, h["eng_h1"], dev, types="risk_assessment,qa_record").json()
    assert _ids(body) == _sql_feed(rq, dev, types=["risk_assessment", "qa_record"]) and body["total"] == 5
    assert _ids(_history(client, h["eng_h1"], dev, types=" ticket_resolved ").json()) == [("ticket_resolved", x["own"])]
    window = _history(client, h["eng_h1"], dev, **{"from": T2, "to": T3}).json()   # both ends inclusive
    assert {i for _, i in _ids(window)} == {x["qa1"], x["risk2"], *x["qa_same"]}
    full = _ids(_history(client, h["eng_h1"], dev, page_size=100).json())
    pages = [_ids(_history(client, h["eng_h1"], dev, page=p, page_size=4).json()) for p in (1, 2, 3)]
    assert pages[0] + pages[1] + pages[2] == full and [len(p) for p in pages] == [4, 4, 1]
    for bad in ("audit", "risk_assessment,unknown", "", ","):
        _err(_history(client, h["eng_h1"], dev, types=bad), 422, "validation_error")


# ---- visibility per role --------------------------------------------------------------------------------
def test_department_users_see_only_their_own_tickets(client, rq):
    h, d, w = rq["h"], rq["d"], rq["world"]
    x = _build(client, rq)
    dev = d["icu"]["id"]
    r = _history(client, h["dept_icu"], dev)
    assert r.status_code == 200
    assert _ids(r.json()) == [("ticket_resolved", x["own"]), ("ticket_reported", x["own"])] == \
        _sql_feed(rq, dev, own_reports_of=client.get(f"{API}/auth/me", headers=h["dept_icu"]).json()["id"],
                  types=["ticket_reported", "ticket_resolved"])
    reporter = r.json()["items"][1]["ticket"]["reported_by"]
    assert reporter["name"] == w["staff"].split("@")[0]               # themself: their own name
    for staff in (w["tech"], w["admin"]):                              # never a staff name (Q9)
        assert staff.split("@")[0] not in r.text
    # role first: asking for an entry type they may not see -> 403, even on another department's
    # device or an unknown device (no lookup happens)
    for forbidden in ("risk_assessment", "qa_record", "maintenance_record", "ticket_reported,risk_assessment"):
        for device in (dev, d["lab"]["id"], str(uuid.uuid4())):
            _err(_history(client, h["dept_icu"], device, types=forbidden), 403, "forbidden")
    assert _history(client, h["dept_icu"], dev, types="ticket_reported").json()["total"] == 1
    # other departments' devices (even scanned by QR) and other hospitals: not found
    for device in (d["lab"]["id"], d["h2"]["id"], str(uuid.uuid4())):
        _err(_history(client, h["dept_icu"], device), 404)
    _err(_history(client, h["dept_none"], dev), 403, "department_required")


def test_ticket_entries_match_the_device_ticket_endpoint(client, rq):
    h, d = rq["h"], rq["d"]
    x = _build(client, rq)
    dev = d["icu"]["id"]
    deleted = rq["report"](h["eng_h1"], "icu").json()["id"]
    assert client.delete(f"{API}/tickets/{deleted}", headers=h["admin"]).status_code in (200, 204)
    expected = {"admin": {x["own"], x["other"]}, "eng_h1": {x["own"], x["other"]},
                "tech_h1": {x["own"], x["other"]}, "dept_icu": {x["own"]}}
    for who, ids in expected.items():
        listed = {t["id"] for t in client.get(f"{API}/devices/{dev}/tickets", headers=h[who],
                                              params={"page_size": 100}).json()["items"]}
        in_history = {i for kind, i in _ids(_history(client, h[who], dev, types="ticket_reported", page_size=100).json())}
        assert in_history == listed == ids, who
        assert deleted not in in_history, who


def test_scope_and_archived_devices(client, rq):
    h, d, w = rq["h"], rq["d"], rq["world"]
    rq["assess"](h["admin"], "h2", "low")
    _err(_history(client, h["tech_h1"], d["h2"]["id"]), 404)
    _err(_history(client, h["eng_h1"], d["h2"]["id"]), 404)
    assert _history(client, h["tech_h2"], d["h2"]["id"]).json()["total"] == 1
    assert _history(client, h["admin"], d["h2"]["id"]).json()["total"] == 1
    # an archived device keeps a readable history
    rq["sql"]("INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level, assessed_at) "
              "SELECT organization_id, hospital_id, id, :u, 'high', :t FROM devices WHERE id = :d",
              u=w["admin_id"], t=T1, d=d["archived"]["id"])
    for who in ("admin", "eng_h1", "tech_h1"):
        body = _history(client, h[who], d["archived"]["id"]).json()
        assert [e["type"] for e in body["items"]] == ["risk_assessment"], who
    _err(_history(client, h["admin"], str(uuid.uuid4())), 404)
    assert set(client.get("/openapi.json").json()["paths"][f"{API}/devices/{{device_id}}/history"]) == {"get"}


def test_total_and_page_come_from_one_snapshot(client, rq):
    """B6-L3 regression. Another transaction saves a new entry AFTER the history's count query and
    BEFORE its page query. The response must still be one consistent picture: the total, the page and
    the entry details from the same snapshot (the new entry is simply not there yet). With two
    independent queries the total said 2 while the page showed 3 entries."""
    h, dev = rq["h"], rq["d"]["icu"]["id"]
    saved = [rq["assess"](h["eng_h1"], "icu", level, assessed_at=at).json()["id"]
             for level, at in (("low", T1), ("high", T2))]
    fired = []

    def save_between_count_and_page(conn, cursor, statement, parameters, context, executemany):
        if fired or "count(*)" not in statement or "risk_assessments" not in statement:
            return
        fired.append(True)
        with get_session_factory()() as other:      # a concurrent writer, committed at once
            other.execute(text(
                "INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level, assessed_at) "
                "SELECT organization_id, hospital_id, device_id, assessed_by, 'medium', :t FROM risk_assessments WHERE id = :s"),
                {"t": T3, "s": saved[0]})
            other.commit()

    event.listen(get_engine(), "after_cursor_execute", save_between_count_and_page)
    try:
        body = _history(client, h["eng_h1"], dev, types="risk_assessment", page_size=50).json()
    finally:
        event.remove(get_engine(), "after_cursor_execute", save_between_count_and_page)
    assert fired == [True]
    assert body["total"] == len(body["items"]) == 2, body
    with get_session_factory()() as s:   # the pooled connection is back on the default isolation level
        assert s.scalar(text("SHOW transaction_isolation")) == "read committed"
    assert _ids(body) == [("risk_assessment", saved[1]), ("risk_assessment", saved[0])]

    after = _history(client, h["eng_h1"], dev, types="risk_assessment", page_size=50).json()   # the next read sees it
    assert after["total"] == len(after["items"]) == 3
    assert [e["at"][:10] for e in after["items"]] == ["2026-07-01", "2026-06-01", "2026-03-01"]
    # the response shape is unchanged
    assert set(body) == {"items", "total", "page", "page_size"} and (body["page"], body["page_size"]) == (1, 50)


def test_reporters_look_exactly_as_in_ticket_responses(client, rq):
    """B6-L4 compatibility: device history and ticket responses share ONE person rule (Q9) from
    app/schemas/person.py. For every role, each history `reported_by` is identical, field for field, to
    the same ticket's `reported_by` in GET /tickets/{id}: a department user sees themself by name and
    other staff as roles with no id; staff see names and ids."""
    h, d = rq["h"], rq["d"]
    x = _build(client, rq)
    dev = d["icu"]["id"]
    seen = {}
    for who in ("admin", "eng_h1", "tech_h1", "dept_icu"):
        items = _history(client, h[who], dev, types="ticket_reported", page_size=100).json()["items"]
        assert items, who
        for e in items:
            ticket = client.get(f"{API}/tickets/{e['ticket']['id']}", headers=h[who]).json()
            assert e["ticket"]["reported_by"] == ticket["reported_by"], who
            assert set(e["ticket"]["reported_by"]) == {"id", "name", "role"}
            seen[(who, e["ticket"]["id"])] = e["ticket"]["reported_by"]
    # the technician's report, as the department user may not see it (not theirs) vs as staff see it
    staff_view = seen[("eng_h1", x["other"])]
    assert staff_view["id"] is not None and staff_view["role"] == "technician"
    own_view = seen[("dept_icu", x["own"])]
    assert own_view["id"] is not None                      # themself: id and name
    # an assignee seen by the department user on their own ticket: a role, no id (same builder)
    assignees = client.get(f"{API}/tickets/{x['own']}", headers=h["dept_icu"]).json()["assignees"]
    assert [(a["id"], a["name"], a["role"]) for a in assignees] == [(None, "Technician", "technician")]


def test_person_model_is_the_same_class_everywhere():
    """B6-L4: the ticket schemas re-export the shared model; OpenAPI keeps one `PersonRef` component."""
    from app.schemas import history, person, ticket
    assert ticket.PersonRef is person.PersonRef is history.PersonRef
    assert issubclass(ticket.TicketAssignee, person.PersonRef)
    assert not hasattr(ticket, "_person")
