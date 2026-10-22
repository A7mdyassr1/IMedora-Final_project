"""
Static, deterministic mock dataset backing MockDataProvider.

Deliberately hand-written (no Faker, no randomness) so every test and
CLI session sees the exact same data every run - per the project brief:
"deterministic mock data where possible so tests are reproducible".

Naming is deliberately consistent with the real database's demo/seed
data (e.g. "Cairo Medical Center", device code "DEV-001" as a Philips
Ventilator) and the bulk data generator's manufacturer/category choices,
so anyone cross-referencing the two isn't confused by two unrelated
fictional worlds.
"""
from datetime import datetime, timezone

HOSPITALS = {
    "h1": {"name": "Cairo Medical Center"},
    "h2": {"name": "Alexandria General Hospital"},
}

DEPARTMENTS = {
    "dept-icu": {"name": "ICU", "hospital_id": "h1"},
    "dept-rad-h1": {"name": "Radiology", "hospital_id": "h1"},
    "dept-er-h1": {"name": "Emergency", "hospital_id": "h1"},
    "dept-rad-h2": {"name": "Radiology", "hospital_id": "h2"},
    "dept-cardio-h2": {"name": "Cardiology", "hospital_id": "h2"},
}

LOCATIONS = {
    "dev-001": "Main Building, Floor 2, Room 201",
    "dev-002": "Main Building, Floor 1, Room 105",
    "dev-003": "Main Building, Floor 2, Room 203",
    "dev-004": "Main Building, Floor 1, Room 110",
    "dev-005": "East Wing, Floor 1, Room 150",
    "dev-006": "East Wing, Floor 3, Room 310",
    "dev-007": "Main Building, Floor 1, Room 112",
    "dev-008": "East Wing, Floor 3, Room 305",
}

# One deterministic "now" everything else is computed relative to, so
# tests don't depend on wall-clock time.
NOW = datetime(2026, 10, 4, 9, 0, 0, tzinfo=timezone.utc)

