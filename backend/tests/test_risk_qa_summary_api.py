"""B6 CP3 - risk summary, QA summary and the QA due list against REAL PostgreSQL, checked against
independent SQL: scope isolation, `unassessed`, archived devices (admin-only include_archived), the
due-list selection (D15: latest record per device and record type, superseded records never due,
deterministic ties) and its date semantics and parameters (D18: within_days 0-365 default 30,
include_overdue default true). Department users get 403 everywhere.
"""
from datetime import timedelta

from tests.risk_scene import rq  # noqa: F401
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API

T1, T2 = "2026-03-01T10:00:00+00:00", "2026-06-01T10:00:00+00:00"


def _err(r, status, code=None):
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text


def _sql_levels(rq, hospital=None, archived=False):
    rows = rq["sql"]("SELECT coalesce(current_risk_level::text, 'unassessed'), count(*) FROM devices "
                     "WHERE organization_id = :o AND (CAST(:h AS uuid) IS NULL OR hospital_id = CAST(:h AS uuid)) "
                     "AND (:a OR deleted_at IS NULL) GROUP BY 1", o=rq["world"]["org"], h=hospital, a=archived)
    counts = {k: 0 for k in ("low", "medium", "high", "critical", "unassessed")}
    counts.update(dict(rows))
    return counts


def _insert_qa(rq, device_key, record_type, status, performed_at, next_due):
    """For archived devices only (the API refuses new records there, Decision 6)."""
    w, d = rq["world"], rq["d"]
    return rq["sql"]("INSERT INTO qa_records (organization_id, hospital_id, device_id, performed_by, record_type, status, "
                     "performed_at, next_due_date) SELECT organization_id, hospital_id, id, :u, CAST(:t AS qa_record_type), "
                     "CAST(:s AS qa_status), :p, :n FROM devices WHERE id = :d RETURNING id::text",
                     u=w["admin_id"], t=record_type, s=status, p=performed_at, n=next_due, d=d[device_key]["id"])[0][0]


# ---- risk summary -------------------------------------------------------------------------------------------
def test_risk_summary_counts_the_cached_levels(client, rq):
    h, w = rq["h"], rq["world"]
    get = lambda who, **q: client.get(f"{API}/risk-assessments/summary", headers=h[who], params=q)  # noqa: E731
    body = get("admin").json()
    assert body["by_level"] == _sql_levels(rq) and body["by_level"]["unassessed"] == body["total"] == 3
    rq["assess"](h["eng_h1"], "icu", "high", assessed_at=T2)
    rq["assess"](h["eng_h1"], "icu", "low", assessed_at=T1)       # backdated: icu stays high
    rq["assess"](h["eng_h1"], "lab", "low")
    rq["assess"](h["admin"], "h2", "critical")
    # an assessment of the archived device (written before it was archived, here directly)
    rq["sql"]("INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level) "
              "SELECT organization_id, hospital_id, id, :u, 'medium' FROM devices WHERE id = :d",
              u=w["admin_id"], d=rq["d"]["archived"]["id"])

    body = get("admin").json()
    assert body == {"total": 3, "by_level": {"low": 1, "medium": 0, "high": 1, "critical": 1, "unassessed": 0},
                    "hospital_id": None, "include_archived": False}
    assert body["by_level"] == _sql_levels(rq)
    with_archived = get("admin", include_archived="true").json()
    assert with_archived["by_level"] == _sql_levels(rq, archived=True) and with_archived["by_level"]["medium"] == 1
    assert get("admin", hospital_id=w["h1"]).json()["by_level"] == _sql_levels(rq, hospital=w["h1"])
    # own hospital only for engineers and technicians
    assert get("tech_h1").json()["by_level"] == _sql_levels(rq, hospital=w["h1"]) == \
        {"low": 1, "medium": 0, "high": 1, "critical": 0, "unassessed": 0}
    assert get("eng_h2").json()["by_level"] == {"low": 0, "medium": 0, "high": 0, "critical": 1, "unassessed": 0}
    assert get("tech_h1", hospital_id=w["h2"]).json()["total"] == 0      # a filter never widens the scope
    _err(get("eng_h1", include_archived="true"), 403, "forbidden")
    for who in ("dept_icu", "dept_none"):
        _err(get(who), 403, "forbidden")


