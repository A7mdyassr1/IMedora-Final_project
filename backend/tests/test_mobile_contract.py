"""B8 CP3 - the mobile contract, checked from the mobile app's side.

`MOBILE_MODELS` maps every field of the Flutter app's domain models (mobile/lib/features/*/domain) to the
JSON field the API returns for it; docs/api/mobile-contract.md is the readable version. Two layers:

1. The OpenAPI document (no database): every endpoint the app calls exists, every mapped field is in its
   response schema, fields the app requires are required (or documented as nullable), and every enum the
   app switches on has exactly the values of the app's Dart enum.
2. The app's flow against REAL PostgreSQL, as a department user would run it: sign in, restore the
   session, scan a QR code, open the device, search the picker, report a problem, add a photo, list "my
   tickets" and the device's tickets, open the ticket with its timeline and photo, read notifications.
   Every response is checked against the same mapping. Skipped unless TEST_DATABASE_URL is set.

A change that breaks the mobile app's parsing fails here first. The Dart side is read too: the enums and
the model fields below are compared with the Dart source in mobile/ (read only), so a change in the app
that this contract does not cover fails as well.
"""
import io
import re
from pathlib import Path

import pytest
from PIL import Image

from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API, PW

# ---- the contract ------------------------------------------------------------------------------------------
# Dart enum values (mobile/lib/features/*/domain), as the API spells them.
DART_ENUMS = {
    "DeviceStatus": {"active", "under_maintenance", "out_of_service", "decommissioned"},
    "Criticality": {"low", "medium", "high", "critical"},                       # Dart: DeviceCriticality
    "TicketPriority": {"low", "medium", "high", "critical"},
    "TicketStatus": {"open", "assigned", "in_progress", "waiting_for_parts", "resolved", "closed", "cancelled"},
    "ProblemCategory": {"Device not working", "Abnormal reading", "Physical damage", "Alarm/problem",
                        "Power issue", "Other"},                                  # the labels, as in ProblemCategoryX
}
ROLES = {"admin", "biomedical_engineer", "technician", "department_user"}
NOTIFICATION_TYPES = {"ticket_created", "ticket_assigned", "ticket_status_changed", "ticket_resolved", "device_alert"}

# Dart field -> (OpenAPI schema, JSON path, nullable in the API). "a.b" = nested object.
MOBILE_MODELS = {
    "AuthSession": {"token": ("TokenResponse", "token", False), "user": ("TokenResponse", "user", False)},
    "AuthUser": {
        "id": ("UserResponse", "id", False), "fullName": ("UserResponse", "full_name", False),
        "email": ("UserResponse", "email", False), "hospitalName": ("UserResponse", "hospital_name", False),
        "departmentName": ("UserResponse", "department_name", True),   # staff without a department: null
        "role": ("UserResponse", "role", False),
    },
    "Device": {
        "id": ("DeviceResponse", "id", False), "deviceCode": ("DeviceResponse", "device_code", False),
        "name": ("DeviceResponse", "name", False), "qrIdentifier": ("DeviceResponse", "qr_identifier", False),
        "manufacturer": ("DeviceResponse", "manufacturer_name", False), "model": ("DeviceResponse", "model_name", False),
        "category": ("DeviceResponse", "category_name", False), "department": ("DeviceResponse", "department_name", False),
        "location": ("DeviceResponse", "location", True), "status": ("DeviceResponse", "status", False),
        "criticality": ("DeviceResponse", "criticality", False),
        "installationDate": ("DeviceResponse", "installation_date", True),
        "warrantyExpiry": ("DeviceResponse", "warranty_expiry", True),
    },
    "Ticket": {
        "id": ("TicketResponse", "id", False), "number": ("TicketResponse", "number", False),
        "deviceId": ("TicketResponse", "device.id", False), "deviceName": ("TicketResponse", "device.name", False),
        "deviceCode": ("TicketResponse", "device.device_code", False),
        "category": ("TicketResponse", "category", False), "description": ("TicketResponse", "description", False),
        "priority": ("TicketResponse", "priority", False), "status": ("TicketResponse", "status", False),
        "createdAt": ("TicketResponse", "created_at", False), "resolvedAt": ("TicketResponse", "resolved_at", True),
    },
    "TicketDetail": {   # Ticket.updates / Ticket.attachments: GET /tickets/{id} only
        "updates": ("TicketDetailResponse", "timeline", False),
        "attachments": ("TicketDetailResponse", "attachments", False),
    },
    "TicketUpdate": {"status": ("TicketTimelineItem", "status", False), "message": ("TicketTimelineItem", "message", False),
                     "at": ("TicketTimelineItem", "at", False)},
    "TicketAttachment": {"id": ("AttachmentResponse", "id", False),
                         "fileName": ("AttachmentResponse", "file_name", True),   # the app always sends a name
                         "fileUrl": ("AttachmentResponse", "file_url", False)},
    "AppNotification": {
        "id": ("NotificationResponse", "id", False), "type": ("NotificationResponse", "type", True),  # null/unknown -> other
        "title": ("NotificationResponse", "title", False), "body": ("NotificationResponse", "body", True),
        "relatedTicketId": ("NotificationResponse", "related_ticket_id", True),
        "isRead": ("NotificationResponse", "is_read", False), "createdAt": ("NotificationResponse", "created_at", False),
        "readAt": ("NotificationResponse", "read_at", True),
    },
}

