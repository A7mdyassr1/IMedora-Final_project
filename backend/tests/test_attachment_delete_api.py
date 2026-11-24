"""B5 follow-up - deleting ticket photos (DELETE /attachments/{id}) against REAL PostgreSQL: who may
delete, visibility (404), finished tickets, the row + file + audit row, the freed slot in the limit
of 3, missing files, legacy rows, database and storage failures, forged storage keys, and concurrent
deletes. Skipped unless TEST_DATABASE_URL is set; rows are removed by tests/ticket_scene.py, files
live in the session's temporary STORAGE_DIR (tests/conftest.py).
"""
import logging
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.services.audit_service import AuditService
from app.storage.local import LocalDiskStorage
from tests.scope_scene import scene  # noqa: F401
from tests.test_attachments_api import _files, _upload, jpeg_with_gps, png
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API


def _err(r, status, code=None):
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text


def _file_of(tickets, attachment_id) -> Path:
    (url,), = tickets["sql"]("SELECT file_url FROM attachments WHERE id = :a", a=attachment_id)
    return Path(get_settings().storage_dir) / url.split(":", 1)[1]


def _rows(tickets, attachment_id) -> int:
    return tickets["sql"]("SELECT count(*) FROM attachments WHERE id = :a", a=attachment_id)[0][0]


def _delete(client, headers, attachment_id):
    return client.delete(f"{API}/attachments/{attachment_id}", headers=headers)


def _me(client, headers):
    return client.get(f"{API}/auth/me", headers=headers).json()["id"]


