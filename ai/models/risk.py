"""
Risk models - AI-facing view of `risk_assessments`.

Deliberately kept as ONE shape used both for "the current risk" (the
single most recent entry) and "risk history" (a list of these) - the
orchestrator/tools must be explicit about which one they're asking for,
since conflating the two is exactly the kind of mistake the project
brief warns against ("distinguish current risk from historical").
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

RiskLevel = Literal["low", "medium", "high", "critical"]


class RiskContext(BaseModel):
    assessment_id: str
    device_id: str
    risk_level: RiskLevel
    assessed_at: datetime
    assessed_by: Optional[str] = None
    notes: Optional[str] = None