DEVICES = {
    "dev-001": {
        "device_id": "dev-001", "device_code": "DEV-001", "name": "Philips Ventilator",
        "serial_number": "PHL-VENT-88213", "qr_identifier": "QR-H1-DEV-001",
        "manufacturer": "Philips", "model_name": "Evita V300", "category": "Ventilator",
        "status": "active", "criticality": "critical",
        "hospital_id": "h1", "department_id": "dept-icu",
        "installation_date": "2022-03-15", "warranty_expiry": "2027-03-15",
        "next_maintenance_due_date": "2026-12-01",
    },
    "dev-002": {
        "device_id": "dev-002", "device_code": "DEV-002", "name": "CT Scanner Unit",
        "serial_number": "GE-CT-44109", "qr_identifier": "QR-H1-DEV-002",
        "manufacturer": "GE Healthcare", "model_name": "Revolution CT", "category": "CT Scanner",
        "status": "active", "criticality": "high",
        "hospital_id": "h1", "department_id": "dept-rad-h1",
        "installation_date": "2023-01-10", "warranty_expiry": "2028-01-10",
        "next_maintenance_due_date": "2026-11-15",
    },
    "dev-003": {
        "device_id": "dev-003", "device_code": "DEV-003", "name": "Patient Monitor",
        "serial_number": "PHL-MON-33021", "qr_identifier": "QR-H1-DEV-003",
        "manufacturer": "Philips", "model_name": "IntelliVue MX450", "category": "Patient Monitor",
        "status": "active", "criticality": "high",
        "hospital_id": "h1", "department_id": "dept-icu",
        "installation_date": "2021-07-20", "warranty_expiry": "2026-07-20",
        "next_maintenance_due_date": "2026-10-20",
    },
    "dev-004": {
        "device_id": "dev-004", "device_code": "DEV-004", "name": "Defibrillator Unit",
        "serial_number": "MDT-DEF-12044", "qr_identifier": "QR-H1-DEV-004",
        "manufacturer": "Medtronic", "model_name": "LIFEPAK 20e", "category": "Defibrillator",
        "status": "under_maintenance", "criticality": "critical",
        "hospital_id": "h1", "department_id": "dept-er-h1",
        "installation_date": "2020-11-05", "warranty_expiry": "2025-11-05",
        "next_maintenance_due_date": "2026-10-10",
    },
    "dev-005": {
        "device_id": "dev-005", "device_code": "DEV-005", "name": "MRI Scanner",
        "serial_number": "SMS-MRI-99871", "qr_identifier": "QR-H2-DEV-005",
        "manufacturer": "Siemens Healthineers", "model_name": "MAGNETOM Sola", "category": "MRI Scanner",
        "status": "active", "criticality": "high",
        "hospital_id": "h2", "department_id": "dept-rad-h2",
        "installation_date": "2023-06-01", "warranty_expiry": "2028-06-01",
        "next_maintenance_due_date": "2027-01-15",
    },
    "dev-006": {
        "device_id": "dev-006", "device_code": "DEV-006", "name": "Infusion Pump",
        "serial_number": "MDR-INF-55302", "qr_identifier": "QR-H2-DEV-006",
        "manufacturer": "Mindray", "model_name": "Infusomat Space", "category": "Infusion Pump",
        "status": "active", "criticality": "medium",
        "hospital_id": "h2", "department_id": "dept-cardio-h2",
        "installation_date": "2024-02-14", "warranty_expiry": "2027-02-14",
        "next_maintenance_due_date": "2027-02-14",
    },
    "dev-007": {
        "device_id": "dev-007", "device_code": "DEV-007", "name": "Anesthesia Machine",
        "serial_number": "DRG-ANS-77410", "qr_identifier": "QR-H1-DEV-007",
        "manufacturer": "Draegerwerk", "model_name": "Perseus A500", "category": "Anesthesia Machine",
        "status": "out_of_service", "criticality": "critical",
        "hospital_id": "h1", "department_id": "dept-er-h1",
        "installation_date": "2019-09-01", "warranty_expiry": "2024-09-01",
        "next_maintenance_due_date": "2026-10-08",
    },
    "dev-008": {
        "device_id": "dev-008", "device_code": "DEV-008", "name": "ECG Machine",
        "serial_number": "BBR-ECG-20918", "qr_identifier": "QR-H2-DEV-008",
        "manufacturer": "B. Braun", "model_name": "CardioLab", "category": "ECG Machine",
        "status": "active", "criticality": "medium",
        "hospital_id": "h2", "department_id": "dept-cardio-h2",
        "installation_date": "2022-12-01", "warranty_expiry": "2027-12-01",
        "next_maintenance_due_date": "2027-03-01",
    },
}

MAINTENANCE_TYPES = {"preventive", "corrective"}

MAINTENANCE_RECORDS = [
    {"record_id": "mr-001", "device_id": "dev-001", "maintenance_type": "preventive",
     "description": "Routine annual calibration check", "performed_at": "2026-01-10T09:00:00+00:00",
     "performed_by": "Mostafa Hassan", "ticket_id": None, "schedule_id": "sch-001",
     "parts_used": []},
    {"record_id": "mr-002", "device_id": "dev-001", "maintenance_type": "corrective",
     "description": "Recalibrated pressure sensor and replaced tubing", "performed_at": "2026-06-20T14:30:00+00:00",
     "performed_by": "Mostafa Hassan", "ticket_id": "tkt-001", "schedule_id": None,
     "parts_used": ["Pressure Sensor Tubing"]},
    {"record_id": "mr-003", "device_id": "dev-002", "maintenance_type": "preventive",
     "description": "Routine annual calibration check", "performed_at": "2026-02-05T10:00:00+00:00",
     "performed_by": "Sara Ibrahim", "ticket_id": None, "schedule_id": "sch-002",
     "parts_used": []},
    {"record_id": "mr-004", "device_id": "dev-004", "maintenance_type": "corrective",
     "description": "Battery pack failed self-test, replacement in progress", "performed_at": "2026-09-28T11:00:00+00:00",
     "performed_by": "Mostafa Hassan", "ticket_id": "tkt-002", "schedule_id": None,
     "parts_used": ["Battery Pack"]},
    {"record_id": "mr-005", "device_id": "dev-007", "maintenance_type": "corrective",
     "description": "Diagnosed gas delivery fault, awaiting replacement part", "performed_at": "2026-09-15T08:30:00+00:00",
     "performed_by": "Sara Ibrahim", "ticket_id": "tkt-003", "schedule_id": None,
     "parts_used": []},
    {"record_id": "mr-006", "device_id": "dev-003", "maintenance_type": "preventive",
     "description": "Routine quarterly inspection", "performed_at": "2026-07-01T09:00:00+00:00",
     "performed_by": "Sara Ibrahim", "ticket_id": None, "schedule_id": "sch-003",
     "parts_used": []},
]

