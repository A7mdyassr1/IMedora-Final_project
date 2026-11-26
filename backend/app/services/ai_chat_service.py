"""POST /ai/chat (B9): the backend's side of the AI assistant (Master Instructions 5 and 10, Decision 7).

Order of work:
1. Every signed-in role may ask (team decision 2026-11-26). A question about a device needs a
   device the caller can see: 403 `department_required` / 404 otherwise. This is checked before
   anything is sent to the AI service.
2. The AI service is off (AI_SERVICE_URL unset): 503 `ai_unavailable`.
3. A read-only token of the caller is issued (Decision 7, conditions 1 and 4). The AI service reads
   data only by calling this API back with it, so it sees exactly what the caller sees (condition 2).
   No privileged key ever reaches it (condition 3).
4. The database connection is released BEFORE waiting for the AI service. That service calls this
   API back while the chat is open, and each callback needs a pool connection. Holding one per open
   chat could exhaust the pool and stall every callback until the timeout.
5. The AI service's reply is mapped to the app's shape: `message` → `text`, plus `follow_ups`,
   `source_type` and `data_available`.

Logging (condition 5): metadata only (user, role, whether a device was given, sizes, outcome,
duration). Never the question, the history, the answer, the token or the key. Chat changes no data,
so it writes no audit row.
"""
import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.exceptions import AppError, NotFoundError
from app.core.security import create_ai_token
from app.models.user import User
from app.repositories.device_repository import DeviceRepository
from app.schemas.ai import AiChatRequest, AiChatResponse
from app.services.ai_client import AiServiceClient, AiUnavailableError

logger = logging.getLogger(__name__)


class AiChatService:
    def __init__(self, db: Session, client: Optional[AiServiceClient]):
        self.db = db
        self.client = client

    def ask(self, user: User, scope: AccessScope, req: AiChatRequest) -> AiChatResponse:
        started = time.monotonic()
        user_id, role = user.id, user.role.name
        outcome = "internal_error"
        try:
            if req.device_id is not None:                              # 1.
                scope.require_device_access()                          # 403 department_required
                if DeviceRepository(self.db).get(scope, req.device_id) is None:
                    raise NotFoundError("Device not found.")
            if self.client is None:                                    # 2.
                raise AiUnavailableError()
            token, expires_in = create_ai_token(user.id, user.password_hash)   # 3.
            payload = {
                "question": req.question,
                "device_id": str(req.device_id) if req.device_id else None,
                "history": [{"role": m.role, "content": m.text} for m in req.history],
                "caller": {"role": role},
                "backend_token": token,
                "backend_token_expires_in": expires_in,
            }
            self.db.rollback()                                         # 4. read only so far: nothing lost
            reply = self.client.chat(payload)
            outcome = "ok"
            return AiChatResponse(text=reply.message, follow_ups=reply.follow_ups,  # 5.
                                  source_type=reply.source_type, data_available=reply.data_available)
        except AppError as exc:
            outcome = exc.code
            raise
        finally:
            logger.info("AI chat user_id=%s role=%s device=%s question_chars=%s history=%s outcome=%s duration_ms=%s",
                        user_id, role, req.device_id is not None, len(req.question), len(req.history), outcome,
                        round((time.monotonic() - started) * 1000))
