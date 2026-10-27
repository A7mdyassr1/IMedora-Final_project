"""
MockDataProvider - a complete, working DataProvider implementation
backed by the static dataset in mock_dataset.py. No network calls, no
database, no backend - everything here works today.

This is what every agent/tool in the AI layer talks to until
BackendDataProvider exists. Swapping the two later should be a one-line
change wherever the provider is constructed (see ai/config.py's
`data_provider` setting) - nothing in this class's public shape should
need to change.
"""
from datetime import date, datetime
from typing import List, Optional

from ai.models.device import DeviceContext, DeviceProfile
from ai.models.inventory import InventoryContext
from ai.models.maintenance import MaintenanceEvent, MaintenanceSchedule
from ai.models.qa import QAContext
from ai.models.risk import RiskContext
from ai.models.ticket import TicketContext
from ai.services.data import mock_dataset as data
from ai.services.data.base import DataProvider


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _parse_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


class MockDataProvider(DataProvider):
    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def _hospital_name(self, hospital_id: str) -> Optional[str]:
        h = data.HOSPITALS.get(hospital_id)
        return h["name"] if h else None

    def _department_name(self, department_id: Optional[str]) -> Optional[str]:
        d = data.DEPARTMENTS.get(department_id) if department_id else None
        return d["name"] if d else None

    def _device_ids_in_department(self, department: str) -> set:
        dept_ids = {did for did, d in data.DEPARTMENTS.items() if d["name"].lower() == department.lower()}
        return {d["device_id"] for d in data.DEVICES.values() if d.get("department_id") in dept_ids}

    def _current_risk_level(self, device_id: str) -> Optional[str]:
        history = [a for a in data.RISK_ASSESSMENTS if a["device_id"] == device_id]
        if not history:
            return None
        latest = max(history, key=lambda a: a["assessed_at"])
        return latest["risk_level"]

    def _to_device_context(self, raw: dict) -> DeviceContext:
        return DeviceContext(
            device_id=raw["device_id"], device_code=raw["device_code"], name=raw["name"],
            hospital_id=raw["hospital_id"], hospital_name=self._hospital_name(raw["hospital_id"]),
            department_name=self._department_name(raw.get("department_id")), status=raw["status"],
        )

    def _to_device_profile(self, raw: dict) -> DeviceProfile:
        return DeviceProfile(
            device_id=raw["device_id"], device_code=raw["device_code"], name=raw["name"],
            serial_number=raw.get("serial_number"), qr_identifier=raw["qr_identifier"],
            manufacturer=raw.get("manufacturer"), model_name=raw.get("model_name"), category=raw.get("category"),
            status=raw["status"], criticality=raw["criticality"],
            current_risk_level=self._current_risk_level(raw["device_id"]),
            hospital_name=self._hospital_name(raw["hospital_id"]),
            department_name=self._department_name(raw.get("department_id")),
            location=data.LOCATIONS.get(raw["device_id"]),
            installation_date=_parse_date(raw.get("installation_date")),
            warranty_expiry=_parse_date(raw.get("warranty_expiry")),
            next_maintenance_due_date=_parse_date(raw.get("next_maintenance_due_date")),
            data_as_of=data.NOW.isoformat(),
        )

    def _to_maintenance_event(self, raw: dict) -> MaintenanceEvent:
        return MaintenanceEvent(
            record_id=raw["record_id"], device_id=raw["device_id"], maintenance_type=raw["maintenance_type"],
            description=raw["description"], performed_at=_parse_dt(raw["performed_at"]),
            performed_by=raw.get("performed_by"), ticket_id=raw.get("ticket_id"),
            schedule_id=raw.get("schedule_id"), parts_used=raw.get("parts_used", []),
        )

    def _to_ticket_context(self, raw: dict) -> TicketContext:
        device = data.DEVICES.get(raw["device_id"])
        return TicketContext(
            ticket_id=raw["ticket_id"], device_id=raw["device_id"],
            device_code=device["device_code"] if device else None,
            problem_description=raw["problem_description"], priority=raw["priority"], status=raw["status"],
            reported_by=raw.get("reported_by"), created_at=_parse_dt(raw["created_at"]),
            resolved_at=_parse_dt(raw.get("resolved_at")), assigned_technicians=raw.get("assigned_technicians", []),
        )

    def _to_risk_context(self, raw: dict) -> RiskContext:
        return RiskContext(
            assessment_id=raw["assessment_id"], device_id=raw["device_id"], risk_level=raw["risk_level"],
            assessed_at=_parse_dt(raw["assessed_at"]), assessed_by=raw.get("assessed_by"), notes=raw.get("notes"),
        )

    def _to_qa_context(self, raw: dict) -> QAContext:
        return QAContext(
            qa_id=raw["qa_id"], device_id=raw["device_id"], record_type=raw["record_type"], status=raw["status"],
            performed_at=_parse_dt(raw["performed_at"]), performed_by=raw.get("performed_by"),
            findings=raw.get("findings"), next_due_date=_parse_date(raw.get("next_due_date")),
        )

    def _to_inventory_context(self, raw: dict) -> InventoryContext:
        part = data.PARTS[raw["part_id"]]
        return InventoryContext(
            part_id=raw["part_id"], part_name=part["part_name"], part_number=part["part_number"],
            hospital_id=raw["hospital_id"], hospital_name=self._hospital_name(raw["hospital_id"]),
            quantity_on_hand=raw["quantity_on_hand"], reorder_threshold=raw.get("reorder_threshold"),
        )

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    def search_devices(self, query: str, limit: int = 20) -> List[DeviceContext]:
        q = query.lower()
        matches = [
            d for d in data.DEVICES.values()
            if q in d["device_code"].lower() or q in d["name"].lower() or q in (d.get("category") or "").lower()
        ]
        return [self._to_device_context(d) for d in matches[:limit]]

    def get_device(self, device_id: str) -> Optional[DeviceProfile]:
        raw = data.DEVICES.get(device_id)
        return self._to_device_profile(raw) if raw else None

    def get_device_profile(self, device_id: str) -> Optional[DeviceProfile]:
        return self.get_device(device_id)

    def get_devices_by_status(self, status: str) -> List[DeviceContext]:
        return [self._to_device_context(d) for d in data.DEVICES.values() if d["status"] == status]

    def get_devices_by_risk(self, risk_level: str) -> List[DeviceContext]:
        return [
            self._to_device_context(d) for d in data.DEVICES.values()
            if self._current_risk_level(d["device_id"]) == risk_level
        ]

    def get_devices_by_category(self, category: str) -> List[DeviceContext]:
        return [
            self._to_device_context(d) for d in data.DEVICES.values()
            if (d.get("category") or "").lower() == category.lower()
        ]

    def get_devices_by_department(self, department: str) -> List[DeviceContext]:
        dept_ids = {did for did, d in data.DEPARTMENTS.items() if d["name"].lower() == department.lower()}
        return [self._to_device_context(d) for d in data.DEVICES.values() if d.get("department_id") in dept_ids]

    def get_devices_by_location(self, location: str) -> List[DeviceContext]:
        loc = location.lower()
        device_ids = {did for did, l in data.LOCATIONS.items() if loc in l.lower()}
        return [self._to_device_context(d) for d in data.DEVICES.values() if d["device_id"] in device_ids]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    def get_maintenance_history(
        self, device_id: str, date_from: Optional[date] = None, date_to: Optional[date] = None,
        maintenance_type: Optional[str] = None, technician: Optional[str] = None,
    ) -> List[MaintenanceEvent]:
        records = [r for r in data.MAINTENANCE_RECORDS if r["device_id"] == device_id]
        if maintenance_type:
            records = [r for r in records if r["maintenance_type"] == maintenance_type]
        if technician:
            records = [r for r in records if r.get("performed_by") == technician]
        if date_from:
            records = [r for r in records if _parse_dt(r["performed_at"]).date() >= date_from]
        if date_to:
            records = [r for r in records if _parse_dt(r["performed_at"]).date() <= date_to]
        records = sorted(records, key=lambda r: r["performed_at"], reverse=True)
        return [self._to_maintenance_event(r) for r in records]

    def get_last_maintenance(self, device_id: str) -> Optional[MaintenanceEvent]:
        history = self.get_maintenance_history(device_id)
        return history[0] if history else None

    def get_next_maintenance(self, device_id: str) -> Optional[MaintenanceSchedule]:
        for s in data.MAINTENANCE_SCHEDULES.values():
            if s["device_id"] == device_id:
                return MaintenanceSchedule(**s)
        return None

    def get_preventive_maintenance_status(self, device_id: str) -> Optional[MaintenanceSchedule]:
        for s in data.MAINTENANCE_SCHEDULES.values():
            if s["device_id"] == device_id and s["maintenance_type"] == "preventive":
                return MaintenanceSchedule(**s)
        return None

    def get_corrective_maintenance_history(self, device_id: str) -> List[MaintenanceEvent]:
        return self.get_maintenance_history(device_id, maintenance_type="corrective")

    def get_maintenance_statistics(
        self, hospital_id: Optional[str] = None, department: Optional[str] = None,
        date_from: Optional[date] = None, date_to: Optional[date] = None,
    ) -> dict:
        records = data.MAINTENANCE_RECORDS
        if hospital_id:
            device_ids = {d["device_id"] for d in data.DEVICES.values() if d["hospital_id"] == hospital_id}
            records = [r for r in records if r["device_id"] in device_ids]
        if department:
            records = [r for r in records if r["device_id"] in self._device_ids_in_department(department)]
        if date_from:
            records = [r for r in records if _parse_dt(r["performed_at"]).date() >= date_from]
        if date_to:
            records = [r for r in records if _parse_dt(r["performed_at"]).date() <= date_to]
        preventive = sum(1 for r in records if r["maintenance_type"] == "preventive")
        corrective = sum(1 for r in records if r["maintenance_type"] == "corrective")
        return {"total": len(records), "preventive": preventive, "corrective": corrective}

    # ------------------------------------------------------------------
    # Tickets
    # ------------------------------------------------------------------
    def search_tickets(self, query: str, limit: int = 20) -> List[TicketContext]:
        q = query.lower()
        matches = [t for t in data.TICKETS if q in t["problem_description"].lower()]
        return [self._to_ticket_context(t) for t in matches[:limit]]

    def get_ticket(self, ticket_id: str) -> Optional[TicketContext]:
        for t in data.TICKETS:
            if t["ticket_id"] == ticket_id:
                return self._to_ticket_context(t)
        return None

    def get_device_tickets(self, device_id: str) -> List[TicketContext]:
        return [self._to_ticket_context(t) for t in data.TICKETS if t["device_id"] == device_id]

    def get_open_tickets(self, hospital_id: Optional[str] = None, department: Optional[str] = None) -> List[TicketContext]:
        open_statuses = {"open", "assigned", "in_progress", "waiting_for_parts"}
        tickets = [t for t in data.TICKETS if t["status"] in open_statuses]
        if hospital_id:
            device_ids = {d["device_id"] for d in data.DEVICES.values() if d["hospital_id"] == hospital_id}
            tickets = [t for t in tickets if t["device_id"] in device_ids]
        if department:
            dept_ids = {did for did, d in data.DEPARTMENTS.items() if d["name"].lower() == department.lower()}
            device_ids = {d["device_id"] for d in data.DEVICES.values() if d.get("department_id") in dept_ids}
            tickets = [t for t in tickets if t["device_id"] in device_ids]
        return [self._to_ticket_context(t) for t in tickets]

    def get_resolved_tickets(self, hospital_id: Optional[str] = None, date_from: Optional[date] = None) -> List[TicketContext]:
        tickets = [t for t in data.TICKETS if t["status"] in ("resolved", "closed")]
        if hospital_id:
            device_ids = {d["device_id"] for d in data.DEVICES.values() if d["hospital_id"] == hospital_id}
            tickets = [t for t in tickets if t["device_id"] in device_ids]
        if date_from:
            tickets = [t for t in tickets if t["resolved_at"] and _parse_dt(t["resolved_at"]).date() >= date_from]
        return [self._to_ticket_context(t) for t in tickets]

    def get_ticket_statistics(
        self, priority: Optional[str] = None, status: Optional[str] = None, department: Optional[str] = None,
        date_from: Optional[date] = None, date_to: Optional[date] = None,
    ) -> dict:
        tickets = data.TICKETS
        if priority:
            tickets = [t for t in tickets if t["priority"] == priority]
        if status:
            tickets = [t for t in tickets if t["status"] == status]
        if department:
            dept_devices = self._device_ids_in_department(department)
            tickets = [t for t in tickets if t["device_id"] in dept_devices]
        if date_from:
            tickets = [t for t in tickets if _parse_dt(t["created_at"]).date() >= date_from]
        if date_to:
            tickets = [t for t in tickets if _parse_dt(t["created_at"]).date() <= date_to]
        by_status: dict = {}
        for t in tickets:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        return {"total": len(tickets), "by_status": by_status}

    # ------------------------------------------------------------------
    # Risk
    # ------------------------------------------------------------------
    def get_device_risk(self, device_id: str) -> Optional[RiskContext]:
        history = [a for a in data.RISK_ASSESSMENTS if a["device_id"] == device_id]
        if not history:
            return None
        latest = max(history, key=lambda a: a["assessed_at"])
        return self._to_risk_context(latest)

    def get_risk_history(self, device_id: str) -> List[RiskContext]:
        history = sorted(
            (a for a in data.RISK_ASSESSMENTS if a["device_id"] == device_id), key=lambda a: a["assessed_at"]
        )
        return [self._to_risk_context(a) for a in history]

    def get_high_risk_devices(self) -> List[DeviceContext]:
        return self.get_devices_by_risk("high")

    def get_critical_risk_devices(self) -> List[DeviceContext]:
        return self.get_devices_by_risk("critical")

    def get_risk_statistics(self, hospital_id: Optional[str] = None) -> dict:
        devices = data.DEVICES.values()
        if hospital_id:
            devices = [d for d in devices if d["hospital_id"] == hospital_id]
        by_level: dict = {}
        for d in devices:
            level = self._current_risk_level(d["device_id"]) or "unassessed"
            by_level[level] = by_level.get(level, 0) + 1
        return by_level

    # ------------------------------------------------------------------
    # QA / Calibration
    # ------------------------------------------------------------------
    def get_device_qa_history(self, device_id: str) -> List[QAContext]:
        records = [q for q in data.QA_RECORDS if q["device_id"] == device_id]
        return [self._to_qa_context(q) for q in sorted(records, key=lambda q: q["performed_at"], reverse=True)]

    def get_calibration_history(self, device_id: str) -> List[QAContext]:
        return [q for q in self.get_device_qa_history(device_id) if q.record_type == "calibration"]

    def get_failed_qa_records(self, hospital_id: Optional[str] = None) -> List[QAContext]:
        records = [q for q in data.QA_RECORDS if q["status"] == "fail"]
        if hospital_id:
            device_ids = {d["device_id"] for d in data.DEVICES.values() if d["hospital_id"] == hospital_id}
            records = [q for q in records if q["device_id"] in device_ids]
        return [self._to_qa_context(q) for q in records]

    def get_upcoming_calibrations(self, within_days: int = 30) -> List[QAContext]:
        cutoff = data.NOW.date()
        results = []
        for q in data.QA_RECORDS:
            if q["record_type"] != "calibration" or not q.get("next_due_date"):
                continue
            due = _parse_date(q["next_due_date"])
            if due and 0 <= (due - cutoff).days <= within_days:
                results.append(self._to_qa_context(q))
        return results

    def get_qa_statistics(self, hospital_id: Optional[str] = None) -> dict:
        records = data.QA_RECORDS
        if hospital_id:
            device_ids = {d["device_id"] for d in data.DEVICES.values() if d["hospital_id"] == hospital_id}
            records = [q for q in records if q["device_id"] in device_ids]
        by_status: dict = {}
        for q in records:
            by_status[q["status"]] = by_status.get(q["status"], 0) + 1
        return {"total": len(records), "by_status": by_status}

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------
    def get_part_inventory(self, hospital_id: str, part_name: Optional[str] = None) -> List[InventoryContext]:
        rows = [r for r in data.PART_INVENTORY if r["hospital_id"] == hospital_id]
        if part_name:
            matching_ids = {
                pid for pid, p in data.PARTS.items() if part_name.lower() in p["part_name"].lower()
            }
            rows = [r for r in rows if r["part_id"] in matching_ids]
        return [self._to_inventory_context(r) for r in rows]

    def get_low_stock_parts(self, hospital_id: str) -> List[InventoryContext]:
        rows = self.get_part_inventory(hospital_id)
        return [r for r in rows if r.below_reorder_threshold]

    def get_part_usage(self, part_id: str, date_from: Optional[date] = None) -> List[MaintenanceEvent]:
        part_name = data.PARTS[part_id]["part_name"] if part_id in data.PARTS else None
        if not part_name:
            return []
        records = [r for r in data.MAINTENANCE_RECORDS if part_name in r.get("parts_used", [])]
        if date_from:
            records = [r for r in records if _parse_dt(r["performed_at"]).date() >= date_from]
        return [self._to_maintenance_event(r) for r in records]

    def get_inventory_statistics(self, hospital_id: str) -> dict:
        rows = self.get_part_inventory(hospital_id)
        return {
            "total_parts_tracked": len(rows),
            "low_stock_count": sum(1 for r in rows if r.below_reorder_threshold),
            "total_units_on_hand": sum(r.quantity_on_hand for r in rows),
        }
