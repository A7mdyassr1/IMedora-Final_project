"""POST /ai/chat (B9, Master Instructions section 5; Decision 7).

The request is the mobile app's `AiRequest` (question, device it was asked from, conversation so far);
the response is its `AiReply` (`text`, `follow_ups`) plus how far to trust the answer (`source_type`,
`data_available`; team decision 2026-11-26), which the AI design requires on every answer.

Limits come from the settings (AI_QUESTION_MAX_CHARS, AI_HISTORY_MAX_MESSAGES,
AI_HISTORY_MESSAGE_MAX_CHARS) and are checked here, so an oversized request is a normal 422.
"""
import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings

SourceType = Literal["structured_data", "general_knowledge", "rag_document", "mixed", "unavailable"]


class AiChatMessage(BaseModel):
    """One earlier message of the conversation. The app's ChatMessage also has `id`, `created_at` and
    `follow_ups`: they may be sent and are ignored."""
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _length(cls, value: str) -> str:
        limit = get_settings().ai_history_message_max_chars
        if len(value) > limit:
            raise ValueError(f"at most {limit} characters")
        return value


class AiChatRequest(BaseModel):
    question: str = Field(description="The new question (not blank).")
    device_id: Optional[uuid.UUID] = Field(default=None, description="Set when the chat was opened from a device: "
                                                                     "it must be a device you can see (404 otherwise).")
    history: List[AiChatMessage] = Field(default_factory=list, description="The conversation so far, oldest first. "
                                                                           "It may end with the new question.")

    @field_validator("question")
    @classmethod
    def _question(cls, value: str) -> str:
        value = value.strip()
        limit = get_settings().ai_question_max_chars
        if not value:
            raise ValueError("must not be blank")
        if len(value) > limit:
            raise ValueError(f"at most {limit} characters")
        return value

    @field_validator("history")
    @classmethod
    def _history(cls, value: List[AiChatMessage]) -> List[AiChatMessage]:
        limit = get_settings().ai_history_max_messages
        if len(value) > limit:
            raise ValueError(f"at most {limit} messages")
        return value


class AiChatResponse(BaseModel):
    text: str = Field(description="The answer, ready to show.")
    follow_ups: List[str] = Field(description="Suggested next questions (may be empty).")
    source_type: SourceType = Field(description="Where the answer comes from: hospital data (`structured_data`), "
                                                "general device knowledge, retrieved documents, a mix, or "
                                                "`unavailable` when the needed data does not exist.")
    data_available: bool = Field(description="False when the answer had to say that the data is not available.")
