"""The AI assistant (B9): POST /ai/chat proxies the mobile app's question to the AI service
(Master Instructions 5 and 10, Decision 7). The app never talks to the AI service or a provider
and never holds a key."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.access import scope_for
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import error_body
from app.models.user import User
from app.schemas.ai import AiChatRequest, AiChatResponse
from app.services.ai_chat_service import AiChatService
from app.services.ai_client import AiServiceClient

router = APIRouter(prefix="/ai", tags=["ai"])


def get_ai_client() -> Optional[AiServiceClient]:
    """The configured AI service, or None when AI_SERVICE_URL is unset (the assistant is off)."""
    s = get_settings()
    if not s.ai_service_url:
        return None
    return AiServiceClient(s.ai_service_url, s.ai_service_api_key.get_secret_value(), s.ai_service_timeout_seconds)


def _example(code: str, message: str) -> dict:
    return {"content": {"application/json": {"example": error_body(code, message)}}}


@router.post(
    "/chat",
    response_model=AiChatResponse,
    summary="Ask the AI assistant",
    description=(
        "Every signed-in role. The answer is built only from data you may see: the AI service reads "
        "hospital data by calling this API back with a short-lived, read-only token of yours.\n\n"
        "`device_id` (a chat opened from a device) must be a device you can see. `history` is the "
        "conversation so far. Limits are configurable (defaults: question 2,000 characters; history "
        "20 messages of 4,000 characters): over them is 422.\n\n"
        "`503 ai_unavailable`: the assistant is off, unreachable, too slow (default 30 s) or failing. "
        "`502 ai_bad_response`: it answered something unusable. Try again later in both cases."
    ),
    responses={
        404: _example("not_found", "Device not found."),
        502: _example("ai_bad_response", "The AI assistant could not answer this time. Please try again later."),
        503: _example("ai_unavailable", "The AI assistant is not available right now. Please try again later."),
    },
)
def chat(body: AiChatRequest, user: User = CurrentUser, db: Session = Depends(get_db),
         client: Optional[AiServiceClient] = Depends(get_ai_client)):
    return AiChatService(db, client).ask(user, scope_for(user), body)
