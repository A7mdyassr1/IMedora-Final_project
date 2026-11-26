"""B6 CP1 - concurrency regression tests for finding F1 (approved plan section 10.2).

Without the device row lock, two concurrent risk writes can leave devices.current_risk_level
inconsistent with the latest assessment: each trigger run sees only committed rows plus its own,
and the later committer overwrites the cache with a stale result (reproduced on a throwaway copy
during planning). The service locks the device row before every risk write; the TRIGGER still does
all of the recalculation. These tests hold that lock in another transaction, start the writers in
parallel, check that they WAIT for it, release it, and check the final cache and the D17 audit rows.
"""
import threading
import time

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import get_session_factory
from tests.risk_scene import rq  # noqa: F401
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API

LOCK_DEVICE = "SELECT id FROM devices WHERE id = :d FOR UPDATE"


def _race(client, device_id, calls):
    """Hold the device row lock in another transaction, start the calls in parallel, check they WAIT."""
    results = [None] * len(calls)
    with get_session_factory()() as holder:
        holder.execute(text(LOCK_DEVICE), {"d": device_id})

        def run(i, call):
            with TestClient(client.app) as c:
                results[i] = call(c)

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for t in threads:
            t.start()
        time.sleep(1.0)
        blocked = [t.is_alive() for t in threads]
        holder.rollback()
    for t in threads:
        t.join(timeout=30)
    assert blocked == [True] * len(calls), "risk writes did not wait for the device row lock"
    return results


def _latest(rq, device_id):
    return rq["sql"]("SELECT risk_level::text FROM risk_assessments WHERE device_id = :d "
                     "ORDER BY assessed_at DESC LIMIT 1", d=device_id)[0][0]


def _level_rows(rq, device_id):
    return rq["sql"]("SELECT old_values->>'current_risk_level', new_values->>'current_risk_level' FROM audit_logs "
                     "WHERE record_id = :d AND new_values ? 'cause' ORDER BY created_at", d=device_id)


def _assert_chain(rq, device_id, start, end):
    """D17 rows of concurrent writers chain: each one's 'after' is the next one's 'before'."""
    rows = _level_rows(rq, device_id)
    values = [start]
    for old, new in rows:
        assert old == values[-1], rows
        values.append(new)
    assert values[-1] == end, rows


def test_concurrent_inserts_leave_the_cache_on_the_latest_assessment(client, rq):
    h, dev = rq["h"], rq["d"]["icu"]["id"]
    body = lambda level, at: {"device_id": dev, "risk_level": level, "assessed_at": at}  # noqa: E731
    results = _race(client, dev, [
        lambda c: c.post(f"{API}/risk-assessments", headers=h["eng_h1"], json=body("low", "2026-06-01T10:00:00+00:00")),
        lambda c: c.post(f"{API}/risk-assessments", headers=h["admin"], json=body("high", "2026-03-01T10:00:00+00:00")),
    ])
    assert [r.status_code for r in results] == [201, 201], [r.text for r in results]
    assert _latest(rq, dev) == "low" == rq["level"]("icu")
    _assert_chain(rq, dev, None, "low")


def test_concurrent_insert_and_correction_crossing_dates(client, rq):
    h, dev = rq["h"], rq["d"]["icu"]["id"]
    moved = rq["assess"](h["eng_h1"], "icu", "critical", assessed_at="2026-09-01T10:00:00+00:00").json()["id"]
    assert rq["level"]("icu") == "critical"
    results = _race(client, dev, [
        # the September assessment moves back to January...
        lambda c: c.patch(f"{API}/risk-assessments/{moved}", headers=h["admin"],
                          json={"assessed_at": "2026-01-01T10:00:00+00:00"}),
        # ...while a February assessment is added: February is now the latest, whatever the order
        lambda c: c.post(f"{API}/risk-assessments", headers=h["eng_h1"],
                         json={"device_id": dev, "risk_level": "low", "assessed_at": "2026-02-01T10:00:00+00:00"}),
    ])
    assert [r.status_code for r in results] == [200, 201], [r.text for r in results]
    assert _latest(rq, dev) == "low" == rq["level"]("icu")
    _assert_chain(rq, dev, None, "low")


def test_concurrent_assessments_at_the_same_time_one_wins(client, rq):
    h, dev = rq["h"], rq["d"]["icu"]["id"]
    at = "2026-05-05T10:00:00+00:00"
    results = _race(client, dev, [
        lambda c: c.post(f"{API}/risk-assessments", headers=h["eng_h1"], json={"device_id": dev, "risk_level": "low", "assessed_at": at}),
        lambda c: c.post(f"{API}/risk-assessments", headers=h["admin"], json={"device_id": dev, "risk_level": "high", "assessed_at": at}),
    ])
    assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "duplicate_assessment_time"
    winner = next(r for r in results if r.status_code == 201).json()["risk_level"]
    assert rq["sql"]("SELECT count(*) FROM risk_assessments WHERE device_id = :d", d=dev)[0][0] == 1
    assert rq["level"]("icu") == winner


def test_risk_and_maintenance_writes_on_one_device_do_not_deadlock(client, rq):
    h, dev = rq["h"], rq["d"]["icu"]["id"]
    preventive = rq["mtype"]("preventive")
    due = str(rq["sql"]("SELECT current_date + 30")[0][0])
    results = _race(client, dev, [
        lambda c: c.post(f"{API}/risk-assessments", headers=h["eng_h1"], json={"device_id": dev, "risk_level": "high"}),
        lambda c: c.post(f"{API}/maintenance-schedules", headers=h["eng_h1"],
                         json={"device_id": dev, "maintenance_type_id": preventive, "frequency_days": 30, "next_due_date": due}),
        lambda c: c.post(f"{API}/risk-assessments", headers=h["admin"],
                         json={"device_id": dev, "risk_level": "low", "assessed_at": "2026-01-01T10:00:00+00:00"}),
    ])
    assert [r.status_code for r in results] == [201, 201, 201], [r.text for r in results]
    assert rq["level"]("icu") == "high" == _latest(rq, dev)
    device = client.get(f"{API}/devices/{dev}", headers=h["admin"]).json()
    assert device["next_maintenance_due_date"] == due
