"""QA tools: inspection/calibration/compliance history, failures, upcoming calibrations, statistics."""
from typing import Optional

from ai.services.data.base import DataProvider
from ai.tools.base import many, stats, tool


@tool("qa")
def get_device_qa_history(provider: DataProvider, device_id: str) -> dict:
    """All QA records (inspection, calibration, compliance) of a device, newest first."""
    return many(provider.get_device_qa_history(device_id), "QA records")


@tool("qa")
def get_calibration_history(provider: DataProvider, device_id: str) -> dict:
    """Calibration records of a device, newest first."""
    return many(provider.get_calibration_history(device_id), "calibration records")


@tool("qa")
def get_failed_qa_records(provider: DataProvider, hospital_id: Optional[str] = None) -> dict:
    """QA records with status 'fail'. Optional hospital filter."""
    return many(provider.get_failed_qa_records(hospital_id), "failed QA records")


@tool("qa")
def get_upcoming_calibrations(provider: DataProvider, within_days: int = 30) -> dict:
    """Calibrations due within the next N days (default 30)."""
    result = many(provider.get_upcoming_calibrations(within_days), f"calibrations due within {within_days} days")
    result["within_days"] = within_days
    return result


@tool("qa")
def get_qa_statistics(provider: DataProvider, hospital_id: Optional[str] = None) -> dict:
    """QA record counts overall and by status (pass/fail/pending)."""
    return stats(provider.get_qa_statistics(hospital_id), hospital_id=hospital_id)


TOOLS = [get_device_qa_history, get_calibration_history, get_failed_qa_records, get_upcoming_calibrations, get_qa_statistics]
