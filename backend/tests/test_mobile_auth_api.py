"""B8 CP1 - the mobile authentication contract against REAL PostgreSQL.

- POST /auth/login answers `{token, user}` as the Master Instructions (section 5) require; `token` is the
  same value as `access_token`, which stays for existing clients.
- POST /auth/forgot-password (team decision 2026-11-26): always 202 with one message; for an account that
  can sign in, the organization's admins get one in-app `password_reset_requested` notification each
  (not the account itself, not again while an earlier one is unread); audited with no actor.
Skipped unless TEST_DATABASE_URL is set; the `world` fixture removes everything it created.
"""
import logging
import threading
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.database import get_session_factory
from app.core.security import hash_password
from app.models import Role, User
from app.schemas.auth import FORGOT_PASSWORD_MESSAGE
from app.services.notification_service import Notifier
from tests.world import API, PW, auth, login

KIND = "password_reset_requested"


def _forgot(client, value, field="email"):
    return client.post(f"{API}/auth/forgot-password", json={field: value})


def _sql(query, **params):
    with get_session_factory()() as db:
        result = db.execute(text(query), params)
        rows = result.all() if result.returns_rows else []
        db.commit()
        return rows


def _requests(org):
    """(recipient email, title, body, is_read) of every reset-request notification of the organization."""
    return _sql("SELECT u.email, n.title, n.body, n.is_read FROM notifications n JOIN users u ON u.id = n.user_id "
                "WHERE n.organization_id = :o AND n.notification_type = :k ORDER BY n.created_at", o=org, k=KIND)


def _add_admin(world, email):
    with get_session_factory()() as db:
        role = db.scalar(select(Role.id).where(Role.name == "admin"))
        admin = db.scalar(select(User).where(User.email == world["admin"]))
        db.add(User(organization_id=admin.organization_id, hospital_id=admin.hospital_id, role_id=role,
                    full_name=email.split("@")[0], email=email, password_hash=hash_password(PW), is_active=True))
        db.commit()


# ---- login: {token, user} ---------------------------------------------------------------------------------
def test_login_answers_token_and_user(client, world):
    body = login(client, world["staff"]).json()
    assert body["token"] == body["access_token"] and body["token"].count(".") == 2   # one JWT, two names
    assert {"token", "user", "access_token", "token_type", "expires_in"} <= set(body)
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['token']}"}).status_code == 200


# ---- forgot password ----------------------------------------------------------------------------------------
def test_every_request_gets_the_same_answer(client, world):
    """Existing, unknown, inactive and other-organization accounts, by `email` or `identifier`, any case:
    one status and one body, so the endpoint cannot be used to find registered emails."""
    responses = [_forgot(client, world["staff"]), _forgot(client, world["staff"].upper(), "identifier"),
                 _forgot(client, "nobody@b2.test"), _forgot(client, world["inactive"]),
                 _forgot(client, f"stranger-{world['sfx']}@b2.test")]
    assert {r.status_code for r in responses} == {202}
    assert {r.text for r in responses} == {f'{{"message":"{FORGOT_PASSWORD_MESSAGE}"}}'}


def test_admins_are_notified_once_per_unread_request(client, world):
    org, staff = world["org"], world["staff"]
    assert _forgot(client, staff).status_code == 202
    rows = _requests(org)
    assert [(r[0], r[1], r[3]) for r in rows] == [(world["admin"], "Password reset requested", False)]
    assert staff in rows[0][2] and "Set a new password in user management." in rows[0][2]
    # the admin sees it in the normal inbox (the same endpoint the mobile app uses)
    inbox = client.get(f"{API}/notifications", headers=auth(client, world["admin"])).json()["items"]
    assert [(n["type"], n["title"]) for n in inbox if n["type"] == KIND] == [(KIND, "Password reset requested")]
    # repeated while the first is unread: no second notification
    for _ in range(3):
        assert _forgot(client, staff.upper(), "identifier").status_code == 202
    assert len(_requests(org)) == 1
    # once read, a new request notifies again
    note = next(n for n in inbox if n["type"] == KIND)
    assert client.patch(f"{API}/notifications/{note['id']}/read",
                        headers=auth(client, world["admin"])).status_code == 200
    _forgot(client, staff)
    assert [r[3] for r in _requests(org)] == [True, False]
    # nobody else was notified: not the account itself, not the technician
    others = _sql("SELECT count(*) FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.email IN (:a, :b) "
                  "AND n.notification_type = :k", a=staff, b=world["tech"], k=KIND)[0][0]
    assert others == 0


