"""B10 - dashboard & analytics endpoints against REAL PostgreSQL (tests/analytics_scene.py).

Every expected number comes from tests/analytics_oracle.py: the AI package's metric rules applied in
plain Python to the scene's dataset, independent of the SQL under test. Each endpoint is also checked
per role (scope), for the narrowing filters, archived devices, validation and query count (no N+1).

Skipped unless TEST_DATABASE_URL is set.
"""
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from app.core.database import get_engine
from tests.analytics_oracle import Oracle
from tests.analytics_scene import ana  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.world import API, auth

A = f"{API}/analytics"
BOTH = {"h1", "h2"}


def _err(r, status, code):
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code, r.text


def _oracle(ana, hospitals=BOTH, **kw):
    return Oracle(ana["db_tz"], ana["today"], hospitals, **kw)


@contextmanager
def count_queries():
    """Number of SQL statements the app runs inside the block."""
    seen = []

    def before(conn, cursor, statement, *args):
        seen.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _category_names(ana):
    sfx = ana["sfx"]
    return {"a": f"Ventilator-{sfx}", "b": f"Monitor-{sfx}"}


# ---- access (every B10 endpoint) ---------------------------------------------------------------------
ENDPOINTS = ["/overview", "/devices", "/maintenance", "/tickets", "/problem-devices", "/trends"]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_staff_only_and_archived_for_admins_only(client, ana, path):
    h = ana["h"]
    assert client.get(f"{A}{path}").status_code == 401
    _err(client.get(f"{A}{path}", headers=h["staff"]), 403, "forbidden")                 # department user
    _err(client.get(f"{A}{path}?include_archived=true", headers=h["tech_h1"]), 403, "forbidden")
    _err(client.get(f"{A}{path}?include_archived=true", headers=h["eng_h2"]), 403, "forbidden")
    for who in ("admin", "tech_h1", "eng_h2"):
        assert client.get(f"{A}{path}", headers=h[who]).status_code == 200, who
    assert client.get(f"{A}{path}?include_archived=true", headers=h["admin"]).status_code == 200
    _err(client.get(f"{A}{path}?hospital_id=not-a-uuid", headers=h["admin"]), 422, "validation_error")


# ---- CP1 devices ---------------------------------------------------------------------------------------
def _named(rows):
    return [[r["name"], r["count"]] for r in rows]


def _check_devices(body, expected):
    for key in ("total", "by_status", "by_risk_level", "by_criticality"):
        assert body[key] == expected[key], key
    assert _named(body["by_department"]) == expected["by_department"]
    assert _named(body["by_category"]) == expected["by_category"]


@pytest.mark.parametrize("who, query, hospitals, kw", [
    ("admin", "", BOTH, {}),
    ("admin", "?include_archived=true", BOTH, {"include_archived": True}),
    ("admin", "?hospital_id={h2}", {"h2"}, {}),
    ("admin", "?department_id={lab}", BOTH, {"department": "lab"}),
    ("tech_h1", "", {"h1"}, {}),
    ("tech_h1", "?hospital_id={h2}", set(), {}),             # outside the scope: zeros, never data
    ("tech_h1", "?department_id={rad}", set(), {}),
    ("eng_h2", "", {"h2"}, {}),
])
def test_device_statistics(client, ana, who, query, hospitals, kw):
    q = query.format(h2=ana["hosp"]["h2"], lab=ana["dept"]["lab"], rad=ana["dept"]["rad"])
    r = client.get(f"{A}/devices{q}", headers=ana["h"][who])
    assert r.status_code == 200, r.text
    _check_devices(r.json(), _oracle(ana, hospitals, **kw).device_stats(_category_names(ana)))


def test_device_statistics_by_id_and_filters_echoed(client, ana):
    body = client.get(f"{A}/devices?department_id={ana['dept']['icu']}", headers=ana["h"]["admin"]).json()
    assert body["filters"] == {"hospital_id": None, "department_id": ana["dept"]["icu"], "include_archived": False}
    assert body["by_department"] == [{"id": ana["dept"]["icu"], "name": "ICU", "count": 2}]
    assert body["by_status"]["percentages"] == {"active": 50.0, "under_maintenance": 50.0, "out_of_service": 0.0,
                                                "decommissioned": 0.0}


