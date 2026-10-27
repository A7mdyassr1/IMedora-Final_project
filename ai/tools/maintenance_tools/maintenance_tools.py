"""Maintenance tools: history, last/next maintenance, preventive status, statistics."""
from typing import Optional

from ai.services.data.base import DataProvider
from ai.tools.base import many, single, stats, tool, to_date


@tool("maintenance")
def get_maintenance_history(
    provider: DataProvider, device_id: str, date_from: Optional[str] = None, date_to: Optional[str] = None,
    maintenance_type: Optional[str] = None, technician: Optional[str] = None,
) -> dict:
    """Maintenance history of a device, newest first. Optional filters: date range, type (preventive/corrective), technician."""
    events = provider.get_maintenance_history(
        device_id, to_date(date_from), to_date(date_to), maintenance_type, technician
    )
    return many(events, "maintenance records")


@tool("maintenance")
def get_last_maintenance(provider: DataProvider, device_id: str) -> dict:
    """The most recent maintenance record of a device."""
    return single(provider.get_last_maintenance(device_id), "maintenance record")


@tool("maintenance")
def get_next_maintenance(provider: DataProvider, device_id: str) -> dict:
    """The next scheduled maintenance of a device."""
    return single(provider.get_next_maintenance(device_id), "maintenance schedule")


@tool("maintenance")
def get_preventive_maintenance_status(provider: DataProvider, device_id: str) -> dict:
    """The preventive maintenance schedule/status of a device."""
    return single(provider.get_preventive_maintenance_status(device_id), "preventive maintenance schedule")


@tool("maintenance")
def get_corrective_maintenance_history(provider: DataProvider, device_id: str) -> dict:
    """Corrective (repair) maintenance history of a device, newest first."""
    return many(provider.get_corrective_maintenance_history(device_id), "corrective maintenance records")


@tool("maintenance")
def get_maintenance_statistics(
    provider: DataProvider, hospital_id: Optional[str] = None, department: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> dict:
    """Maintenance counts (total / preventive / corrective), filterable by hospital, department, date range."""
    values = provider.get_maintenance_statistics(hospital_id, department, to_date(date_from), to_date(date_to))
    return stats(values, hospital_id=hospital_id, department=department, date_from=date_from, date_to=date_to)


TOOLS = [
    get_maintenance_history, get_last_maintenance, get_next_maintenance,
    get_preventive_maintenance_status, get_corrective_maintenance_history, get_maintenance_statistics,
]