MAINTENANCE_SCHEDULES = {
    "sch-001": {"schedule_id": "sch-001", "device_id": "dev-001", "maintenance_type": "preventive",
                "frequency_days": 365, "next_due_date": "2027-01-10", "last_performed_date": "2026-01-10"},
    "sch-002": {"schedule_id": "sch-002", "device_id": "dev-002", "maintenance_type": "preventive",
                "frequency_days": 365, "next_due_date": "2027-02-05", "last_performed_date": "2026-02-05"},
    "sch-003": {"schedule_id": "sch-003", "device_id": "dev-003", "maintenance_type": "preventive",
                "frequency_days": 90, "next_due_date": "2026-10-20", "last_performed_date": "2026-07-01"},
}

TICKETS = [
    {"ticket_id": "tkt-001", "device_id": "dev-001", "problem_description": "Abnormal pressure reading",
     "priority": "high", "status": "resolved", "reported_by": "Ahmed Fathy",
     "created_at": "2026-06-18T08:00:00+00:00", "resolved_at": "2026-06-20T14:30:00+00:00",
     "assigned_technicians": ["Mostafa Hassan"]},
    {"ticket_id": "tkt-002", "device_id": "dev-004", "problem_description": "Battery not holding charge",
     "priority": "critical", "status": "in_progress", "reported_by": "Nour Adel",
     "created_at": "2026-09-27T07:15:00+00:00", "resolved_at": None,
     "assigned_technicians": ["Mostafa Hassan"]},
    {"ticket_id": "tkt-003", "device_id": "dev-007", "problem_description": "Gas delivery fault, machine shut down",
     "priority": "critical", "status": "waiting_for_parts", "reported_by": "Nour Adel",
     "created_at": "2026-09-14T16:00:00+00:00", "resolved_at": None,
     "assigned_technicians": ["Sara Ibrahim"]},
    {"ticket_id": "tkt-004", "device_id": "dev-002", "problem_description": "Unusual noise during scan",
     "priority": "medium", "status": "open", "reported_by": "Ahmed Fathy",
     "created_at": "2026-10-01T09:00:00+00:00", "resolved_at": None,
     "assigned_technicians": []},
]

RISK_ASSESSMENTS = [
    # device, level, date - current = most recent per device
    {"assessment_id": "ra-001", "device_id": "dev-001", "risk_level": "high",
     "assessed_at": "2025-06-01T10:00:00+00:00", "assessed_by": "Eng. Yasmin Kamal", "notes": None},
    {"assessment_id": "ra-002", "device_id": "dev-001", "risk_level": "critical",
     "assessed_at": "2026-06-21T10:00:00+00:00", "assessed_by": "Eng. Yasmin Kamal",
     "notes": "Life-support device with a recent corrective repair - elevated to critical."},
    {"assessment_id": "ra-003", "device_id": "dev-002", "risk_level": "high",
     "assessed_at": "2026-02-10T10:00:00+00:00", "assessed_by": "Eng. Yasmin Kamal", "notes": None},
    {"assessment_id": "ra-004", "device_id": "dev-003", "risk_level": "medium",
     "assessed_at": "2026-07-05T10:00:00+00:00", "assessed_by": "Eng. Yasmin Kamal", "notes": None},
    {"assessment_id": "ra-005", "device_id": "dev-004", "risk_level": "high",
     "assessed_at": "2026-09-29T10:00:00+00:00", "assessed_by": "Eng. Yasmin Kamal",
     "notes": "Currently under corrective maintenance."},
    {"assessment_id": "ra-006", "device_id": "dev-005", "risk_level": "low",
     "assessed_at": "2026-06-10T10:00:00+00:00", "assessed_by": "Eng. Yasmin Kamal", "notes": None},
    {"assessment_id": "ra-007", "device_id": "dev-006", "risk_level": "low",
     "assessed_at": "2026-03-01T10:00:00+00:00", "assessed_by": "Eng. Yasmin Kamal", "notes": None},
    {"assessment_id": "ra-008", "device_id": "dev-007", "risk_level": "critical",
     "assessed_at": "2026-09-16T10:00:00+00:00", "assessed_by": "Eng. Yasmin Kamal",
     "notes": "Out of service pending parts - treat as critical until resolved."},
    {"assessment_id": "ra-009", "device_id": "dev-008", "risk_level": "medium",
     "assessed_at": "2026-01-15T10:00:00+00:00", "assessed_by": "Eng. Yasmin Kamal", "notes": None},
]