def test_another_organization_sees_only_its_own(client, ana):
    stranger = auth(client, ana["world"]["admin"].replace("admin-", "stranger-"))
    body = client.get(f"{A}/devices", headers=stranger).json()
    assert body["total"] == 1 and body["by_risk_level"]["counts"]["high"] == 1          # X1 only
    assert [d["name"] for d in body["by_department"]] == ["Other Dept"]


def test_empty_scope_has_null_percentages(client, ana):
    body = client.get(f"{A}/devices?hospital_id={ana['world']['oh']}", headers=ana["h"]["admin"]).json()
    assert body["total"] == 0 and body["by_department"] == [] and body["by_category"] == []
    assert set(body["by_status"]["percentages"].values()) == {None}


def test_device_statistics_query_count_does_not_grow(client, ana):
    h = ana["h"]["admin"]
    client.get(f"{A}/devices", headers=h)                                               # warm-up
    with count_queries() as all_rows:
        client.get(f"{A}/devices", headers=h)
    with count_queries() as one_dept:
        client.get(f"{A}/devices?department_id={ana['dept']['lab']}", headers=h)
    assert len(all_rows) == len(one_dept) <= 6        # auth + 3 aggregates, whatever the number of devices


# ---- CP2 maintenance -----------------------------------------------------------------------------------
MARCH = "date_from=2025-03-01&date_to=2025-03-31"
PERIOD = ("2025-03-01", "2025-03-31")


def _type_names(ana):
    return {"preventive": "preventive", "corrective": "corrective", "other": f"inspection-{ana['sfx']}"}


@pytest.mark.parametrize("who, query, hospitals, kw", [
    ("admin", "", BOTH, {}),
    ("admin", "&include_archived=true", BOTH, {"include_archived": True}),
    ("admin", "&department_id={lab}", BOTH, {"department": "lab"}),
    ("tech_h1", "", {"h1"}, {}),
    ("tech_h1", "&hospital_id={h2}", set(), {}),
    ("eng_h2", "", {"h2"}, {}),
])
def test_maintenance_statistics(client, ana, who, query, hospitals, kw):
    q = query.format(h2=ana["hosp"]["h2"], lab=ana["dept"]["lab"])
    r = client.get(f"{A}/maintenance?{MARCH}{q}", headers=ana["h"][who])
    assert r.status_code == 200, r.text
    body, o = r.json(), _oracle(ana, hospitals, **kw)
    records = o.records(PERIOD)
    assert body["period"] == {"date_from": PERIOD[0], "date_to": PERIOD[1]}
    assert body["total"] == len(records)
    assert body["preventive"] == sum(1 for x in records.values() if x[1] == "preventive")
    assert body["corrective"] == sum(1 for x in records.values() if x[1] == "corrective")
    assert [[t["name"], t["count"]] for t in body["by_type"]] == o.by_type(PERIOD, _type_names(ana))
    expected, got = o.compliance(), body["preventive_compliance"]
    assert got["as_of"] == ana["today"].isoformat() and got["due_soon_days"] == 30
    assert (got["devices_evaluated"], got["counts"], got["compliance_rate_pct"]) == (
        expected["devices_evaluated"], expected["counts"], expected["compliance_rate_pct"])
    assert got["overdue_total"] == len(expected["overdue"])
    assert [(d["device_code"].split("-")[0], d["days_overdue"]) for d in got["overdue_devices"]] == expected["overdue"]


def test_maintenance_known_values_and_database_days(client, ana):
    """The admin view of March, worked out by hand: R8 (31 Mar 22:30 UTC) is 1 April in the database's time
    zone and R9 (28 Feb 22:30 UTC) is 1 March; the archived device's R7 is left out."""
    body = client.get(f"{A}/maintenance?{MARCH}", headers=ana["h"]["admin"]).json()
    assert (body["total"], body["preventive"], body["corrective"]) == (6, 1, 4)
    c = body["preventive_compliance"]
    assert c["counts"] == {"overdue": 2, "due_soon": 1, "on_track": 1, "no_schedule": 1, "unknown_due_date": 0}
    assert c["compliance_rate_pct"] == 50.0
    first = c["overdue_devices"][0]
    assert (first["device_code"], first["department"], first["hospital"], first["days_overdue"]) == (
        f"D1-{ana['sfx']}", "ICU", "Hospital One", 5)
    assert first["next_due_date"] == (ana["today"] - __import__("datetime").timedelta(days=5)).isoformat()


