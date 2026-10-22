"""
Chat models for the Chatbot Agent (Phase AI-8).

`SourceType` is mandatory on every `ChatResponse` - per the project
brief, every answer must declare whether it came from real hospital
data, general device knowledge, retrieved documents, or a mix, so the
UI (and the person reading it) always knows how much to trust it.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class ChatRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SourceType(str, Enum):
    structured_data = "structured_data"  # came from DataProvider tools
    general_knowledge = "general_knowledge"  # came from the static device knowledge base
    rag_document = "rag_document"  # came from retrieved manuals/SOPs
    mixed = "mixed"
    unavailable = "unavailable"  # the needed data doesn't exist - said so, not guessed


class ChatResponse(BaseModel):
    message: str
    source_type: SourceType
    sources: List[str] = Field(
        default_factory=list, description="Tool names, document ids, or knowledge-base keys actually used."
    )
    data_available: bool = Field(
        default=True, description="False when the answer had to say 'that data isn't available' instead of answering."
    )
