"""
Collects records through the DataProvider interface ONLY (no mock/backend
specifics), so the same analytics run on MockDataProvider today and on
BackendDataProvider later.

The interface has no "list everything" methods, so we assemble the
working set from the ones it has:
  - all devices   = union of get_devices_by_status() over every status
  - tickets       = get_device_tickets() per device (includes cancelled)
  - maintenance   = get_maintenance_history() per device

That is N+1 calls, fine for the mock and a hospital-sized dataset. If the
backend ever needs bulk endpoints, add them to DataProvider and change
only this file.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ai.models.device import DeviceContext
from ai.models.maintenance import MaintenanceEvent
from ai.models.ticket import TicketContext
from ai.services.data.base import DataProvider

DEVICE_STATUSES = ("active", "under_maintenance", "out_of_service", "decommissioned")
RISK_LEVELS = ("low", "medium", "high", "critical")


def get_all_devices(
    provider: DataProvider, hospital_id: Optional[str] = None, department: Optional[str] = None
) -> List[DeviceContext]:
    seen: Dict[str, DeviceContext] = {}
    for status in DEVICE_STATUSES:
        for dev in provider.get_devices_by_status(status):
            seen.setdefault(dev.device_id, dev)
    devices = list(seen.values())
    if hospital_id:
        devices = [d for d in devices if d.hospital_id == hospital_id]
    if department:
        devices = [d for d in devices if (d.department_name or "").lower() == department.lower()]
    return sorted(devices, key=lambda d: d.device_code)


def collect_tickets(provider: DataProvider, devices: List[DeviceContext]) -> List[TicketContext]:
    seen: Dict[str, TicketContext] = {}
    for dev in devices:
        for t in provider.get_device_tickets(dev.device_id):
            seen.setdefault(t.ticket_id, t)
    return list(seen.values())


def collect_maintenance(provider: DataProvider, devices: List[DeviceContext]) -> List[MaintenanceEvent]:
    seen: Dict[str, MaintenanceEvent] = {}
    for dev in devices:
        for m in provider.get_maintenance_history(dev.device_id):
            seen.setdefault(m.record_id, m)
    return list(seen.values())


def collect_preventive_schedules(provider: DataProvider, devices: List[DeviceContext]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for dev in devices:
        if dev.status == "decommissioned":
            continue
        schedule = provider.get_preventive_maintenance_status(dev.device_id)
        if schedule is not None:
            out[dev.device_id] = schedule
    return out


def current_risk_by_device(provider: DataProvider) -> Dict[str, str]:
    """device_id -> current risk level (devices never assessed are absent)."""
    out: Dict[str, str] = {}
    for level in RISK_LEVELS:
        for dev in provider.get_devices_by_risk(level):
            out[dev.device_id] = level
    return out


def resolve_as_of(provider: DataProvider, devices: List[DeviceContext], explicit: Optional[date] = None) -> date:
    """'Today' for overdue maths: explicit > the provider's own data_as_of > the real date."""
    if explicit:
        return explicit
    for dev in devices[:1]:
        profile = provider.get_device(dev.device_id)
        raw = getattr(profile, "data_as_of", None)
        if raw:
            try:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except ValueError:
                pass
    return date.today()