def test_maintenance_parameters(client, ana):
    h = ana["h"]["admin"]
    c = client.get(f"{A}/maintenance?{MARCH}&due_soon_days=5&limit=1", headers=h).json()["preventive_compliance"]
    assert c["counts"]["due_soon"] == 0 and c["counts"]["on_track"] == 2        # D2 (10 days) is now on track
    assert c["overdue_total"] == 2 and len(c["overdue_devices"]) == 1
    for bad in ("due_soon_days=-1", "due_soon_days=366", "limit=0", "limit=101", "date_from=2025-04-01&date_to=2025-03-01",
                "date_from=yesterday"):
        _err(client.get(f"{A}/maintenance?{bad}", headers=h), 422, "validation_error")
    r = client.get(f"{A}/maintenance?date_from=2025-04-01&date_to=2025-03-01", headers=h)
    assert r.json()["error"]["details"] == [{"field": "query.date_from", "message": "date_from must not be after date_to"}]


def test_default_period_is_the_last_30_days(client, ana):
    from datetime import timedelta
    today = ana["today"]
    for path in ("/maintenance", "/tickets", "/problem-devices"):
        body = client.get(f"{A}{path}", headers=ana["h"]["admin"]).json()
        assert body["period"] == {"date_from": (today - timedelta(days=29)).isoformat(), "date_to": today.isoformat()}
    body = client.get(f"{A}/tickets?date_to=2025-03-31", headers=ana["h"]["admin"]).json()
    assert body["period"]["date_from"] == "2025-03-02"


# ---- CP2 tickets -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("who, query, hospitals, kw", [
    ("admin", "", BOTH, {}),
    ("admin", "&include_archived=true", BOTH, {"include_archived": True}),
    ("admin", "&department_id={icu}", BOTH, {"department": "icu"}),
    ("tech_h1", "", {"h1"}, {}),
    ("eng_h2", "", {"h2"}, {}),
    ("eng_h2", "&hospital_id={h1}", set(), {}),
])
def test_ticket_statistics(client, ana, who, query, hospitals, kw):
    q = query.format(h1=ana["hosp"]["h1"], icu=ana["dept"]["icu"])
    r = client.get(f"{A}/tickets?{MARCH}{q}", headers=ana["h"][who])
    assert r.status_code == 200, r.text
    body, expected = r.json(), _oracle(ana, hospitals, **kw).ticket_stats(PERIOD)
    for key in ("created", "by_priority", "failures", "resolved", "open_now", "mttr"):
        assert body[key] == expected[key], key


def test_ticket_known_values_and_database_days(client, ana):
    """T6 (28 Feb 23:30 UTC) counts in March, T7 (31 Mar 22:30 UTC) does not; T8, reported in February,
    counts in March's MTTR (resolution date); T10 (admin-deleted) and T9 (archived device) never count."""
    body = client.get(f"{A}/tickets?{MARCH}", headers=ana["h"]["admin"]).json()
    assert body["created"]["total"] == 10 and body["failures"] == 9 and body["resolved"] == 5
    assert body["mttr"] == {"mttr_hours": 114.7, "median_hours": 12.0, "min_hours": 3.5, "max_hours": 504.0,
                            "sample_size": 5}
    assert body["open_now"]["counts"] == {"open": 3, "assigned": 1, "in_progress": 1, "waiting_for_parts": 1}
    assert [[d["name"], d["count"]] for d in body["by_department"]] == [["ICU", 4], ["Lab", 4], ["Radiology", 2]]
    empty = client.get(f"{A}/tickets?date_from=2024-01-01&date_to=2024-01-31", headers=ana["h"]["admin"]).json()
    assert empty["mttr"] is None and empty["created"]["total"] == 0 and empty["open_now"]["total"] == 6


# ---- CP2 problem devices ------------------------------------------------------------------------------------
@pytest.mark.parametrize("who, query, hospitals, min_tickets", [
    ("admin", "", BOTH, 0),
    ("admin", "&min_tickets=2", BOTH, 2),
    ("tech_h1", "", {"h1"}, 0),
    ("eng_h2", "", {"h2"}, 0),
])
def test_problem_devices(client, ana, who, query, hospitals, min_tickets):
    r = client.get(f"{A}/problem-devices?{MARCH}{query}&limit=100", headers=ana["h"][who])
    assert r.status_code == 200, r.text
    body = r.json()
    rows, last = _oracle(ana, hospitals).problem_devices(PERIOD, min_tickets)
    got = [(d["device_code"].split("-")[0], d["ticket_count"], d["corrective_maintenance_count"]) for d in body["devices"]]
    assert got == rows and body["total_devices"] == len(rows) and body["min_tickets"] == min_tickets
    for d in body["devices"]:
        key = d["device_code"].split("-")[0]
        expected = last.get(key)
        assert (d["last_ticket_at"] is None) == (expected is None)
        if expected:
            assert __import__("datetime").datetime.fromisoformat(d["last_ticket_at"]) == expected


