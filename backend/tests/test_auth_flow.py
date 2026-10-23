"""
Full auth + user-administration flows against REAL PostgreSQL.
Skipped unless TEST_DATABASE_URL points at a disposable database that has the
IMedora migrations applied. Creates its own organizations and removes them again.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.roles import Role as R
from app.core.security import hash_password
from app.models import Department, Hospital, Organization, Role, User
from app.repositories.role_repository import RoleRepository

PW = "Correct-Horse-9"
API = "/api/v1"


@pytest.fixture
def world(real_db_url):
    factory = get_session_factory()
    sfx = uuid.uuid4().hex[:8]
    with factory() as db:
        RoleRepository(db).ensure_standard_roles()
        org = Organization(name=f"B2 Org {sfx}", code=f"B2-{sfx}")
        other = Organization(name=f"B2 Other {sfx}", code=f"B2X-{sfx}")
        db.add_all([org, other])
        db.flush()
        h1 = Hospital(organization_id=org.id, name="Hospital One", code="H1")
        h2 = Hospital(organization_id=org.id, name="Hospital Two", code="H2")
        oh = Hospital(organization_id=other.id, name="Foreign Hospital", code="OH")
        db.add_all([h1, h2, oh])
        db.flush()
        icu = Department(hospital_id=h1.id, name="ICU")
        rad = Department(hospital_id=h2.id, name="Radiology")
        db.add_all([icu, rad])
        db.flush()
        roles = {r.name: r.id for r in db.scalars(select(Role))}

        def mk(email, role, org_, hosp, dept=None, active=True, pw=PW):
            u = User(organization_id=org_.id, hospital_id=hosp.id, department_id=dept.id if dept else None,
                     role_id=roles[role], full_name=email.split("@")[0], email=email,
                     password_hash=hash_password(pw), is_active=active)
            db.add(u)
            db.flush()
            return u

        admin = mk(f"admin-{sfx}@b2.test", "admin", org, h1)
        tech = mk(f"tech-{sfx}@b2.test", "technician", org, h1)
        staff = mk(f"staff-{sfx}@b2.test", "department_user", org, h1, icu)
        inactive = mk(f"off-{sfx}@b2.test", "technician", org, h1, active=False)
        stranger = mk(f"stranger-{sfx}@b2.test", "technician", other, oh)
        db.commit()
        data = dict(sfx=sfx, admin=admin.email, tech=tech.email, staff=staff.email, inactive=inactive.email,
                    admin_id=str(admin.id), tech_id=str(tech.id), stranger_id=str(stranger.id),
                    h1=str(h1.id), h2=str(h2.id), oh=str(oh.id), icu=str(icu.id), rad=str(rad.id),
                    org=str(org.id), other=str(other.id))
    yield data
    with factory() as db:  # bottom-up, scoped to the two test organizations
        orgs = [uuid.UUID(data["org"]), uuid.UUID(data["other"])]
        hosp_ids = select(Hospital.id).where(Hospital.organization_id.in_(orgs))
        db.execute(delete(User).where(User.organization_id.in_(orgs)))
        db.execute(delete(Department).where(Department.hospital_id.in_(hosp_ids)))
        db.execute(delete(Hospital).where(Hospital.organization_id.in_(orgs)))
        db.execute(delete(Organization).where(Organization.id.in_(orgs)))
        db.commit()


def login(client, email, password=PW):
    return client.post(f"{API}/auth/login", json={"identifier": email, "password": password})


def auth(client, email):
    r = login(client, email)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---- login ----------------------------------------------------------------
def test_login_success_returns_token_and_user(client, world):
    r = login(client, world["staff"].upper())  # email match is case-insensitive
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    u = body["user"]
    assert u["role"] == "department_user" and u["hospital_name"] == "Hospital One" and u["department_name"] == "ICU"
    assert "password" not in r.text and "hash" not in r.text


def test_login_accepts_email_field_alias(client, world):
    r = client.post(f"{API}/auth/login", json={"email": world["admin"], "password": PW})
    assert r.status_code == 200


def test_bad_logins_all_look_identical(client, world):
    responses = [
        login(client, world["admin"], "wrong-password-1"),
        login(client, "nobody@b2.test"),
        login(client, world["inactive"]),
    ]
    assert {r.status_code for r in responses} == {401}
    assert len({r.text for r in responses}) == 1  # no account enumeration


def test_me_with_valid_token_and_after_deactivation(client, world):
    h = auth(client, world["tech"])
    assert client.get(f"{API}/auth/me", headers=h).json()["email"] == world["tech"]
    admin_h = auth(client, world["admin"])
    assert client.patch(f"{API}/users/{world['tech_id']}", json={"is_active": False}, headers=admin_h).status_code == 200
    assert client.get(f"{API}/auth/me", headers=h).status_code == 401  # old token dies immediately
    assert login(client, world["tech"]).status_code == 401


def test_token_for_a_deleted_user_is_rejected(client, world):
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        get_settings().jwt_secret_key.get_secret_value(), algorithm="HS256")
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# ---- change password ----------------------------------------------------------
def test_change_password(client, world):
    h = auth(client, world["staff"])
    url = f"{API}/auth/change-password"
    assert client.post(url, json={"current_password": "nope-nope-1", "new_password": "Brand-New-Pass-1"}, headers=h).status_code == 400
    assert client.post(url, json={"current_password": PW, "new_password": "short"}, headers=h).status_code == 422
    assert client.post(url, json={"current_password": PW, "new_password": PW}, headers=h).status_code == 400
    assert client.post(url, json={"current_password": PW, "new_password": "Brand-New-Pass-1"}, headers=h).status_code == 204
    assert login(client, world["staff"], PW).status_code == 401
    assert login(client, world["staff"], "Brand-New-Pass-1").status_code == 200


# ---- authorization --------------------------------------------------------------
@pytest.mark.parametrize("who", ["tech", "staff"])
def test_non_admins_cannot_use_user_administration(client, world, who):
    h = auth(client, world[who])
    assert client.get(f"{API}/users", headers=h).status_code == 403
    assert client.post(f"{API}/users", headers=h, json={}).status_code == 403  # 403 before body validation


# ---- user administration -----------------------------------------------------------
def new_user(world, **over):
    body = dict(email=f"New-{uuid.uuid4().hex[:6]}@b2.test", full_name="New Person", password=PW,
                role="biomedical_engineer", hospital_id=world["h1"])
    return {**body, **over}


def test_admin_creates_user_who_can_log_in(client, world):
    h = auth(client, world["admin"])
    body = new_user(world, department_id=world["icu"])
    r = client.post(f"{API}/users", json=body, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["email"] == body["email"].lower() and r.json()["organization_id"] == world["org"]
    assert login(client, body["email"]).status_code == 200


def test_create_rejects_duplicates_and_bad_placement(client, world):
    h = auth(client, world["admin"])
    assert client.post(f"{API}/users", json=new_user(world, email=world["tech"].upper()), headers=h).status_code == 409
    assert client.post(f"{API}/users", json=new_user(world, hospital_id=world["oh"]), headers=h).status_code == 400   # other org's hospital
    assert client.post(f"{API}/users", json=new_user(world, department_id=world["rad"]), headers=h).status_code == 400  # dept of hospital 2


def test_list_filter_and_paginate(client, world):
    h = auth(client, world["admin"])
    page = client.get(f"{API}/users", params={"page_size": 2}, headers=h).json()
    assert page["total"] == 4 and len(page["items"]) == 2 and page["page"] == 1  # stranger (other org) excluded
    only_tech = client.get(f"{API}/users", params={"role": "technician"}, headers=h).json()
    assert {u["role"] for u in only_tech["items"]} == {"technician"} and only_tech["total"] == 2
    assert client.get(f"{API}/users", params={"q": "staff-"}, headers=h).json()["total"] == 1
    assert client.get(f"{API}/users", params={"page_size": 500}, headers=h).status_code == 422


def test_organization_isolation(client, world):
    h = auth(client, world["admin"])
    sid = world["stranger_id"]
    assert client.get(f"{API}/users/{sid}", headers=h).status_code == 404
    assert client.patch(f"{API}/users/{sid}", json={"full_name": "Hacked"}, headers=h).status_code == 404
    assert client.post(f"{API}/users/{sid}/reset-password", json={"new_password": "Hijacked-Pass-1"}, headers=h).status_code == 404


def test_update_role_and_placement(client, world):
    h = auth(client, world["admin"])
    url = f"{API}/users/{world['tech_id']}"
    r = client.patch(url, json={"role": "biomedical_engineer", "full_name": "  Renamed "}, headers=h)
    assert r.status_code == 200 and r.json()["role"] == "biomedical_engineer" and r.json()["full_name"] == "Renamed"
    assert client.patch(url, json={"hospital_id": world["h2"], "department_id": world["rad"]}, headers=h).json()["department_name"] == "Radiology"
    assert client.patch(url, json={"hospital_id": world["h1"]}, headers=h).status_code == 400  # old dept belongs to hospital 2
    assert client.patch(url, json={"hospital_id": world["h1"], "department_id": None}, headers=h).status_code == 200


def test_admin_cannot_lock_themselves_out(client, world):
    h = auth(client, world["admin"])
    url = f"{API}/users/{world['admin_id']}"
    assert client.patch(url, json={"is_active": False}, headers=h).status_code == 400
    assert client.patch(url, json={"role": "technician"}, headers=h).status_code == 400


def test_admin_reset_password(client, world):
    h = auth(client, world["admin"])
    r = client.post(f"{API}/users/{world['tech_id']}/reset-password", json={"new_password": "Reset-By-Admin-1"}, headers=h)
    assert r.status_code == 204
    assert login(client, world["tech"], PW).status_code == 401
    assert login(client, world["tech"], "Reset-By-Admin-1").status_code == 200


def test_bad_uuid_in_path_is_422(client, world):
    assert client.get(f"{API}/users/not-a-uuid", headers=auth(client, world["admin"])).status_code == 422