# Not "required" in OpenAPI (pydantic default_factory=list) but always serialized, at worst as []:
DEFAULTS_TO_EMPTY_LIST = {("TicketDetailResponse", "attachments")}

# (method, path) of every call the app's repositories make (base URL = http://host:8000/api/v1)
MOBILE_CALLS = [
    ("post", "/auth/login"), ("get", "/auth/me"), ("post", "/auth/forgot-password"),
    ("get", "/devices/qr/{qr_identifier}"), ("get", "/devices/{device_id}"), ("get", "/devices"),
    ("post", "/tickets"), ("get", "/tickets/mine"), ("get", "/devices/{device_id}/tickets"),
    ("get", "/tickets/{ticket_id}"), ("post", "/tickets/{ticket_id}/attachments"),
    ("get", "/attachments/{attachment_id}"),
    ("get", "/notifications"), ("patch", "/notifications/{notification_id}/read"), ("post", "/notifications/read-all"),
]


def _value(body, path):
    for key in path.split("."):
        assert isinstance(body, dict) and key in body, (path, body)
        body = body[key]
    return body


def _check(body, model, nullable_ok=True):
    """Every field `model` needs is present, and non-null unless the contract says it may be null."""
    for dart_field, (_schema, path, nullable) in MOBILE_MODELS[model].items():
        value = _value(body, path)
        assert value is not None or (nullable and nullable_ok), f"{model}.{dart_field} ({path}) is null"


# ---- 0. the Dart source (mobile/, read only) -------------------------------------------------------------------
MOBILE_FEATURES = Path(__file__).resolve().parents[2] / "mobile" / "lib" / "features"
DART_FILES = {"auth": "auth/domain/auth_user.dart", "device": "devices/domain/device.dart",
              "ticket": "tickets/domain/ticket.dart", "notification": "notifications/domain/notification.dart"}
# contract model -> (Dart file, Dart class)
DART_CLASSES = {"AuthSession": ("auth", "AuthSession"), "AuthUser": ("auth", "AuthUser"), "Device": ("device", "Device"),
                "Ticket": ("ticket", "Ticket"), "TicketUpdate": ("ticket", "TicketUpdate"),
                "TicketAttachment": ("ticket", "TicketAttachment"), "AppNotification": ("notification", "AppNotification")}