def test_problem_devices_ranking_and_limit(client, ana):
    body = client.get(f"{A}/problem-devices?{MARCH}&limit=3", headers=ana["h"]["admin"]).json()
    assert [(d["device_code"].split("-")[0], d["ticket_count"], d["corrective_maintenance_count"])
            for d in body["devices"]] == [("D1", 3, 2), ("D3", 2, 1), ("E1", 1, 1)]
    assert body["total_devices"] == 6 and body["ranked_by"].startswith("ticket_count")
    for bad in ("min_tickets=-1", "limit=0", "limit=101"):
        _err(client.get(f"{A}/problem-devices?{bad}", headers=ana["h"]["admin"]), 422, "validation_error")


@pytest.mark.parametrize("path", ["/maintenance", "/tickets", "/problem-devices"])
def test_cp2_query_count_does_not_grow(client, ana, path):
    h = ana["h"]["admin"]
    client.get(f"{A}{path}?{MARCH}", headers=h)
    with count_queries() as all_rows:
        client.get(f"{A}{path}?{MARCH}", headers=h)
    with count_queries() as one_dept:     # ICU has an overdue device too, so the same queries run
        client.get(f"{A}{path}?{MARCH}&department_id={ana['dept']['icu']}", headers=h)
    assert len(all_rows) == len(one_dept) <= 9


@pytest.mark.parametrize("d1, d2, expected", [
    (0, 30, {"overdue": 1, "due_soon": 2, "on_track": 1}),      # due today is due soon; today + 30 still is
    (-1, 31, {"overdue": 2, "due_soon": 0, "on_track": 2}),     # yesterday is overdue; today + 31 is on track
])
def test_preventive_compliance_day_boundaries(client, ana, d1, d2, expected):
    from datetime import timedelta
    from sqlalchemy import text
    from app.core.database import get_session_factory
    today = ana["today"]
    with get_session_factory()() as db:
        for code, offset in (("D1", d1), ("D2", d2)):
            db.execute(text("UPDATE maintenance_schedules SET next_due_date = :due WHERE device_id = :d "
                            "AND maintenance_type_id = :t"),
                       {"due": today + timedelta(days=offset), "d": ana["dev"][code], "t": ana["types"]["preventive"]})
        db.commit()
    c = client.get(f"{A}/maintenance?{MARCH}", headers=ana["h"]["admin"]).json()["preventive_compliance"]
    assert {k: c["counts"][k] for k in expected} == expected
    assert c["overdue_total"] == len(c["overdue_devices"]) == expected["overdue"]


# ---- CP3 inventory ---------------------------------------------------------------------------------------
HOSPITAL_NAMES = {"h1": "Hospital One", "h2": "Hospital Two", "oh": "Foreign Hospital"}


def test_inventory_access(client, ana):
    h = ana["h"]
    assert client.get(f"{A}/inventory").status_code == 401
    _err(client.get(f"{A}/inventory", headers=h["staff"]), 403, "forbidden")
    for bad in ("hospital_id=not-a-uuid", "limit=0", "limit=101"):
        _err(client.get(f"{A}/inventory?{bad}", headers=h["admin"]), 422, "validation_error")