# ---- QA summary ---------------------------------------------------------------------------------------------
def test_qa_summary_counts_by_status_and_type(client, rq):
    h, w = rq["h"], rq["world"]
    for device, record_type, status in (("icu", "calibration", "pass"), ("icu", "calibration", "pending"),
                                        ("lab", "inspection", "fail"), ("h2", "compliance", "pass")):
        assert rq["qa"](h["admin"], device, record_type, status=status, performed_at=T1).status_code == 201
    _insert_qa(rq, "archived", "inspection", "fail", T1, None)
    get = lambda who, **q: client.get(f"{API}/qa-records/summary", headers=h[who], params=q).json()  # noqa: E731

    def sql(hospital=None, archived=False):
        rows = rq["sql"]("SELECT q.status::text, q.record_type::text FROM qa_records q JOIN devices d ON d.id = q.device_id "
                         "WHERE q.organization_id = :o AND (CAST(:h AS uuid) IS NULL OR q.hospital_id = CAST(:h AS uuid)) "
                         "AND (:a OR d.deleted_at IS NULL)", o=w["org"], h=hospital, a=archived)
        by_status = {s: sum(1 for r in rows if r[0] == s) for s in ("pass", "fail", "pending")}
        by_type = {t: sum(1 for r in rows if r[1] == t) for t in ("inspection", "calibration", "compliance")}
        return {"total": len(rows), "by_status": by_status, "by_type": by_type}

    body = get("admin")
    assert {k: body[k] for k in ("total", "by_status", "by_type")} == sql() == \
        {"total": 4, "by_status": {"pass": 2, "fail": 1, "pending": 1}, "by_type": {"inspection": 1, "calibration": 2, "compliance": 1}}
    archived = get("admin", include_archived="true")
    assert {k: archived[k] for k in ("total", "by_status", "by_type")} == sql(archived=True) and archived["total"] == 5
    tech = get("tech_h1")
    assert {k: tech[k] for k in ("total", "by_status", "by_type")} == sql(hospital=w["h1"]) and tech["total"] == 3
    _err(client.get(f"{API}/qa-records/summary", headers=h["tech_h1"], params={"include_archived": "true"}), 403)
    for who in ("dept_icu", "dept_none"):
        _err(client.get(f"{API}/qa-records/summary", headers=h[who]), 403, "forbidden")


# ---- QA due list (D15, D18) -------------------------------------------------------------------------------------
def _scene_for_due(rq):
    h = rq["h"]
    today = rq["sql"]("SELECT current_date")[0][0]
    day = lambda n: str(today + timedelta(days=n))  # noqa: E731
    ids = {}

    def qa(key, device, record_type, performed_at, next_due, who="eng_h1", **extra):
        r = rq["qa"](h[who], device, record_type, performed_at=performed_at, next_due_date=next_due, **extra)
        assert r.status_code == 201, r.text
        ids[key] = r.json()["id"]

    qa("superseded", "icu", "calibration", T1, day(3))         # due in 3 days, but replaced by the next one
    qa("icu_cal", "icu", "calibration", T2, day(100))          # the latest calibration: due in 100 days
    qa("icu_insp", "icu", "inspection", T2, day(0), status="pass")   # due today
    qa("lab_cal", "lab", "calibration", T1, day(-1), status="fail")  # overdue since yesterday
    qa("lab_comp", "lab", "compliance", T2, day(30))           # exactly at the default window's edge
    qa("h2_insp", "h2", "inspection", T2, day(31), who="admin")  # one day beyond it
    qa("icu_comp", "icu", "compliance", T2, None)              # no next due date: never due
    # equal performed_at: the record created LAST is the latest (created_at, then id)
    qa("tie_first", "lab", "inspection", T2, day(5))
    qa("tie_last", "lab", "inspection", T2, day(200))
    ids["archived"] = _insert_qa(rq, "archived", "inspection", "pending", T2, day(1))
    return ids, today


def _sql_due(rq, within, overdue=True, hospital=None, archived=False):
    """Independent query (window function, not DISTINCT ON) for the expected ids, soonest first."""
    rows = rq["sql"](
        "SELECT id::text FROM (SELECT q.*, row_number() OVER (PARTITION BY q.device_id, q.record_type "
        "ORDER BY q.performed_at DESC, q.created_at DESC, q.id DESC) AS rn FROM qa_records q JOIN devices d ON d.id = q.device_id "
        "WHERE q.organization_id = :o AND (CAST(:h AS uuid) IS NULL OR q.hospital_id = CAST(:h AS uuid)) "
        "AND (:a OR d.deleted_at IS NULL)) x WHERE rn = 1 AND next_due_date IS NOT NULL "
        "AND next_due_date <= current_date + :w AND (:ov OR next_due_date >= current_date) ORDER BY next_due_date, id",
        o=rq["world"]["org"], h=hospital, a=archived, w=within, ov=overdue)
    return [r[0] for r in rows]