def _dart(key):
    path = MOBILE_FEATURES / DART_FILES[key]
    if not path.exists():
        pytest.skip(f"mobile source not present: {path}")
    return path.read_text(encoding="utf-8")


def _snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _dart_enum(source, name):
    body = re.search(rf"enum {name}\s*\{{([^}}]*)\}}", source).group(1)
    return [v.strip() for v in body.split(",") if v.strip()]


def _dart_fields(source, cls):
    start = source.index(f"class {cls} ")
    end = source.find("\nclass ", start + 1)
    body = source[start:end if end != -1 else len(source)]
    return set(re.findall(r"^\s*final\s+[\w<>?, ]+?\s+(\w+);", body, re.M))


def test_the_contract_enums_are_the_dart_enums():
    device, ticket, note = _dart("device"), _dart("ticket"), _dart("notification")
    assert {_snake(v) for v in _dart_enum(device, "DeviceStatus")} == DART_ENUMS["DeviceStatus"]
    assert set(_dart_enum(device, "DeviceCriticality")) == DART_ENUMS["Criticality"]
    assert set(_dart_enum(ticket, "TicketPriority")) == DART_ENUMS["TicketPriority"]
    assert {_snake(v) for v in _dart_enum(ticket, "TicketStatus")} == DART_ENUMS["TicketStatus"]
    labels = set(re.findall(r"ProblemCategory\.\w+ => '([^']+)'", ticket))
    assert len(_dart_enum(ticket, "ProblemCategory")) == len(labels) and labels == DART_ENUMS["ProblemCategory"]
    api_values = set(re.findall(r"^\s*\w+\('([a-z_]+)'\)", note, re.M)) - {"other"}
    assert api_values == NOTIFICATION_TYPES


def test_the_contract_maps_every_dart_field():
    """Every `final` field of the app's models is mapped (a new Dart field fails here until the contract
    says where it comes from), and no mapping names a field the app does not have."""
    mapped = {model: set(fields) for model, fields in MOBILE_MODELS.items()}
    mapped["Ticket"] |= mapped.pop("TicketDetail")
    for model, (key, cls) in DART_CLASSES.items():
        assert _dart_fields(_dart(key), cls) == mapped[model], model


# ---- 1. the OpenAPI document ---------------------------------------------------------------------------------
def test_every_mobile_call_exists(app):
    paths = app.openapi()["paths"]
    missing = [(m, p) for m, p in MOBILE_CALLS if m not in paths.get(f"{API}{p}", {})]
    assert missing == []


def test_mapped_fields_exist_and_required_ones_are_required(app):
    schemas = app.openapi()["components"]["schemas"]
    for model, fields in MOBILE_MODELS.items():
        for dart_field, (schema, path, nullable) in fields.items():
            top = path.split(".")[0]
            props = schemas[schema]["properties"]
            assert top in props, f"{model}.{dart_field}: {schema}.{top} missing"
            if not nullable:   # always in the response: required, or a list that defaults to []
                always = top in schemas[schema].get("required", []) or (schema, top) in DEFAULTS_TO_EMPTY_LIST
                assert always, f"{model}.{dart_field}: {schema}.{top} may be missing"


def test_list_defaults_are_really_lists():
    from app.schemas.ticket import TicketDetailResponse
    for schema, field in DEFAULTS_TO_EMPTY_LIST:
        assert schema == "TicketDetailResponse" and TicketDetailResponse.model_fields[field].default_factory is list


def test_enums_match_the_dart_enums(app):
    schemas = app.openapi()["components"]["schemas"]
    for name, values in DART_ENUMS.items():
        assert set(schemas[name]["enum"]) == values, name
    create = schemas["TicketCreate"]
    assert set(create["required"]) == {"device_id", "category", "description"}       # priority optional
    assert set(create["properties"]) == {"device_id", "category", "description", "priority"}
    assert set(schemas["LoginRequest"]["required"]) == {"identifier", "password"}


