"""
Generates a large, realistic dataset - a small hospital GROUP, not a
single toy hospital: 3 hospitals, tens of devices each, a full year+ of
maintenance/risk/QA history, tickets, parts usage, the works.

This is separate from seed_phase1.py..seed_phase6.py on purpose: it
creates its OWN organization ("Egypt Health Group" / EHG) so it never
touches or duplicates the small deterministic demo data those scripts
create. It reuses shared lookup tables (manufacturers, device_categories,
roles, maintenance_types) if they already exist, and adds to them if not -
so this runs correctly whether or not the phase seeds ran first.

Everything here goes through the same constraints and triggers as
everywhcere else: the maintenance_parts inventory trigger, the
current_risk_level cache trigger, the resolved-ticket CHECK, the
composite-FK device/type matching - nothing is special-cased for bulk
generation. Stock is tracked in-memory (mirroring part_inventory) so we
never even attempt to oversell a part.

Run with:
    python database/seeds/generate_bulk_data.py
    python database/seeds/generate_bulk_data.py --scale 2       # ~2x the volume
    python database/seeds/generate_bulk_data.py --seed 7        # different random data

Safe to run only ONCE per database - it will refuse to run again against
a database that already has the EHG organization (use --force to add
more on top anyway, e.g. after changing --scale, though this is meant
for a single generation, not repeated additive runs).
"""
import argparse
import os
import random
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from faker import Faker

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")

ORG_NAME = "Egypt Health Group"
ORG_CODE = "EHG"

HOSPITALS = [
    ("Alexandria General Hospital", "ALEX-GEN", "Alexandria, Egypt"),
    ("Giza Specialized Medical Center", "GIZA-SPEC", "Giza, Egypt"),
    ("Mansoura University Hospital", "MANS-UNI", "Mansoura, Egypt"),
]

DEPARTMENT_NAMES = [
    "ICU", "Emergency", "Radiology", "Surgery", "Cardiology", "Laboratory",
    "Dialysis", "Neonatal ICU", "Oncology", "Orthopedics", "Physical Therapy",
]

MANUFACTURERS = [
    "Philips", "GE Healthcare", "Siemens Healthineers", "Medtronic",
    "Draegerwerk", "Mindray", "Fresenius Medical Care", "Getinge",
    "B. Braun", "Nihon Kohden",
]

CATEGORY_MODELS = {
    "Ventilator": ["Evita V300", "Puritan Bennett 980", "Servo-air", "Trilogy Evo"],
    "Patient Monitor": ["IntelliVue MX450", "CARESCAPE B650", "BeneVision N22"],
    "Defibrillator": ["LIFEPAK 20e", "HeartStart XL+", "TEC-5600"],
    "CT Scanner": ["Revolution CT", "SOMATOM go.Top", "Aquilion Prime"],
    "MRI Scanner": ["Ingenia 1.5T", "MAGNETOM Sola", "Vantage Orian"],
    "Ultrasound": ["LOGIQ E10", "Voluson E10", "Affiniti 70"],
    "Infusion Pump": ["Alaris GP", "Volumat MC Agilia", "Infusomat Space"],
    "ECG Machine": ["PageWriter TC70", "CardioLab", "ECG-1550"],
    "Anesthesia Machine": ["Perseus A500", "Aisys CS2", "FLOW-i"],
    "X-Ray Machine": ["DigitalDiagnost C90", "Discovery XR656", "Definium 8000"],
    "Dialysis Machine": ["5008S", "Prismaflex", "AK 98"],
}