@pytest.mark.parametrize("who, query, hospitals", [
    ("admin", "", BOTH),
    ("admin", "hospital_id={h1}", {"h1"}),
    ("admin", "hospital_id={oh}", set()),          # another organization's hospital: zeros, never its stock
    ("tech_h1", "", {"h1"}),
    ("tech_h1", "hospital_id={h2}", set()),
    ("eng_h2", "", {"h2"}),
])
def test_inventory_statistics(client, ana, who, query, hospitals):
    q = query.format(**ana["hosp"])
    r = client.get(f"{A}/inventory?{q}", headers=ana["h"][who])
    assert r.status_code == 200, r.text
    body, expected = r.json(), Oracle.inventory(hospitals)
    for key in ("items_tracked", "parts_tracked", "total_units_on_hand", "low_stock_count", "out_of_stock_count"):
        assert body[key] == expected[key], key
    numbers = {p: f"PN-{p}-{ana['sfx']}" for p in ("P1", "P2", "P3")}
    rev = {v: k for k, v in ana["hosp"].items()}
    got = [(numbers_key, rev[x["hospital_id"]], x["quantity_on_hand"], x["reorder_threshold"])
           for x in body["low_stock"] for numbers_key in [x["part_number"].split("-")[1]]]
    assert got == Oracle.low_stock(hospitals, numbers, HOSPITAL_NAMES)
    for x in body["low_stock"]:
        assert x["hospital"] == HOSPITAL_NAMES[rev[x["hospital_id"]]] and x["part_id"] == ana["part"][x["part_number"].split("-")[1]]


def test_inventory_known_values_and_limit(client, ana):
    body = client.get(f"{A}/inventory?limit=2", headers=ana["h"]["admin"]).json()
    assert (body["items_tracked"], body["parts_tracked"], body["total_units_on_hand"],
            body["low_stock_count"], body["out_of_stock_count"]) == (5, 3, 22, 3, 1)
    assert [(x["part_number"].split("-")[1], x["hospital"], x["quantity_on_hand"]) for x in body["low_stock"]] == [
        ("P2", "Hospital One", 0), ("P1", "Hospital One", 2)]


