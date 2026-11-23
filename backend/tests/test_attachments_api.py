"""B5 CP4 - ticket photo attachments (Decision 5) against REAL PostgreSQL: content-checked JPEG / PNG
only, GPS / EXIF removed, size and count limits (count under the ticket row lock), who may upload and
download, files served only through the API, legacy rows, and no file without its row (or row
without its file) when something fails. Skipped unless TEST_DATABASE_URL is set; rows are removed
by tests/ticket_scene.py, files live in the session's temporary STORAGE_DIR (tests/conftest.py).
"""
import io
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.services.audit_service import AuditService
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API


def jpeg_with_gps(size=(64, 48), maker="SecretCam") -> bytes:
    exif = Image.Exif()
    exif[0x010F] = maker
    exif[0x8825] = {1: "N", 2: (30.0, 2.0, 40.0), 3: "E", 4: (31.0, 14.0, 5.0)}
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


def _files() -> set:
    root = Path(get_settings().storage_dir)
    return {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def _err(r, status, code=None):
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text


def _upload(client, headers, tid, content, name="photo.jpg", mime="image/jpeg"):
    return client.post(f"{API}/tickets/{tid}/attachments", headers=headers, files={"file": (name, content, mime)})


def test_reporter_uploads_a_photo_without_its_location_and_downloads_it(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    raw = jpeg_with_gps()
    assert b"SecretCam" in raw
    before = _files()
    r = _upload(client, h["dept_icu"], tid, raw, name="C:\\Users\\nurse\\Pictures\\pump display.JPEG")
    assert r.status_code == 201, r.text
    a = r.json()
    assert (a["file_name"], a["mime_type"], a["file_url"]) == ("pump display.jpg", "image/jpeg", f"/api/v1/attachments/{a['id']}")
    assert len(_files() - before) == 1

    d = client.get(a["file_url"], headers=h["dept_icu"])
    assert d.status_code == 200 and d.headers["content-type"] == "image/jpeg"
    assert d.headers["x-content-type-options"] == "nosniff" and "no-store" in d.headers["cache-control"]
    assert len(d.content) == a["file_size_bytes"]
    assert b"SecretCam" not in d.content and b"Exif" not in d.content
    assert dict(Image.open(io.BytesIO(d.content)).getexif()) == {}

    detail = client.get(f"{API}/tickets/{tid}", headers=h["dept_icu"]).json()
    assert [x["id"] for x in detail["attachments"]] == [a["id"]]
    assert client.get(f"{API}/tickets/{tid}/attachments", headers=h["eng_h1"]).json()[0]["id"] == a["id"]
    # the stored reference is internal, never a URL; the row and its audit row share one transaction
    (url, xmin), = tickets["sql"]("SELECT file_url, xmin::text FROM attachments WHERE id = :a", a=a["id"])
    assert url.startswith("local:") and "://" not in url
    assert tickets["sql"]("SELECT xmin::text FROM audit_logs WHERE table_name = 'attachments' AND record_id = :a",
                          a=a["id"]) == [(xmin,)]


def test_who_may_upload_and_download(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    lab_user = tickets["add_user"]("lab-user", "department_user", "h1", tickets["lab"])
    _err(_upload(client, h["tech_h1"], tid, png(), "a.png", "image/png"), 403)     # sees it, but not working on it
    _err(_upload(client, h["tech_h2"], tid, png(), "a.png", "image/png"), 404)     # other hospital
    _err(_upload(client, lab_user, tid, png(), "a.png", "image/png"), 404)         # not their report
    r = _upload(client, h["eng_h1"], tid, png(), "board.png", "image/png")
    assert r.status_code == 201 and r.json()["mime_type"] == "image/png"
    tech = client.get(f"{API}/auth/me", headers=h["tech_h1"]).json()
    client.post(f"{API}/tickets/{tid}/assignments", headers=h["eng_h1"], json={"user_id": tech["id"]})
    assert _upload(client, h["tech_h1"], tid, jpeg_with_gps()).status_code == 201  # now assigned
    assert _upload(client, h["admin"], tid, jpeg_with_gps()).status_code == 201
    _err(_upload(client, h["dept_icu"], tid, jpeg_with_gps()), 409, "attachment_limit_reached")

    # the reporter sees staff as roles (Q9); staff see names
    as_reporter = client.get(f"{API}/tickets/{tid}/attachments", headers=h["dept_icu"]).json()
    assert [(x["uploaded_by"]["id"], x["uploaded_by"]["name"]) for x in as_reporter][0] == (None, "Biomedical engineer")
    assert client.get(f"{API}/tickets/{tid}/attachments", headers=h["admin"]).json()[0]["uploaded_by"]["id"] is not None

    url = r.json()["file_url"]
    assert client.get(url, headers=h["dept_icu"]).status_code == 200
    for outsider in (h["tech_h2"], h["eng_h2"], lab_user, h["dept_none"]):
        _err(client.get(url, headers=outsider), 404)
    _err(client.get(f"{API}/tickets/{tid}/attachments", headers=h["tech_h2"]), 404)
    _err(client.get(url), 401)


def test_only_real_jpeg_and_png_within_the_size_limit(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    before = _files()
    gif = io.BytesIO()
    Image.new("RGB", (4, 4)).save(gif, "GIF")
    _err(_upload(client, h["dept_icu"], tid, b"not an image at all", "photo.jpg"), 415, "unsupported_file")
    _err(_upload(client, h["dept_icu"], tid, gif.getvalue(), "photo.png", "image/png"), 415, "unsupported_file")
    _err(_upload(client, h["dept_icu"], tid, jpeg_with_gps()[:200]), 415, "unsupported_file")     # truncated
    _err(_upload(client, h["dept_icu"], tid, b""), 415, "unsupported_file")
    too_big = b"\xff\xd8" + os.urandom(get_settings().max_upload_bytes)
    _err(_upload(client, h["dept_icu"], tid, too_big), 413, "file_too_large")
    _err(client.post(f"{API}/tickets/{tid}/attachments", headers=h["dept_icu"]), 422)            # no file
    assert _files() == before
    assert tickets["sql"]("SELECT count(*) FROM attachments WHERE ticket_id = :t", t=tid)[0][0] == 0


def test_no_attachments_on_finished_deleted_or_inactive_tickets(client, tickets):
    h, world = tickets["h"], tickets["world"]
    cancelled = tickets["report"](h["dept_icu"], "icu").json()["id"]
    client.patch(f"{API}/tickets/{cancelled}/status", headers=h["dept_icu"], json={"status": "cancelled"})
    _err(_upload(client, h["dept_icu"], cancelled, png(), "a.png", "image/png"), 409)
    deleted = tickets["report"](h["dept_icu"], "icu").json()["id"]
    assert client.delete(f"{API}/tickets/{deleted}", headers=h["admin"]).status_code == 204
    _err(_upload(client, h["admin"], deleted, png(), "a.png", "image/png"), 409)
    _err(_upload(client, h["dept_icu"], deleted, png(), "a.png", "image/png"), 404)   # gone for non-admins
    h2_ticket = tickets["report"](h["eng_h2"], "h2").json()["id"]
    tickets["sql"]("UPDATE hospitals SET is_active = false WHERE id = :h", h=world["h2"])
    try:
        _err(_upload(client, h["admin"], h2_ticket, png(), "a.png", "image/png"), 400)
    finally:
        tickets["sql"]("UPDATE hospitals SET is_active = true WHERE id = :h", h=world["h2"])


def test_parallel_uploads_respect_the_limit_of_three(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    before = _files()
    content = jpeg_with_gps()
    results = [None] * 5
    with get_session_factory()() as holder:
        holder.execute(text("SELECT id FROM maintenance_tickets WHERE id = :t FOR UPDATE"), {"t": tid})

        def run(i):
            with TestClient(client.app) as c:
                results[i] = _upload(c, h["dept_icu"], tid, content, f"p{i}.jpg")

        threads = [threading.Thread(target=run, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        time.sleep(1.0)
        blocked = [t.is_alive() for t in threads]
        holder.rollback()
    for t in threads:
        t.join(timeout=30)
    assert blocked == [True] * 5, "uploads did not wait for the ticket's row lock"
    assert sorted(r.status_code for r in results) == [201, 201, 201, 409, 409]
    assert tickets["sql"]("SELECT count(*) FROM attachments WHERE ticket_id = :t", t=tid)[0][0] == 3
    assert len(_files() - before) == 3   # the refused uploads left no file behind


def test_a_failed_database_write_leaves_no_file(client, tickets, monkeypatch):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    before = _files()
    original = AuditService.inserted

    def fail_for_attachments(self, actor_id, obj, organization_id=None):
        if obj.__tablename__ == "attachments":
            raise RuntimeError("simulated database failure after the file was written")
        return original(self, actor_id, obj, organization_id)

    monkeypatch.setattr(AuditService, "inserted", fail_for_attachments)
    with pytest.raises(RuntimeError):
        _upload(client, h["dept_icu"], tid, jpeg_with_gps())
    monkeypatch.undo()
    assert _files() == before
    assert tickets["sql"]("SELECT count(*) FROM attachments WHERE ticket_id = :t", t=tid)[0][0] == 0


def test_rows_without_a_stored_file_are_listed_but_never_fetched(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    legacy = tickets["sql"](
        "INSERT INTO attachments (organization_id, hospital_id, ticket_id, uploaded_by, file_url, file_name, mime_type) "
        "SELECT organization_id, hospital_id, id, reported_by, 'https://example.com/seed.jpg', 'seed.jpg', 'image/jpeg' "
        "FROM maintenance_tickets WHERE id = :t RETURNING id::text", t=tid)[0][0]
    assert [a["id"] for a in client.get(f"{API}/tickets/{tid}", headers=h["dept_icu"]).json()["attachments"]] == [legacy]
    r = client.get(f"{API}/attachments/{legacy}", headers=h["dept_icu"])
    _err(r, 404)
    assert "example.com" not in r.text and "location" not in r.headers
    # a stored file that has gone missing from disk
    a = _upload(client, h["dept_icu"], tid, png(), "a.png", "image/png").json()
    (url,), = tickets["sql"]("SELECT file_url FROM attachments WHERE id = :a", a=a["id"])
    (Path(get_settings().storage_dir) / url.split(":", 1)[1]).unlink()
    _err(client.get(a["file_url"], headers=h["dept_icu"]), 404)
    # a forged reference cannot escape the storage folder
    tickets["sql"]("UPDATE attachments SET file_url = 'local:../../etc/passwd' WHERE id = :a", a=a["id"])
    _err(client.get(a["file_url"], headers=h["dept_icu"]), 404)