def test_the_uploader_deletes_their_photo_row_file_and_audit(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    a = _upload(client, h["dept_icu"], tid, jpeg_with_gps(), "pump.jpg").json()
    path = _file_of(tickets, a["id"])
    assert path.is_file()

    r = _delete(client, h["dept_icu"], a["id"])
    assert r.status_code == 204 and r.content == b""
    assert _rows(tickets, a["id"]) == 0 and not path.exists()
    _err(client.get(a["file_url"], headers=h["dept_icu"]), 404)
    assert client.get(f"{API}/tickets/{tid}", headers=h["dept_icu"]).json()["attachments"] == []
    assert client.get(f"{API}/tickets/{tid}/attachments", headers=h["dept_icu"]).json() == []
    _err(_delete(client, h["dept_icu"], a["id"]), 404)                      # already gone

    # audit: one delete row by the uploader, with the old values (internal key, ticket, name)
    rows = tickets["sql"]("SELECT a.action::text, a.old_values->>'ticket_id', a.old_values->>'file_name', "
                          "a.old_values->>'file_url' LIKE 'local:%', coalesce(a.new_values, 'null'::jsonb) = 'null'::jsonb, u.email "
                          "FROM audit_logs a JOIN users u ON u.id = a.user_id "
                          "WHERE a.table_name = 'attachments' AND a.record_id = :a ORDER BY a.created_at", a=a["id"])
    assert [r[0] for r in rows] == ["insert", "delete"]
    assert rows[1] == ("delete", tid, "pump.jpg", True, True, tickets["world"]["staff"])


def test_a_deleted_photo_frees_its_slot(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    ids = [_upload(client, h["dept_icu"], tid, png(), f"{i}.png", "image/png").json()["id"] for i in range(3)]
    _err(_upload(client, h["dept_icu"], tid, png(), "4.png", "image/png"), 409, "attachment_limit_reached")
    assert _delete(client, h["dept_icu"], ids[1]).status_code == 204
    replacement = _upload(client, h["dept_icu"], tid, jpeg_with_gps(), "replacement.jpg")
    assert replacement.status_code == 201, replacement.text
    listed = [x["id"] for x in client.get(f"{API}/tickets/{tid}/attachments", headers=h["dept_icu"]).json()]
    assert listed == [ids[0], ids[2], replacement.json()["id"]]
    _err(_upload(client, h["dept_icu"], tid, png(), "5.png", "image/png"), 409, "attachment_limit_reached")


def test_who_may_delete(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    lab_user = tickets["add_user"]("lab-user", "department_user", "h1", tickets["lab"])
    client.post(f"{API}/tickets/{tid}/assignments", headers=h["eng_h1"], json={"user_id": _me(client, h["tech_h1"])})
    by_reporter = _upload(client, h["dept_icu"], tid, png(), "r.png", "image/png").json()
    by_tech = _upload(client, h["tech_h1"], tid, png(), "t.png", "image/png").json()
    by_engineer = _upload(client, h["eng_h1"], tid, png(), "e.png", "image/png").json()
    files = {x["id"]: _file_of(tickets, x["id"]) for x in (by_reporter, by_tech, by_engineer)}

    # outside the caller's scope: 404, as for downloads - nothing changes
    for outsider in (h["tech_h2"], h["eng_h2"], lab_user, h["dept_none"]):
        _err(_delete(client, outsider, by_reporter["id"]), 404)
    _err(client.delete(f"{API}/attachments/{by_reporter['id']}"), 401)
    # visible, but someone else's photo: 403
    _err(_delete(client, h["dept_icu"], by_tech["id"]), 403)
    _err(_delete(client, h["tech_h1"], by_reporter["id"]), 403)
    assert all(_rows(tickets, i) == 1 and f.is_file() for i, f in files.items())

    assert _delete(client, h["tech_h1"], by_tech["id"]).status_code == 204          # own photo, active assignee
    assert _delete(client, h["eng_h1"], by_reporter["id"]).status_code == 204       # engineer of the hospital
    # an uploader who is no longer assigned cannot delete their photo any more; engineers still can
    again = _upload(client, h["tech_h1"], tid, png(), "t2.png", "image/png").json()
    assert client.delete(f"{API}/tickets/{tid}/assignments/{_me(client, h['tech_h1'])}",
                         headers=h["eng_h1"]).status_code == 200
    _err(_delete(client, h["tech_h1"], again["id"]), 403)
    assert _delete(client, h["admin"], again["id"]).status_code == 204
    assert _delete(client, h["admin"], by_engineer["id"]).status_code == 204
    assert not any(f.exists() for f in files.values())


def test_a_department_user_without_a_department_cannot_delete(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    a = _upload(client, h["dept_icu"], tid, png(), "a.png", "image/png").json()
    tickets["sql"]("UPDATE users SET department_id = NULL WHERE email = :e", e=tickets["world"]["staff"])
    _err(_delete(client, h["dept_icu"], a["id"]), 403, "department_required")
    assert _rows(tickets, a["id"]) == 1


def test_finished_tickets_only_admins_remove_photos(client, tickets):
    h, world = tickets["h"], tickets["world"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    a1 = _upload(client, h["dept_icu"], tid, png(), "a.png", "image/png").json()
    a2 = _upload(client, h["dept_icu"], tid, png(), "b.png", "image/png").json()
    assert client.patch(f"{API}/tickets/{tid}/status", headers=h["dept_icu"], json={"status": "cancelled"}).status_code == 200
    _err(_delete(client, h["dept_icu"], a1["id"]), 409)
    _err(_delete(client, h["eng_h1"], a1["id"]), 409)
    assert _delete(client, h["admin"], a1["id"]).status_code == 204                  # privacy removal
    assert client.delete(f"{API}/tickets/{tid}", headers=h["admin"]).status_code == 204   # soft-deleted ticket
    _err(_delete(client, h["dept_icu"], a2["id"]), 404)                                # no longer visible to them
    assert _delete(client, h["admin"], a2["id"]).status_code == 204

    h2 = tickets["report"](h["eng_h2"], "h2").json()["id"]
    a3 = _upload(client, h["eng_h2"], h2, png(), "c.png", "image/png").json()
    tickets["sql"]("UPDATE hospitals SET is_active = false WHERE id = :h", h=world["h2"])
    try:
        assert _delete(client, h["admin"], a3["id"]).status_code == 204              # inactive hospital: admin only
    finally:
        tickets["sql"]("UPDATE hospitals SET is_active = true WHERE id = :h", h=world["h2"])


def test_missing_files_legacy_rows_and_forged_keys(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    # the file has already disappeared from disk: the row is still removed
    a = _upload(client, h["dept_icu"], tid, png(), "a.png", "image/png").json()
    _file_of(tickets, a["id"]).unlink()
    assert _delete(client, h["dept_icu"], a["id"]).status_code == 204 and _rows(tickets, a["id"]) == 0
    # a pre-B5 row with an external URL: only the row is removed, the URL is never contacted
    legacy = tickets["sql"](
        "INSERT INTO attachments (organization_id, hospital_id, ticket_id, uploaded_by, file_url, file_name) "
        "SELECT organization_id, hospital_id, id, reported_by, 'https://example.com/seed.jpg', 'seed.jpg' "
        "FROM maintenance_tickets WHERE id = :t RETURNING id::text", t=tid)[0][0]
    assert _delete(client, h["admin"], legacy).status_code == 204 and _rows(tickets, legacy) == 0
    # a forged reference pointing outside the storage folder: the row goes, the outside file is untouched
    outside = Path(get_settings().storage_dir).parent / "outside-victim.jpg"
    outside.write_bytes(b"must survive")
    try:
        b = _upload(client, h["dept_icu"], tid, png(), "b.png", "image/png").json()
        real = _file_of(tickets, b["id"])
        tickets["sql"]("UPDATE attachments SET file_url = 'local:../outside-victim.jpg' WHERE id = :a", a=b["id"])
        assert _delete(client, h["dept_icu"], b["id"]).status_code == 204
        assert outside.read_bytes() == b"must survive"
        real.unlink()  # this test's own file, orphaned on purpose by the forged reference
    finally:
        outside.unlink(missing_ok=True)


def test_a_failed_database_delete_keeps_row_and_file(client, tickets, monkeypatch):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    a = _upload(client, h["dept_icu"], tid, png(), "a.png", "image/png").json()
    path = _file_of(tickets, a["id"])

    def fail(self, actor_id, obj, organization_id=None):
        raise RuntimeError("simulated database failure during the delete")

    monkeypatch.setattr(AuditService, "deleted", fail)
    with pytest.raises(RuntimeError):
        _delete(client, h["dept_icu"], a["id"])
    monkeypatch.undo()
    assert _rows(tickets, a["id"]) == 1 and path.is_file()
    assert client.get(a["file_url"], headers=h["dept_icu"]).status_code == 200      # still fully usable
    assert not tickets["sql"]("SELECT 1 FROM audit_logs WHERE record_id = :a AND action = 'delete'", a=a["id"])


def test_a_failed_file_removal_after_the_commit_is_logged_not_undone(client, tickets, monkeypatch, caplog):
    """The database is authoritative: the deletion stands, the unreferenced file is logged with its key."""
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    a = _upload(client, h["dept_icu"], tid, png(), "a.png", "image/png").json()
    path = _file_of(tickets, a["id"])

    def disk_error(self, key):
        raise OSError("simulated disk error")

    monkeypatch.setattr(LocalDiskStorage, "delete", disk_error)
    with caplog.at_level(logging.ERROR, logger="app.services.attachment_service"):
        assert _delete(client, h["dept_icu"], a["id"]).status_code == 204
    monkeypatch.undo()
    assert _rows(tickets, a["id"]) == 0
    assert tickets["sql"]("SELECT count(*) FROM audit_logs WHERE record_id = :a AND action = 'delete'", a=a["id"])[0][0] == 1
    key = path.relative_to(get_settings().storage_dir).as_posix()
    assert any("orphaned storage key" in r.getMessage() and key in r.getMessage() for r in caplog.records)
    assert path.is_file()                         # left behind, as logged; no row can serve it any more
    _err(client.get(a["file_url"], headers=h["dept_icu"]), 404)
    path.unlink()


def test_concurrent_deletes_of_one_photo(client, tickets):
    """Two deletes of the same photo wait for the ticket's row lock: one 204, one 404, one audit row."""
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    a = _upload(client, h["dept_icu"], tid, png(), "a.png", "image/png").json()
    before = _files()
    results = [None] * 2
    with get_session_factory()() as holder:
        holder.execute(text("SELECT id FROM maintenance_tickets WHERE id = :t FOR UPDATE"), {"t": tid})

        def run(i, who):
            with TestClient(client.app) as c:
                results[i] = _delete(c, h[who], a["id"])

        threads = [threading.Thread(target=run, args=(0, "dept_icu")), threading.Thread(target=run, args=(1, "eng_h1"))]
        for t in threads:
            t.start()
        time.sleep(1.0)
        blocked = [t.is_alive() for t in threads]
        holder.rollback()
    for t in threads:
        t.join(timeout=30)
    assert blocked == [True, True], "deletes did not wait for the ticket's row lock"
    assert sorted(r.status_code for r in results) == [204, 404]
    assert tickets["sql"]("SELECT count(*) FROM audit_logs WHERE record_id = :a AND action = 'delete'", a=a["id"])[0][0] == 1
    assert len(before - _files()) == 1


def test_only_ticket_photos_can_be_deleted(client, tickets):
    h, d = tickets["h"], tickets["d"]
    device_photo = tickets["sql"](
        "INSERT INTO attachments (organization_id, hospital_id, device_id, uploaded_by, file_url, file_name) "
        "SELECT organization_id, hospital_id, id, (SELECT id FROM users WHERE email = :e), 'local:00/x.jpg', 'x.jpg' "
        "FROM devices WHERE id = :d RETURNING id::text", d=d["icu"]["id"], e=tickets["world"]["staff"])[0][0]
    _err(_delete(client, h["admin"], device_photo), 400)
    assert _rows(tickets, device_photo) == 1
