"""
Risk tools.

`get_device_risk` returns ONLY the current (latest) assessment and
`get_risk_history` returns every assessment - they are deliberately
separate tools so an agent can never present a historical assessment as
the current risk. If a device has never been assessed, both say so
(`found: False` / empty list); nothing is ever inferred.
"""
from typing import Optional

from ai.services.data.base import DataProvider
from ai.tools.base import many, single, stats, tool


@tool("risk")
def get_device_risk(provider: DataProvider, device_id: str) -> dict:
    """The CURRENT risk assessment of a device (most recent one only)."""
    result = single(provider.get_device_risk(device_id), "risk assessment")
    result["scope"] = "current"
    return result


@tool("risk")
def get_risk_history(provider: DataProvider, device_id: str) -> dict:
    """ALL historical risk assessments of a device, oldest first."""
    result = many(provider.get_risk_history(device_id), "risk assessments")
    result["scope"] = "history"
    return result


@tool("risk")
def get_high_risk_devices(provider: DataProvider) -> dict:
    """Devices whose current risk level is 'high'."""
    return many(provider.get_high_risk_devices(), "high-risk devices")


@tool("risk")
def get_critical_risk_devices(provider: DataProvider) -> dict:
    """Devices whose current risk level is 'critical'."""
    return many(provider.get_critical_risk_devices(), "critical-risk devices")


@tool("risk")
def get_risk_statistics(provider: DataProvider, hospital_id: Optional[str] = None) -> dict:
    """Distribution of devices by current risk level ('unassessed' = never assessed)."""
    return stats(provider.get_risk_statistics(hospital_id), hospital_id=hospital_id)


TOOLS = [get_device_risk, get_risk_history, get_high_risk_devices, get_critical_risk_devices, get_risk_statistics]
