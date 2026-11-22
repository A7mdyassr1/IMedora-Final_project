"""Shared CP3 scenario on top of the `world` fixture (tests only).

    Organization (world["org"])
      H1: ICU (world), Lab (added here)
      H2: Radiology (world)
    Devices (created by the admin):  icu, lab, h2, archived (H1/ICU, archived)
    Users: dept_icu (= world staff), dept_none (H1, no department), tech_h1 (= world tech),
           eng_h1, eng_h2, tech_h2, admin (= world admin)

Rows are removed by the existing fixtures' teardown: devices by `cat`, users and
departments by `world` (which also clears their audit rows first).
"""
import pytest
from sqlalchemy import select

from app.core.database import get_session_factory
from app.core.security import hash_password
from app.models import Department, Role, User
from tests.test_devices_flow import make_device
from tests.world import PW, auth


def _add_user(db, world, email, role, hospital_key, department_id=None):
    role_id = db.scalar(select(Role.id).where(Role.name == role))
    u = User(organization_id=world["org"], hospital_id=world[hospital_key], department_id=department_id,
             role_id=role_id, full_name=email.split("@")[0], email=email,
             password_hash=hash_password(PW), is_active=True)
    db.add(u)
    db.flush()
    return u.email


@pytest.fixture
def scene(client, world, cat):
    sfx = world["sfx"]
    with get_session_factory()() as db:
        lab = Department(hospital_id=world["h1"], name="Lab")
        db.add(lab)
        db.flush()
        lab_id = str(lab.id)
        emails = dict(
            dept_none=_add_user(db, world, f"dept-none-{sfx}@b2.test", "department_user", "h1"),
            eng_h1=_add_user(db, world, f"eng-h1-{sfx}@b2.test", "biomedical_engineer", "h1"),
            eng_h2=_add_user(db, world, f"eng-h2-{sfx}@b2.test", "biomedical_engineer", "h2"),
            tech_h2=_add_user(db, world, f"tech-h2-{sfx}@b2.test", "technician", "h2"),
        )
        db.commit()
    h = {
        "admin": auth(client, world["admin"]),
        "dept_icu": auth(client, world["staff"]),     # department_user, H1 / ICU
        "tech_h1": auth(client, world["tech"]),       # technician, H1
        **{k: auth(client, v) for k, v in emails.items()},
    }
    admin = h["admin"]
    devices = dict(
        icu=make_device(client, admin, world, cat, name="ICU ventilator", device_code="S-ICU",
                        serial_number="SN-SECRET-1", criticality="critical"),
        lab=make_device(client, admin, world, cat, name="Lab analyser", device_code="S-LAB",
                        department_id=lab_id, serial_number="SN-SECRET-2"),
        h2=make_device(client, admin, world, cat, name="H2 scanner", device_code="S-H2",
                       hospital_id=world["h2"], department_id=world["rad"]),
        archived=make_device(client, admin, world, cat, name="Old ICU ventilator", device_code="S-ARCH"),
    )
    assert client.delete(f"/api/v1/devices/{devices['archived']['id']}", headers=admin).status_code == 200
    return dict(h=h, d=devices, lab=lab_id, world=world, cat=cat)