QA_RECORDS = [
    {"qa_id": "qa-001", "device_id": "dev-001", "record_type": "calibration", "status": "pass",
     "performed_at": "2026-01-10T09:00:00+00:00", "performed_by": "Eng. Yasmin Kamal",
     "findings": "Pressure sensor within tolerance", "next_due_date": "2027-01-10"},
    {"qa_id": "qa-002", "device_id": "dev-002", "record_type": "inspection", "status": "pass",
     "performed_at": "2026-02-05T10:00:00+00:00", "performed_by": "Eng. Yasmin Kamal",
     "findings": "No issues found", "next_due_date": "2026-08-05"},
    {"qa_id": "qa-003", "device_id": "dev-004", "record_type": "calibration", "status": "fail",
     "performed_at": "2026-09-29T09:00:00+00:00", "performed_by": "Eng. Yasmin Kamal",
     "findings": "Battery self-test failed - corrective ticket raised", "next_due_date": "2026-10-15"},
    {"qa_id": "qa-004", "device_id": "dev-005", "record_type": "compliance", "status": "pass",
     "performed_at": "2026-06-10T09:00:00+00:00", "performed_by": "Eng. Yasmin Kamal",
     "findings": "Meets regulatory requirements", "next_due_date": "2027-06-10"},
    {"qa_id": "qa-005", "device_id": "dev-008", "record_type": "inspection", "status": "pending",
     "performed_at": "2026-10-02T09:00:00+00:00", "performed_by": "Eng. Yasmin Kamal",
     "findings": None, "next_due_date": None},
]

PARTS = {
    "part-sensor": {"part_id": "part-sensor", "part_name": "Pressure Sensor Tubing", "part_number": "PN-TUBING-006"},
    "part-filter": {"part_id": "part-filter", "part_name": "HEPA Filter", "part_number": "PN-FILTER-002"},
    "part-battery": {"part_id": "part-battery", "part_name": "Battery Pack", "part_number": "PN-BATT-003"},
    "part-ecg-cable": {"part_id": "part-ecg-cable", "part_name": "ECG Lead Cable", "part_number": "PN-CABLE-004"},
    "part-o2-sensor": {"part_id": "part-o2-sensor", "part_name": "Oxygen Sensor", "part_number": "PN-O2SENS-005"},
}

PART_INVENTORY = [
    {"part_id": "part-sensor", "hospital_id": "h1", "quantity_on_hand": 18, "reorder_threshold": 5},
    {"part_id": "part-filter", "hospital_id": "h1", "quantity_on_hand": 3, "reorder_threshold": 5},
    {"part_id": "part-battery", "hospital_id": "h1", "quantity_on_hand": 2, "reorder_threshold": 4},
    {"part_id": "part-ecg-cable", "hospital_id": "h2", "quantity_on_hand": 12, "reorder_threshold": 3},
    {"part_id": "part-o2-sensor", "hospital_id": "h2", "quantity_on_hand": 1, "reorder_threshold": 3},
]