# ---- CP3 trends ------------------------------------------------------------------------------------------
METRICS = ["tickets", "corrective_maintenance", "preventive_maintenance", "total_maintenance", "mttr_hours"]


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize("interval, period", [
    ("day", ("2025-02-27", "2025-04-02")),
    ("week", ("2025-02-01", "2025-04-30")),
    ("month", ("2025-01-15", "2025-06-10")),
])
def test_trends_match_the_oracle(client, ana, metric, interval, period):
    r = client.get(f"{A}/trends?metric={metric}&interval={interval}&date_from={period[0]}&date_to={period[1]}",
                   headers=ana["h"]["admin"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["metric"], body["interval"]) == (metric, interval)
    assert body["period"] == {"date_from": period[0], "date_to": period[1]}
    assert [[p["start"], p["end"], p["value"], p["sample_size"]] for p in body["points"]] == \
        _oracle(ana).trend(metric, interval, period)


@pytest.mark.parametrize("who, query, hospitals, kw", [
    ("admin", "&include_archived=true", BOTH, {"include_archived": True}),
    ("admin", "&department_id={lab}", BOTH, {"department": "lab"}),
    ("tech_h1", "", {"h1"}, {}),
    ("eng_h2", "", {"h2"}, {}),
    ("eng_h2", "&hospital_id={h1}", set(), {}),
])
@pytest.mark.parametrize("metric", ["tickets", "total_maintenance", "mttr_hours"])
def test_trends_scope(client, ana, who, query, hospitals, kw, metric):
    q = query.format(h1=ana["hosp"]["h1"], lab=ana["dept"]["lab"])
    r = client.get(f"{A}/trends?metric={metric}&interval=week&{MARCH}{q}", headers=ana["h"][who])
    assert r.status_code == 200, r.text
    assert [[p["start"], p["end"], p["value"], p["sample_size"]] for p in r.json()["points"]] == \
        _oracle(ana, hospitals, **kw).trend(metric, "week", PERIOD)


def test_trend_known_values(client, ana):
    """March by ISO week: buckets are cut by the period (1-2 March, 31 March); T6 (28 Feb 23:30 UTC) is in
    the first bucket and T7 (31 Mar 22:30 UTC) in none."""
    body = client.get(f"{A}/trends?metric=tickets&interval=week&{MARCH}", headers=ana["h"]["admin"]).json()
    points = body["points"]
    assert [(p["start"], p["end"]) for p in points] == [
        ("2025-03-01", "2025-03-02"), ("2025-03-03", "2025-03-09"), ("2025-03-10", "2025-03-16"),
        ("2025-03-17", "2025-03-23"), ("2025-03-24", "2025-03-30"), ("2025-03-31", "2025-03-31")]
    assert sum(p["value"] for p in points) == 9          # = /tickets failures for March
    month = client.get(f"{A}/trends?metric=mttr_hours&interval=month&date_from=2025-03-01&date_to=2025-04-30",
                       headers=ana["h"]["admin"]).json()["points"]
    assert month[0] == {"start": "2025-03-01", "end": "2025-03-31", "value": 114.7, "sample_size": 5}


def test_trend_defaults_and_limits(client, ana):
    from datetime import timedelta
    h, today = ana["h"]["admin"], ana["today"]
    body = client.get(f"{A}/trends", headers=h).json()
    assert (body["metric"], body["interval"], len(body["points"])) == ("tickets", "day", 30)
    assert body["period"] == {"date_from": (today - timedelta(days=29)).isoformat(), "date_to": today.isoformat()}
    week = client.get(f"{A}/trends?interval=week&date_to=2025-03-31", headers=h).json()
    assert week["period"]["date_from"] == "2025-01-13" and len(week["points"]) == 12
    month = client.get(f"{A}/trends?interval=month&date_to=2025-03-31", headers=h).json()
    assert month["period"]["date_from"] == "2024-04-01" and len(month["points"]) == 12
    assert len(client.get(f"{A}/trends?date_from=2024-01-01&date_to=2024-12-31", headers=h).json()["points"]) == 366
    assert len(client.get(f"{A}/trends?interval=month&date_from=2024-01-01&date_to=2025-12-31",
                          headers=h).json()["points"]) == 24
    for bad, message in (("date_from=2024-01-01&date_to=2025-01-01", "a day trend covers at most 366 days"),
                         ("interval=week&date_from=2024-01-01&date_to=2026-01-01",
                          "a week trend covers at most 24 calendar months"),
                         ("interval=month&date_from=2024-01-31&date_to=2026-01-01",
                          "a month trend covers at most 24 calendar months"),
                         ("date_from=2025-03-02&date_to=2025-03-01", "date_from must not be after date_to")):
        r = client.get(f"{A}/trends?{bad}", headers=h)
        _err(r, 422, "validation_error")
        assert r.json()["error"]["details"] == [{"field": "query.date_from", "message": message}]
    for bad in ("metric=failures", "interval=year", "interval=Day"):
        _err(client.get(f"{A}/trends?{bad}", headers=h), 422, "validation_error")


@pytest.mark.parametrize("path", ["/inventory", "/trends?metric=mttr_hours&interval=day&" + MARCH,
                                  "/trends?metric=preventive_maintenance&interval=month&" + MARCH])
def test_cp3_query_count_is_fixed(client, ana, path):
    h = ana["h"]["admin"]
    client.get(f"{A}{path}", headers=h)
    with count_queries() as seen:
        r = client.get(f"{A}{path}", headers=h)
    assert r.status_code == 200 and len(seen) <= 5


# ---- CP4 overview ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("who, query, hospitals, kw", [
    ("admin", "", BOTH, {}),
    ("admin", "&include_archived=true", BOTH, {"include_archived": True}),
    ("admin", "&department_id={icu}", BOTH, {"department": "icu"}),
    ("admin", "&hospital_id={h2}", {"h2"}, {}),
    ("tech_h1", "", {"h1"}, {}),
    ("eng_h2", "", {"h2"}, {}),
    ("eng_h2", "&hospital_id={h1}", set(), {}),
])
def test_overview_matches_the_oracle(client, ana, who, query, hospitals, kw):
    from tests.analytics_oracle import LEVELS, OPEN_STATUSES
    q = query.format(h1=ana["hosp"]["h1"], h2=ana["hosp"]["h2"], icu=ana["dept"]["icu"])
    r = client.get(f"{A}/overview?{MARCH}{q}", headers=ana["h"][who])
    assert r.status_code == 200, r.text
    body, o = r.json(), _oracle(ana, hospitals, **kw)
    stats = o.device_stats(_category_names(ana))
    assert body["devices"] == {"total": stats["total"], "by_status": stats["by_status"],
                               "by_risk_level": stats["by_risk_level"]}
    open_tickets = [t for t in o.tickets().values() if t[2] in OPEN_STATUSES]
    assert body["open_tickets"] == {"by_status": o.dist([t[2] for t in open_tickets], OPEN_STATUSES),
                                    "by_priority": o.dist([t[3] for t in open_tickets], LEVELS)}
    assert body["schedules"] == {"as_of": ana["today"].isoformat(), "due_soon_days": 30, **o.schedules_due()}
    stock = Oracle.inventory(hospitals if "department" not in kw else BOTH)
    assert body["inventory"] == {k: stock[k] for k in ("items_tracked", "low_stock_count", "out_of_stock_count")}
    assert body["qa"] == o.dist(list(o.qa().elements()), ["pass", "fail", "pending"])
    stats_t, records = o.ticket_stats(PERIOD), o.records(PERIOD)
    assert body["activity"] == {
        "failures": stats_t["failures"], "tickets_resolved": stats_t["resolved"],
        "mttr_hours": stats_t["mttr"] and stats_t["mttr"]["mttr_hours"],
        "maintenance_performed": len(records),
        "preventive": sum(1 for x in records.values() if x[1] == "preventive"),
        "corrective": sum(1 for x in records.values() if x[1] == "corrective"),
        "preventive_compliance_rate_pct": o.compliance()["compliance_rate_pct"]}


