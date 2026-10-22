"""
Report models for the Device Report Agent (Phase AI-11).

`ReportResult.missing_data` is not an afterthought - per the project
brief, a report must clearly say what it couldn't fill in rather than
silently omitting a section or fabricating a value.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

DEFAULT_REPORT_SECTIONS = [
    "device_profile",
    "current_status",
    "maintenance_summary",
    "maintenance_history",
    "ticket_summary",
    "risk_assessment",
    "qa_calibration",
    "parts_usage",
    "observations",
    "data_limitations",
]


class ReportRequest(BaseModel):
    device_id: str
    requested_by: Optional[str] = None
    include_sections: List[str] = Field(default_factory=lambda: list(DEFAULT_REPORT_SECTIONS))


class ReportResult(BaseModel):
    device_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sections: Dict[str, str] = Field(default_factory=dict, description="section name -> rendered content")
    missing_data: List[str] = Field(default_factory=list, description="Sections/fields that couldn't be filled.")
