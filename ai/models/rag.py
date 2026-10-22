"""
RAG models - a document (a manual/SOP/etc.) and its chunks once ingested.

Per the project brief: never invent metadata. Fields here are only
populated when the ingestion pipeline (Phase AI-6) actually extracts or
is explicitly told that value - everything else stays None rather than
being guessed.
"""
from datetime import datetime
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field

DocumentType = Literal["pdf", "txt", "markdown"]


class RAGDocument(BaseModel):
    document_id: str
    document_name: str
    document_type: DocumentType
    device_category: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[datetime] = None


class RAGChunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    page: Optional[int] = None
    metadata: Dict[str, str] = Field(default_factory=dict)