PARTS_CATALOG = [
    ("Pressure Sensor", "PN-SENSOR-001", "piece"),
    ("HEPA Filter", "PN-FILTER-002", "piece"),
    ("Battery Pack", "PN-BATT-003", "piece"),
    ("ECG Lead Cable", "PN-CABLE-004", "piece"),
    ("Oxygen Sensor", "PN-O2SENS-005", "piece"),
    ("Suction Tubing", "PN-TUBING-006", "meter"),
    ("Humidifier Chamber", "PN-HUMID-007", "piece"),
    ("5A Fuse", "PN-FUSE-008", "piece"),
    ("Main Circuit Board", "PN-BOARD-009", "piece"),
    ("Blood Pressure Cuff", "PN-CUFF-010", "piece"),
    ("Temperature Probe", "PN-TEMP-011", "piece"),
    ("IV Tubing Set", "PN-IVSET-012", "piece"),
    ("Ultrasound Probe Cover", "PN-COVER-013", "box"),
    ("X-Ray Tube", "PN-XRTUBE-014", "piece"),
    ("Ventilator Bellows Kit", "PN-BELLOWS-015", "kit"),
    ("Power Supply Unit", "PN-PSU-016", "piece"),
    ("Touchscreen Display Module", "PN-SCREEN-017", "piece"),
    ("Speaker Module", "PN-SPEAKER-018", "piece"),
    ("Calibration Kit", "PN-CALKIT-019", "kit"),
    ("Filter Cartridge", "PN-CART-020", "piece"),
]

ROLE_NAMES = ["admin", "biomedical_engineer", "technician", "department_user"]

DEVICE_STATUSES = ["active"] * 85 + ["under_maintenance"] * 10 + ["out_of_service"] * 5
CRITICALITY_BY_CATEGORY = {
    "Ventilator": "critical", "Defibrillator": "critical", "Dialysis Machine": "critical",
    "Anesthesia Machine": "critical", "Patient Monitor": "high", "CT Scanner": "high",
    "MRI Scanner": "high", "Infusion Pump": "medium", "ECG Machine": "medium",
    "Ultrasound": "medium", "X-Ray Machine": "high",
}
TICKET_STATUS_WEIGHTS = [
    ("open", 20), ("assigned", 15), ("in_progress", 15),
    ("waiting_for_parts", 10), ("resolved", 25), ("closed", 10), ("cancelled", 5),
]
RISK_LEVEL_WEIGHTS = {
    "critical": [("low", 10), ("medium", 25), ("high", 35), ("critical", 30)],
    "high": [("low", 20), ("medium", 35), ("high", 30), ("critical", 15)],
    "medium": [("low", 35), ("medium", 40), ("high", 20), ("critical", 5)],
}
TICKET_PROBLEMS = [
    "Device not powering on", "Abnormal reading on display", "Unusual noise during operation",
    "Overheating alarm triggered", "Battery not holding charge", "Calibration drift detected",
    "Physical damage to casing", "Software freeze during use", "Leak detected in tubing",
    "Intermittent connectivity loss",
]


def weighted_choice(pairs):
    items, weights = zip(*pairs)
    return random.choices(items, weights=weights, k=1)[0]


def get_or_create(cur, table, name_value, extra_cols=None, extra_vals=None, name_col="name"):
    cur.execute(f"SELECT id FROM {table} WHERE {name_col} = %s", (name_value,))
    row = cur.fetchone()
    if row:
        return row[0]
    cols = [name_col] + (extra_cols or [])
    vals = [name_value] + (extra_vals or [])
    placeholders = ", ".join(["%s"] * len(vals))
    cur.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id", vals)
    return cur.fetchone()[0]


