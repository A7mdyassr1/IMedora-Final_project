"""
Analytics models (Phase AI-4 produces these).

`value` is intentionally a plain number/dict - analytics TOOLS compute
it deterministically in Python; the LLM only ever explains an
AnalyticsResult that already exists, never invents or recomputes the
number itself (see the project brief's "do not ask the LLM to calculate
raw statistics from text").
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field


class AnalyticsResult(BaseModel):
    metric_name: str
    value: Union[float, int, Dict[str, Any]]
    unit: Optional[str] = None
    filters_applied: Dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