def test_due_list_selection_and_dates(client, rq):
    h, w = rq["h"], rq["world"]
    ids, today = _scene_for_due(rq)
    get = lambda who="admin", **q: client.get(f"{API}/qa-records/due", headers=h[who], params=q).json()  # noqa: E731
    ordered = lambda body: [i["id"] for i in body["items"]]  # noqa: E731

    body = get()  # defaults: within_days=30, include_overdue=true
    assert body["within_days"] == 30 and body["include_overdue"] is True and body["today"] == str(today)
    assert ordered(body) == [ids["lab_cal"], ids["icu_insp"], ids["lab_comp"]] == _sql_due(rq, 30)
    by_id = {i["id"]: i for i in body["items"]}
    assert (by_id[ids["lab_cal"]]["due_status"], by_id[ids["lab_cal"]]["days_until_due"]) == ("overdue", -1)
    assert (by_id[ids["icu_insp"]]["due_status"], by_id[ids["icu_insp"]]["days_until_due"]) == ("upcoming", 0)
    assert (by_id[ids["lab_comp"]]["due_status"], by_id[ids["lab_comp"]]["days_until_due"]) == ("upcoming", 30)
    assert by_id[ids["lab_cal"]]["status"] == "fail"          # the result is informational only

    # superseded records and records without a due date never appear, whatever the window
    wide = ordered(get(within_days=365))
    assert wide == _sql_due(rq, 365)
    for never in ("superseded", "tie_first", "icu_comp", "archived"):
        assert ids[never] not in wide, never
    assert ids["tie_last"] in wide and ids["icu_cal"] in wide

    assert ordered(get(within_days=31)) == _sql_due(rq, 31) and ids["h2_insp"] in ordered(get(within_days=31))
    assert ordered(get(include_overdue="false")) == [ids["icu_insp"], ids["lab_comp"]] == _sql_due(rq, 30, overdue=False)
    assert ordered(get(within_days=0)) == [ids["lab_cal"], ids["icu_insp"]] == _sql_due(rq, 0)
    assert ordered(get(record_type="calibration")) == [ids["lab_cal"]]
    assert ordered(get(device_id=rq["d"]["icu"]["id"], within_days=365)) == [ids["icu_insp"], ids["icu_cal"]]
    # scope: technicians see their own hospital; a filter never widens it
    assert ordered(get("tech_h1", within_days=31)) == _sql_due(rq, 31, hospital=w["h1"])
    assert ids["h2_insp"] not in ordered(get("tech_h1", within_days=31, hospital_id=w["h2"]))
    assert ordered(get("eng_h2", within_days=31)) == [ids["h2_insp"]]
    # archived devices: admins only, on request
    assert ids["archived"] in ordered(get(include_archived="true")) and \
        ordered(get(include_archived="true")) == _sql_due(rq, 30, archived=True)
    _err(client.get(f"{API}/qa-records/due", headers=h["tech_h1"], params={"include_archived": "true"}), 403)
    # paging
    page = get(within_days=365, page=2, page_size=2)
    assert page["total"] == len(wide) and ordered(page) == wide[2:4]


def test_due_list_parameters_and_access(client, rq):
    h = rq["h"]
    url = f"{API}/qa-records/due"
    for ok in ("0", "365"):
        assert client.get(url, headers=h["admin"], params={"within_days": ok}).status_code == 200
    for bad in ("-1", "366", "abc", "1.5"):
        _err(client.get(url, headers=h["admin"], params={"within_days": bad}), 422, "validation_error")
    _err(client.get(url, headers=h["admin"], params={"include_overdue": "maybe"}), 422)
    for who in ("dept_icu", "dept_none"):
        _err(client.get(url, headers=h[who]), 403, "forbidden")
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/qa-records/due", "/qa-records/summary", "/risk-assessments/summary"):
        assert set(paths[f"{API}{path}"]) == {"get"}