def random_datetime_since(start: datetime, end: datetime = None) -> datetime:
    end = end or datetime.now(timezone.utc)
    if start >= end:
        return end
    delta = end - start
    return start + timedelta(seconds=random.uniform(0, delta.total_seconds()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=float, default=1.0, help="Multiplier for data volume (default 1.0)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--force", action="store_true", help="Run even if EHG organization already exists")
    args = parser.parse_args()

    random.seed(args.seed)
    Faker.seed(args.seed)
    fake = Faker()

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        cur.execute("SELECT id FROM organizations WHERE code = %s", (ORG_CODE,))
        existing = cur.fetchone()
        if existing and not args.force:
            print(
                f"Organization '{ORG_CODE}' already exists (id={existing[0]}). "
                "This generator is meant to run once. Use --force to add more anyway, "
                "or drop/recreate your database to start clean."
            )
            return

        two_years_ago = datetime.now(timezone.utc) - timedelta(days=730)

        # --- organization, hospitals, departments ---------------------------
        cur.execute(
            "INSERT INTO organizations (name, code) VALUES (%s, %s) RETURNING id", (ORG_NAME, ORG_CODE)
        )
        org_id = cur.fetchone()[0]

        hospitals = []
        for name, code, address in HOSPITALS:
            cur.execute(
                "INSERT INTO hospitals (organization_id, name, code, address) VALUES (%s,%s,%s,%s) RETURNING id",
                (org_id, name, code, address),
            )
            hospitals.append({"id": cur.fetchone()[0], "code": code, "departments": [], "locations": []})
        conn.commit()

        num_departments = max(4, int(len(DEPARTMENT_NAMES) * min(args.scale, 1.0)))
        for hosp in hospitals:
            chosen_depts = random.sample(DEPARTMENT_NAMES, k=min(num_departments, len(DEPARTMENT_NAMES)))
            for dept_name in chosen_depts:
                cur.execute(
                    "INSERT INTO departments (hospital_id, name) VALUES (%s,%s) RETURNING id",
                    (hosp["id"], dept_name),
                )
                hosp["departments"].append(cur.fetchone()[0])
            for _ in range(6):
                cur.execute(
                    "INSERT INTO locations (hospital_id, building, floor, room) VALUES (%s,%s,%s,%s) RETURNING id",
                    (hosp["id"], random.choice(["Main Building", "Annex", "East Wing"]),
                     str(random.randint(1, 6)), f"{random.randint(100,499)}"),
                )
                hosp["locations"].append(cur.fetchone()[0])
        conn.commit()
        print(f"Organizations/hospitals/departments/locations created ({len(hospitals)} hospitals).")

        # --- global lookups: manufacturers, categories, models, roles, types --
        manufacturer_ids = {m: get_or_create(cur, "manufacturers", m) for m in MANUFACTURERS}
        category_ids = {c: get_or_create(cur, "device_categories", c) for c in CATEGORY_MODELS}
        conn.commit()

        model_ids = []  # list of (model_id, category_name)
        for category, models in CATEGORY_MODELS.items():
            for model_name in models:
                mfr = random.choice(MANUFACTURERS)
                cur.execute(
                    "SELECT id FROM device_models WHERE manufacturer_id = %s AND name = %s",
                    (manufacturer_ids[mfr], model_name),
                )
                row = cur.fetchone()
                if row:
                    model_ids.append((row[0], category))
                    continue
                cur.execute(
                    "INSERT INTO device_models (manufacturer_id, device_category_id, name) VALUES (%s,%s,%s) RETURNING id",
                    (manufacturer_ids[mfr], category_ids[category], model_name),
                )
                model_ids.append((cur.fetchone()[0], category))
        conn.commit()

        role_ids = {r: get_or_create(cur, "roles", r) for r in ROLE_NAMES}
        preventive_id = get_or_create(cur, "maintenance_types", "preventive")
        corrective_id = get_or_create(cur, "maintenance_types", "corrective")
        conn.commit()
        print(f"Lookups ready: {len(manufacturer_ids)} manufacturers, {len(model_ids)} device models.")

        # --- devices ------------------------------------------------------------
        devices_per_hospital = (int(50 * args.scale), int(90 * args.scale))
        all_devices = []  # dicts with id, hospital_id, criticality, installation_date
        device_counter = 0
        for hosp in hospitals:
            n_devices = random.randint(*devices_per_hospital)
            for i in range(n_devices):
                device_counter += 1
                model_id, category = random.choice(model_ids)
                criticality = CRITICALITY_BY_CATEGORY.get(category, "medium")
                installation_date = fake.date_between(start_date="-6y", end_date="-1M")
                warranty_years = random.choice([2, 3, 5])
                warranty_expiry = installation_date + timedelta(days=365 * warranty_years)
                device_code = f"{hosp['code']}-{i+1:04d}"
                qr_identifier = f"QR-{hosp['code']}-{device_counter:06d}"
                cur.execute(
                    """
                    INSERT INTO devices (organization_id, hospital_id, department_id, location_id, device_model_id,
                                          device_code, name, qr_identifier, status, criticality,
                                          installation_date, warranty_expiry)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                    """,
                    (
                        org_id, hosp["id"], random.choice(hosp["departments"]), random.choice(hosp["locations"]),
                        model_id, device_code, f"{category} - {device_code}", qr_identifier,
                        random.choice(DEVICE_STATUSES), criticality, installation_date, warranty_expiry,
                    ),
                )
                all_devices.append({
                    "id": cur.fetchone()[0], "hospital_id": hosp["id"], "org_id": org_id,
                    "criticality": criticality,
                    "installation_datetime": datetime.combine(installation_date, datetime.min.time(), tzinfo=timezone.utc),
                })
            conn.commit()
        print(f"{len(all_devices)} devices created across {len(hospitals)} hospitals.")

        # --- users ------------------------------------------------------------
        num_users = max(8, int(18 * args.scale))
        all_users = []
        for _ in range(num_users):
            hosp = random.choice(hospitals)
            role_name = random.choices(ROLE_NAMES, weights=[5, 15, 60, 20], k=1)[0]
            dept_id = random.choice(hosp["departments"]) if role_name == "department_user" else None
            full_name = fake.name()
            email = fake.unique.email()
            cur.execute(
                """
                INSERT INTO users (organization_id, hospital_id, department_id, role_id, full_name, email, password_hash)
                VALUES (%s,%s,%s,%s,%s,%s,'not-a-real-hash') RETURNING id
                """,
                (org_id, hosp["id"], dept_id, role_ids[role_name], full_name, email),
            )
            all_users.append({"id": cur.fetchone()[0], "hospital_id": hosp["id"], "role": role_name})
        conn.commit()
        technicians = [u for u in all_users if u["role"] == "technician"] or all_users
        print(f"{len(all_users)} users created ({len(technicians)} technicians).")

        # --- maintenance schedules (preventive, ~80% of devices) -----------------
        schedule_count = 0
        for device in all_devices:
            if random.random() > 0.8:
                continue
            freq = random.choice([30, 90, 180, 365])
            next_due = fake.date_between(start_date="today", end_date="+180d")
            cur.execute(
                """
                INSERT INTO maintenance_schedules (organization_id, hospital_id, device_id, maintenance_type_id,
                                                    frequency_days, next_due_date)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (org_id, device["hospital_id"], device["id"], preventive_id, freq, next_due),
            )
            schedule_count += 1
        conn.commit()
        print(f"{schedule_count} maintenance schedules created.")

        # --- tickets + assignments --------------------------------------------
        num_tickets = max(15, int(45 * args.scale))
        tickets = []
        for _ in range(num_tickets):
            device = random.choice(all_devices)
            reporter = random.choice(all_users)
            created_at = random_datetime_since(two_years_ago)
            status = weighted_choice(TICKET_STATUS_WEIGHTS)
            resolved_at = None
            if status in ("resolved", "closed"):
                resolved_at = random_datetime_since(created_at, created_at + timedelta(days=14))
            cur.execute(
                """
                INSERT INTO maintenance_tickets (organization_id, hospital_id, device_id, reported_by,
                                                  problem_description, priority, status, resolved_at, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (
                    org_id, device["hospital_id"], device["id"], reporter["id"],
                    random.choice(TICKET_PROBLEMS),
                    random.choices(["low", "medium", "high", "critical"], weights=[25, 40, 25, 10], k=1)[0],
                    status, resolved_at, created_at,
                ),
            )
            ticket_id = cur.fetchone()[0]
            tickets.append({"id": ticket_id, "device_id": device["id"], "status": status})

            if status != "open":
                tech = random.choice(technicians)
                cur.execute(
                    "INSERT INTO ticket_assignments (ticket_id, user_id, assigned_at) VALUES (%s,%s,%s)",
                    (ticket_id, tech["id"], created_at),
                )
        conn.commit()
        print(f"{len(tickets)} tickets created with assignments.")

        # --- maintenance records (per device: 0-4, some ticket/schedule linked) --
        cur.execute(
            "SELECT id, device_id, maintenance_type_id FROM maintenance_schedules WHERE organization_id = %s",
            (org_id,),
        )
        schedules_by_device = {}
        for sched_id, dev_id, mtype_id in cur.fetchall():
            schedules_by_device[dev_id] = (sched_id, mtype_id)

        resolved_tickets_by_device = {}
        for t in tickets:
            if t["status"] in ("resolved", "closed"):
                resolved_tickets_by_device.setdefault(t["device_id"], []).append(t["id"])

        record_count = 0
        all_records = []
        for device in all_devices:
            n_records = random.choices([0, 1, 2, 3, 4], weights=[10, 25, 30, 20, 15], k=1)[0]
            for _ in range(n_records):
                performed_at = random_datetime_since(device["installation_datetime"])
                performer = random.choice(technicians)
                use_ticket = device["id"] in resolved_tickets_by_device and random.random() < 0.5
                use_schedule = (not use_ticket) and device["id"] in schedules_by_device and random.random() < 0.6

                ticket_id = None
                schedule_id = None
                mtype_id = corrective_id
                description = "Routine service performed"

                if use_ticket:
                    ticket_id = random.choice(resolved_tickets_by_device[device["id"]])
                    mtype_id = corrective_id
                    description = "Repaired fault reported in ticket"
                elif use_schedule:
                    schedule_id, mtype_id = schedules_by_device[device["id"]]
                    description = "Scheduled preventive maintenance completed"

                cur.execute(
                    """
                    INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id,
                                                      ticket_id, schedule_id, performed_by, description, performed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                    """,
                    (org_id, device["hospital_id"], device["id"], mtype_id, ticket_id, schedule_id,
                     performer["id"], description, performed_at),
                )
                all_records.append({"id": cur.fetchone()[0], "hospital_id": device["hospital_id"]})
                record_count += 1
        conn.commit()
        print(f"{record_count} maintenance records created.")

        # --- parts + inventory (per hospital) + usage ---------------------------
        part_ids = {}
        for name, part_number, unit in PARTS_CATALOG:
            cur.execute("SELECT id FROM parts WHERE part_number = %s", (part_number,))
            row = cur.fetchone()
            if row:
                part_ids[name] = row[0]
                continue
            cur.execute(
                "INSERT INTO parts (name, part_number, unit) VALUES (%s,%s,%s) RETURNING id",
                (name, part_number, unit),
            )
            part_ids[name] = cur.fetchone()[0]
        conn.commit()

        stock = {}  # (hospital_id, part_id) -> quantity on hand, mirrors part_inventory
        for hosp in hospitals:
            for part_name, part_id in part_ids.items():
                qty = random.randint(10, 60)
                cur.execute(
                    """
                    INSERT INTO part_inventory (organization_id, hospital_id, part_id, quantity_on_hand, reorder_threshold)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (hospital_id, part_id) DO NOTHING
                    """,
                    (org_id, hosp["id"], part_id, qty, max(5, qty // 5)),
                )
                stock[(hosp["id"], part_id)] = qty
        conn.commit()
        print(f"{len(part_ids)} parts stocked across {len(hospitals)} hospitals.")

        usage_count = 0
        for record in all_records:
            if random.random() > 0.4:
                continue
            part_name = random.choice(list(part_ids.keys()))
            part_id = part_ids[part_name]
            key = (record["hospital_id"], part_id)
            available = stock.get(key, 0)
            if available <= 0:
                continue
            qty = min(random.randint(1, 3), available)
            cur.execute(
                "INSERT INTO maintenance_parts (maintenance_record_id, part_id, quantity) VALUES (%s,%s,%s)",
                (record["id"], part_id, qty),
            )
            stock[key] -= qty
            usage_count += 1
        conn.commit()
        print(f"{usage_count} maintenance_parts usage rows created (stock tracked, never oversold).")

        # --- risk assessments (per device, 1-3 over time) -----------------------
        risk_count = 0
        for device in all_devices:
            if random.random() > 0.8:
                continue
            n_assessments = random.randint(1, 3)
            dates = sorted(random_datetime_since(device["installation_datetime"]) for _ in range(n_assessments))
            weights = RISK_LEVEL_WEIGHTS.get(device["criticality"], RISK_LEVEL_WEIGHTS["medium"])
            assessor = random.choice([u for u in all_users if u["role"] in ("biomedical_engineer", "admin")] or all_users)
            for assessed_at in dates:
                level = weighted_choice(weights)
                cur.execute(
                    """
                    INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level, assessed_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    (org_id, device["hospital_id"], device["id"], assessor["id"], level, assessed_at),
                )
                risk_count += 1
        conn.commit()
        print(f"{risk_count} risk assessments created (devices.current_risk_level updated by trigger).")

        # --- QA records (per device, ~50% chance of 1-2) ------------------------
        qa_count = 0
        for device in all_devices:
            if random.random() > 0.5:
                continue
            for _ in range(random.randint(1, 2)):
                performed_at = random_datetime_since(device["installation_datetime"])
                record_type = random.choice(["inspection", "calibration", "compliance"])
                status = random.choices(["pass", "fail", "pending"], weights=[75, 10, 15], k=1)[0]
                next_due = (performed_at + timedelta(days=random.choice([90, 180, 365]))).date()
                performer = random.choice([u for u in all_users if u["role"] == "biomedical_engineer"] or all_users)
                cur.execute(
                    """
                    INSERT INTO qa_records (organization_id, hospital_id, device_id, performed_by, record_type,
                                             status, performed_at, next_due_date)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (org_id, device["hospital_id"], device["id"], performer["id"], record_type, status,
                     performed_at, next_due),
                )
                qa_count += 1
        conn.commit()
        print(f"{qa_count} QA records created.")

        # --- attachments, notifications, audit_logs (lighter volume) ------------
        attachment_count = 0
        for t in random.sample(tickets, k=min(len(tickets), max(5, len(tickets) // 3))):
            cur.execute(
                "INSERT INTO attachments (organization_id, hospital_id, ticket_id, uploaded_by, file_url, file_name, mime_type) "
                "SELECT organization_id, hospital_id, %s, reported_by, %s, %s, 'image/jpeg' "
                "FROM maintenance_tickets WHERE id = %s",
                (t["id"], f"https://example.com/bulk-seed/{t['id']}.jpg", "photo.jpg", t["id"]),
            )
            attachment_count += 1
        conn.commit()
        print(f"{attachment_count} attachments created.")

        notification_count = 0
        for _ in range(min(30, len(tickets))):
            t = random.choice(tickets)
            user = random.choice(all_users)
            is_read = random.random() < 0.6
            cur.execute(
                """
                INSERT INTO notifications (organization_id, user_id, related_ticket_id, title, body,
                                            notification_type, is_read, read_at)
                VALUES (%s,%s,%s,%s,%s,'ticket_assigned',%s,%s)
                """,
                (org_id, user["id"], t["id"], "Ticket update", "A ticket you're involved with was updated.",
                 is_read, datetime.now(timezone.utc) if is_read else None),
            )
            notification_count += 1
        conn.commit()
        print(f"{notification_count} notifications created.")

        audit_count = 0
        for t in random.sample(tickets, k=min(len(tickets), 40)):
            actor = random.choice(all_users)
            cur.execute(
                """
                INSERT INTO audit_logs (organization_id, user_id, table_name, record_id, action, old_values, new_values)
                VALUES (%s,%s,'maintenance_tickets',%s,'update', '{"status": "open"}'::jsonb, %s::jsonb)
                """,
                (org_id, actor["id"], t["id"], f'{{"status": "{t["status"]}"}}'),
            )
            audit_count += 1
        conn.commit()
        print(f"{audit_count} audit log rows created.")

        print("\nBulk data generation complete.")
        print(f"  Organization: {ORG_NAME} ({ORG_CODE})")
        print(f"  Hospitals: {len(hospitals)}, Devices: {len(all_devices)}, Users: {len(all_users)}")
        print(f"  Tickets: {len(tickets)}, Maintenance records: {record_count}")
        print(f"  Risk assessments: {risk_count}, QA records: {qa_count}")
        print(f"  Parts stocked: {len(part_ids)} x {len(hospitals)} hospitals, usage rows: {usage_count}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