# ---- 2. the app's flow against PostgreSQL --------------------------------------------------------------------
def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 12), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_the_mobile_flow(client, tickets):
    t = tickets
    h, d, w = t["h"], t["d"], t["world"]

    # sign in (LoginScreen -> AuthRepository.login): {identifier, password} -> {token, user}
    r = client.post(f"{API}/auth/login", json={"identifier": w["staff"], "password": PW})
    assert r.status_code == 200, r.text
    _check(r.json(), "AuthSession")
    _check(r.json()["user"], "AuthUser", nullable_ok=False)            # a department user has a department
    assert r.json()["user"]["role"] in ROLES
    me = {"Authorization": f"Bearer {r.json()['token']}"}
    bad = client.post(f"{API}/auth/login", json={"identifier": w["staff"], "password": "wrong"})
    assert bad.status_code == 401 and set(bad.json()["error"]) >= {"code", "message"}   # -> AuthFailure(message)

    # restore a stored session (AuthRepository.restoreSession): GET /auth/me, 401 when no longer valid
    restored = client.get(f"{API}/auth/me", headers=me)
    assert restored.status_code == 200 and restored.json() == r.json()["user"]
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401

    # scan a QR code (DeviceRepository.getByQrIdentifier): GET /devices/qr/{qr}, any letter case
    icu = d["icu"]
    for scanned in (icu["qr_identifier"], icu["qr_identifier"].lower()):
        device = client.get(f"{API}/devices/qr/{scanned}", headers=me)
        assert device.status_code == 200, device.text
        _check(device.json(), "Device")
        assert device.json()["id"] == icu["id"] and device.json()["status"] in DART_ENUMS["DeviceStatus"]
    unknown = client.get(f"{API}/devices/qr/NO-SUCH-CODE", headers=me)
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "not_found"   # -> NotFoundFailure
    # another department of the same hospital: the limited view (no criticality, no dates)
    limited = client.get(f"{API}/devices/qr/{d['lab']['qr_identifier']}", headers=me).json()
    assert limited["access"] == "limited" and "criticality" not in limited
    for dart_field in ("id", "deviceCode", "name", "qrIdentifier", "manufacturer", "model", "category", "department",
                       "status"):
        assert _value(limited, MOBILE_MODELS["Device"][dart_field][1]) is not None, dart_field

    # open the device (getById) and search the picker (listDevices): name, code or department
    assert client.get(f"{API}/devices/{icu['id']}", headers=me).json() == device.json()
    for q in ("ventilator", "S-ICU", "icu"):
        page = client.get(f"{API}/devices", headers=me, params={"q": q}).json()
        assert [x["id"] for x in page["items"]] == [icu["id"]], q
        _check(page["items"][0], "Device")

    # report a problem (ReportProblemScreen -> TicketRepository.createTicket): no priority -> medium
    created = client.post(f"{API}/tickets", headers=me, json={"device_id": icu["id"], "category": "Power issue",
                                                              "description": "  The screen stays black  "})
    assert created.status_code == 201, created.text
    ticket = created.json()
    _check(ticket, "Ticket")
    assert re.fullmatch(r"TKT-[0-9A-F]{8}", ticket["number"])
    assert (ticket["category"], ticket["description"], ticket["priority"], ticket["status"]) == \
        ("Power issue", "The screen stays black", "medium", "open")
    stored = t["sql"]("SELECT problem_description FROM maintenance_tickets WHERE id = :i", i=ticket["id"])[0][0]
    assert stored == "[Power issue] The screen stays black"          # what ProblemDescription.parse reads

    # its photo (attachmentPaths -> one multipart upload per photo, field `file`)
    photo = client.post(f"{API}/tickets/{ticket['id']}/attachments", headers=me,
                        files={"file": ("IMG_0001.png", _png(), "image/png")})
    assert photo.status_code == 201, photo.text
    _check(photo.json(), "TicketAttachment", nullable_ok=False)
    image = client.get(photo.json()["file_url"], headers=me)       # an API path: base host + file_url
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"   # fileUrl needs the token
    assert client.get(photo.json()["file_url"]).status_code == 401

    # staff work on it, so the reporter gets notifications and the timeline grows
    assert client.post(f"{API}/tickets/{ticket['id']}/assignments", headers=h["eng_h1"],
                       json={"user_id": w["tech_id"]}).status_code == 201
    assert client.patch(f"{API}/tickets/{ticket['id']}/status", headers=h["tech_h1"],
                        json={"status": "in_progress"}).status_code == 200

    # my tickets (getMyTickets) and the device's tickets (getTicketsForDevice): newest first, pages of items
    other = client.post(f"{API}/tickets", headers=me, json={"device_id": icu["id"], "category": "Other",
                                                            "description": "Loose cable"}).json()
    for url in (f"{API}/tickets/mine", f"{API}/devices/{icu['id']}/tickets"):
        page = client.get(url, headers=me).json()
        assert set(page) >= {"items", "total", "page", "page_size"}
        assert [x["id"] for x in page["items"]][:2] == [other["id"], ticket["id"]], url
        for item in page["items"]:
            _check(item, "Ticket")
            assert item["status"] in DART_ENUMS["TicketStatus"] and item["priority"] in DART_ENUMS["TicketPriority"]

    # the ticket with its history and photo (getTicketById)
    detail = client.get(f"{API}/tickets/{ticket['id']}", headers=me).json()
    _check(detail, "Ticket")
    _check(detail, "TicketDetail")
    assert [u["status"] for u in detail["timeline"]] == ["open", "assigned", "in_progress"]     # oldest first
    for update in detail["timeline"]:
        _check(update, "TicketUpdate")
    assert [a["id"] for a in detail["attachments"]] == [photo.json()["id"]]
    assert w["tech"].split("@")[0] not in str(detail)                  # staff as roles for department users (Q9)

    # notifications (NotificationsScreen): newest first, then read one, then all
    inbox = client.get(f"{API}/notifications", headers=me).json()
    assert {"items", "total", "unread_count"} <= set(inbox) and inbox["unread_count"] >= 3
    for n in inbox["items"]:
        _check(n, "AppNotification")
        assert n["type"] in NOTIFICATION_TYPES
    assert {n["type"] for n in inbox["items"]} >= {"ticket_created", "ticket_assigned", "ticket_status_changed"}
    first = inbox["items"][0]
    read = client.patch(f"{API}/notifications/{first['id']}/read", headers=me).json()
    assert read["is_read"] is True and read["read_at"] is not None
    assert client.post(f"{API}/notifications/read-all", headers=me).json()["updated"] == inbox["unread_count"] - 1
    assert client.get(f"{API}/notifications", headers=me).json()["unread_count"] == 0


def test_mobile_errors_share_one_envelope(client, tickets):
    """The app turns errors into Failure(message): every error has {"error": {"code", "message"}}."""
    h, d = tickets["h"], tickets["d"]
    cases = [
        client.get(f"{API}/devices/qr/{d['icu']['qr_identifier']}"),                                         # 401
        client.get(f"{API}/devices/qr/{d['icu']['qr_identifier']}", headers=h["dept_none"]),                 # 403
        client.get(f"{API}/devices/qr/{d['h2']['qr_identifier']}", headers=h["dept_icu"]),                   # 404
        client.post(f"{API}/tickets", headers=h["dept_icu"], json={"device_id": d["icu"]["id"], "category": "Smoke",
                                                                   "description": "x"}),                     # 422
    ]
    assert [r.status_code for r in cases] == [401, 403, 404, 422]
    for r in cases:
        error = r.json()["error"]
        assert isinstance(error["code"], str) and isinstance(error["message"], str) and error["message"]
    assert cases[1].json()["error"]["code"] == "department_required"
