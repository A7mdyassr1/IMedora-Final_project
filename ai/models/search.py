"""Generic structured search result wrapper, used by search_devices/search_tickets etc."""
from typing import Literal, Optional

from pydantic import BaseModel

SearchResultType = Literal["device", "ticket", "part", "user", "document"]


class SearchResult(BaseModel):
    result_type: SearchResultType
    id: str
    title: str
    summary: Optional[str] = None
    score: Optional[float] = None
