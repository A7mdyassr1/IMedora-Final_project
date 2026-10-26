"""Shared integration-test world: two organizations with hospitals, departments and users.
Needs TEST_DATABASE_URL (see conftest.py). Torn down bottom-up, scoped to the rows it created."""
import uuid

import pytest
from sqlalchemy import delete, select

from app.core.database import get_session_factory
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