def test_unknown_and_blocked_accounts_store_nothing(client, world):
    org = world["org"]
    before = _sql("SELECT count(*) FROM audit_logs WHERE organization_id = :o", o=org)[0][0]
    for email in ("nobody@b2.test", world["inactive"]):
        assert _forgot(client, email).status_code == 202
    _sql("UPDATE hospitals SET is_active = false WHERE organization_id = :o AND code = 'H1'", o=org)
    try:
        assert _forgot(client, world["staff"]).status_code == 202        # hospital inactive: cannot sign in
    finally:
        _sql("UPDATE hospitals SET is_active = true WHERE organization_id = :o AND code = 'H1'", o=org)
    assert _requests(org) == []
    assert _sql("SELECT count(*) FROM audit_logs WHERE organization_id = :o", o=org)[0][0] == before


def test_the_request_is_audited_without_an_actor(client, world):
    org = world["org"]
    _forgot(client, world["tech"])
    rows = _sql("SELECT a.user_id, a.action::text, a.new_values->>'notification_type', a.new_values->>'user_id' "
                "FROM audit_logs a WHERE a.organization_id = :o AND a.table_name = 'notifications' "
                "AND a.new_values->>'notification_type' = :k", o=org, k=KIND)
    assert rows == [(None, "insert", KIND, world["admin_id"])]


def test_an_admin_asking_for_themself_notifies_the_other_admins(client, world):
    org = world["org"]
    _forgot(client, world["admin"])                       # the only admin: nobody else to ask
    assert _requests(org) == []
    second = f"admin2-{world['sfx']}@b2.test"
    _add_admin(world, second)
    _forgot(client, world["admin"])
    assert [r[0] for r in _requests(org)] == [second]


def test_the_admin_resets_the_password_and_the_user_signs_in(client, world):
    """The whole flow: request -> admin notified -> existing admin reset endpoint -> new password works,
    and tokens issued before the reset stop working (password stamp)."""
    old_token = login(client, world["staff"]).json()["token"]
    _forgot(client, world["staff"])
    staff_id = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {old_token}"}).json()["id"]
    new_password = "N3w-Passw0rd-" + uuid.uuid4().hex[:6]
    r = client.post(f"{API}/users/{staff_id}/reset-password", headers=auth(client, world["admin"]),
                    json={"new_password": new_password})
    assert r.status_code == 204, r.text
    assert login(client, world["staff"], new_password).status_code == 200
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401


def test_bad_bodies_are_422(client, world):
    for body in ({}, {"email": ""}, {"identifier": "x" * 256}):
        r = client.post(f"{API}/auth/forgot-password", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", (body, r.text)


def test_requests_for_two_admins_at_once_do_not_deadlock(client, world, monkeypatch):
    """Review finding: requests for admin A and admin B at the same time. Each request locks its own
    account row, then inserts a notification for the OTHER admin, whose foreign key takes a KEY SHARE
    lock on that admin's row. With FOR UPDATE the two transactions waited for each other (deadlock, one
    request lost). The account lock is FOR NO KEY UPDATE, which foreign-key checks do not wait for."""
    org, second = world["org"], f"admin2-{world['sfx']}@b2.test"
    _add_admin(world, second)
    both_locked = threading.Barrier(2, timeout=10)
    original = Notifier.password_reset_requested

    def at_the_same_time(self, user):
        try:
            both_locked.wait()        # each request holds its own account's row lock here
        except threading.BrokenBarrierError:
            pass
        return original(self, user)

    monkeypatch.setattr(Notifier, "password_reset_requested", at_the_same_time)
    statuses = []

    def ask(email):
        with TestClient(client.app) as c:
            statuses.append(_forgot(c, email).status_code)

    threads = [threading.Thread(target=ask, args=(email,)) for email in (world["admin"], second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert statuses == [202, 202]
    assert sorted(r[0] for r in _requests(org)) == sorted([world["admin"], second])   # each told about the other


def test_the_answer_does_not_wait_for_the_processing(client, world, monkeypatch, caplog):
    """The request is processed after the 202 is sent (BackgroundTasks, own session): even when the
    processing fails the caller gets the same answer, and the failure is only logged."""
    from app.services.auth_service import AuthService

    def broken(self, identifier):
        raise RuntimeError("database gone")

    monkeypatch.setattr(AuthService, "request_password_reset", broken)
    with caplog.at_level(logging.ERROR, logger="app.services.auth_service"):
        r = _forgot(client, world["staff"])
    assert (r.status_code, r.json()["message"]) == (202, FORGOT_PASSWORD_MESSAGE)
    assert "Password reset request could not be processed" in caplog.text
    assert world["staff"] not in caplog.text                     # the typed identifier is never logged