def test_overview_agrees_with_the_detail_endpoints(client, ana):
    h = ana["h"]["tech_h1"]
    get = lambda path: client.get(f"{A}{path}", headers=h).json()  # noqa: E731
    o, devices, tickets = get(f"/overview?{MARCH}"), get("/devices"), get(f"/tickets?{MARCH}")
    maintenance, stock = get(f"/maintenance?{MARCH}"), get("/inventory")
    assert o["devices"]["by_status"] == devices["by_status"] and o["devices"]["by_risk_level"] == devices["by_risk_level"]
    assert o["open_tickets"]["by_status"] == tickets["open_now"]
    assert o["activity"]["failures"] == tickets["failures"] and o["activity"]["tickets_resolved"] == tickets["resolved"]
    assert o["activity"]["mttr_hours"] == tickets["mttr"]["mttr_hours"]
    assert (o["activity"]["maintenance_performed"], o["activity"]["preventive"], o["activity"]["corrective"]) == (
        maintenance["total"], maintenance["preventive"], maintenance["corrective"])
    assert o["activity"]["preventive_compliance_rate_pct"] == maintenance["preventive_compliance"]["compliance_rate_pct"]
    assert o["inventory"]["low_stock_count"] == stock["low_stock_count"]


def test_overview_known_values(client, ana):
    body = client.get(f"{A}/overview?{MARCH}&due_soon_days=5", headers=ana["h"]["admin"]).json()
    assert body["schedules"]["due_soon_days"] == 5
    assert (body["schedules"]["overdue"], body["schedules"]["due_soon"]) == (3, 0)   # D1, D3 (other type), E1
    assert body["qa"]["counts"] == {"pass": 1, "fail": 2, "pending": 1}
    assert body["activity"]["mttr_hours"] == 114.7 and body["activity"]["failures"] == 9
    for bad in ("due_soon_days=-1", "due_soon_days=366", "date_from=2025-04-01&date_to=2025-03-01"):
        _err(client.get(f"{A}/overview?{bad}", headers=ana["h"]["admin"]), 422, "validation_error")


def test_overview_query_count_is_fixed(client, ana):
    h = ana["h"]["admin"]
    client.get(f"{A}/overview?{MARCH}", headers=h)
    with count_queries() as all_rows:
        client.get(f"{A}/overview?{MARCH}", headers=h)
    with count_queries() as narrow:
        client.get(f"{A}/overview?{MARCH}&department_id={ana['dept']['icu']}", headers=h)
    assert len(all_rows) == len(narrow) <= 14


@pytest.mark.parametrize("path", ["/overview", "/maintenance", "/tickets", "/problem-devices", "/trends",
                                  "/trends?interval=month&x=1", "/trends?interval=week&x=1"])
@pytest.mark.parametrize("query, field", [("date_to=9999-12-31", "date_to"), ("date_from=0001-01-01", "date_from"),
                                          ("date_to=0001-01-01", "date_to"), ("date_from=3000-01-01", "date_from")])
def test_extreme_dates_are_a_422_not_a_500(client, ana, path, query, field):
    sep = "&" if "?" in path else "?"
    r = client.get(f"{A}{path}{sep}{query}", headers=ana["h"]["admin"])
    _err(r, 422, "validation_error")
    assert r.json()["error"]["details"] == [{"field": f"query.{field}",
                                             "message": f"{field} must be between 1900-01-01 and 2999-12-31"}]
    edge = client.get(f"{A}{path}{sep}date_from=1900-01-01&date_to=1900-01-31", headers=ana["h"]["admin"])
    assert edge.status_code == 200, edge.text
