"""QA models - AI-facing view of `qa_records` (inspection/calibration/compliance)."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel

QARecordType = Literal["inspection", "calibration", "compliance"]
QAStatus = Literal["pass", "fail", "pending"]


class QAContext(BaseModel):
    qa_id: str
    device_id: str
    record_type: QARecordType
    status: QAStatus
    performed_at: datetime
    performed_by: Optional[str] = None
    findings: Optional[str] = None
    next_due_date: Optional[date] = None
