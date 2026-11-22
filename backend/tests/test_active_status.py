"""
Organization / hospital active status (Decision 6, B3.1 CP2) against REAL PostgreSQL.
Skipped unless TEST_DATABASE_URL is set.

- Inactive organization or hospital: login refused with the SAME message as a wrong password,
  and tokens already issued stop working on the next request.
- Nothing new is added to an inactive hospital; editing what is already there stays allowed.
- Lock-out guard: an admin cannot deactivate the hospital they belong to.
"""
import pytest
from sqlalchemy import text

from app.core.database import get_session_factory
from tests.test_devices_flow import cat, eng, make_device  # noqa: F401  (pytest fixtures)
from tests.world import API, PW, auth, login

BAD_LOGIN = "Invalid email or password."
BAD_TOKEN = "Invalid or expired token."


def _sql(stmt: str, **params):
    with get_session_factory()() as db:
        db.execute(text(stmt), params)
        db.commit()


def _me(client, headers):
    return client.get(f"{API}/auth/me", headers=headers)


def _user_in_h2(client, world, admin, role="technician"):
    email = f"h2-{role}-{world['sfx']}@b2.test"
    r = client.post(f"{API}/users", headers=admin, json=dict(
        email=email, full_name="H2 Person", password=PW, role=role, hospital_id=world["h2"]))
    assert r.status_code == 201, r.text
    return email, r.json()["id"]


# ---- inactive organization -------------------------------------------------------------------
def test_inactive_organization_blocks_login_and_existing_tokens(client, world):
    token = auth(client, world["tech"])
    assert _me(client, token).status_code == 200
    # No API changes an organization's status (deployment-level decision), so set it directly.
    _sql("UPDATE organizations SET is_active = false WHERE id = :o", o=world["org"])

    r = login(client, world["tech"])
    assert r.status_code == 401 and r.json()["error"]["message"] == BAD_LOGIN  # state not revealed
    r = _me(client, token)
    assert r.status_code == 401 and r.json()["error"]["message"] == BAD_TOKEN
    assert login(client, world["admin"]).status_code == 401  # admins too

    _sql("UPDATE organizations SET is_active = true WHERE id = :o", o=world["org"])
    assert login(client, world["tech"]).status_code == 200  # reversible
    assert _me(client, token).status_code == 200


def test_other_organizations_are_unaffected(client, world):
    _sql("UPDATE organizations SET is_active = false WHERE id = :o", o=world["other"])
    assert login(client, world["tech"]).status_code == 200


def test_create_user_script_refuses_an_inactive_organization(world, monkeypatch):
    import sys
    from scripts import create_user
    _sql("UPDATE organizations SET is_active = false WHERE id = :o", o=world["org"])
    monkeypatch.setenv("IMEDORA_USER_PASSWORD", "Script-Pass-123")
    monkeypatch.setattr(sys, "argv", ["create_user", "--email", f"cli-off-{world['sfx']}@b2.test",
                                      "--organization-code", f"B2-{world['sfx']}", "--full-name", "X",
                                      "--hospital-code", "H1", "--role", "technician"])
    with pytest.raises(SystemExit) as exc:
        create_user.main()
    assert "inactive" in str(exc.value.code)


# ---- inactive hospital -----------------------------------------------------------------------
def test_inactive_hospital_blocks_its_staff_but_not_other_hospitals(client, world):
    admin = auth(client, world["admin"])  # admin belongs to H1
    email, _ = _user_in_h2(client, world, admin)
    h2_token = auth(client, email)

    assert client.patch(f"{API}/hospitals/{world['h2']}", headers=admin, json={"is_active": False}).status_code == 200
    r = login(client, email)
    assert r.status_code == 401 and r.json()["error"]["message"] == BAD_LOGIN
    assert _me(client, h2_token).status_code == 401
    assert _me(client, admin).status_code == 200            # H1 staff unaffected
    assert login(client, world["tech"]).status_code == 200

    assert client.patch(f"{API}/hospitals/{world['h2']}", headers=admin, json={"is_active": True}).status_code == 200
    assert login(client, email).status_code == 200            # reactivation restores access


def test_admin_cannot_deactivate_their_own_hospital(client, world):
    admin = auth(client, world["admin"])
    r = client.patch(f"{API}/hospitals/{world['h1']}", headers=admin, json={"is_active": False})
    assert r.status_code == 400 and "lock you out" in r.json()["error"]["message"]
    assert client.get(f"{API}/hospitals/{world['h1']}", headers=admin).json()["is_active"] is True
    assert _me(client, admin).status_code == 200
    # other edits of their own hospital, and deactivating ANOTHER hospital, still work
    assert client.patch(f"{API}/hospitals/{world['h1']}", headers=admin, json={"name": "Hospital One (main)"}).status_code == 200
    assert client.patch(f"{API}/hospitals/{world['h1']}", headers=admin, json={"is_active": True}).status_code == 200
    assert client.patch(f"{API}/hospitals/{world['h2']}", headers=admin, json={"is_active": False}).status_code == 200


def test_non_admins_still_cannot_change_hospitals(client, world):
    tech = auth(client, world["tech"])
    assert client.patch(f"{API}/hospitals/{world['h2']}", headers=tech, json={"is_active": False}).status_code == 403


def test_nothing_new_can_be_added_to_an_inactive_hospital(client, world, cat, eng):
    admin = auth(client, world["admin"])
    # CP3 setup change: everything here happens in H2, which the H1 engineer can no longer reach,
    # so the organization-wide admin performs the device operations.
    existing = make_device(client, admin, world, cat, hospital_id=world["h2"], department_id=world["rad"])
    assert client.patch(f"{API}/hospitals/{world['h2']}", headers=admin, json={"is_active": False}).status_code == 200

    def refused(r, what):
        assert r.status_code == 400, r.text
        assert r.json()["error"]["message"] == f"Hospital is inactive; {what} cannot be added to it."

    refused(client.post(f"{API}/devices", headers=admin, json=dict(
        hospital_id=world["h2"], department_id=world["rad"], device_model_id=cat["model_a"],
        device_code="NEW-IN-H2", name="New")), "devices")
    refused(client.post(f"{API}/users", headers=admin, json=dict(
        email=f"late-{world['sfx']}@b2.test", full_name="Late", password=PW, role="technician",
        hospital_id=world["h2"])), "users")
    refused(client.post(f"{API}/departments", headers=admin, json={"hospital_id": world["h2"], "name": "New Dept"}), "departments")
    refused(client.post(f"{API}/locations", headers=admin, json={"hospital_id": world["h2"], "room": "9"}), "locations")
    # moving an existing user INTO the inactive hospital counts as adding
    refused(client.patch(f"{API}/users/{world['tech_id']}", headers=admin, json={"hospital_id": world["h2"]}), "users")

    # editing what already exists there is still allowed (records stay readable and correctable)
    assert client.patch(f"{API}/departments/{world['rad']}", headers=admin, json={"name": "Radiology (closed)"}).status_code == 200
    assert client.patch(f"{API}/devices/{existing['id']}", headers=admin, json={"name": "Old scanner"}).status_code == 200
    assert client.get(f"{API}/devices/{existing['id']}", headers=admin).status_code == 200

    # active hospitals are unaffected
    assert client.post(f"{API}/departments", headers=admin, json={"hospital_id": world["h1"], "name": "Still OK"}).status_code == 201
