"""The backend's client of the AI service (B9, Decision 7).

The contract is `docs/api/ai-service-contract.md` (a proposal the AI owner reviews; team decision
2026-11-26). One call: `POST {AI_SERVICE_URL}/v1/chat` with the header `X-API-Key`.

Safety rules:
- **Timeout:** AI_SERVICE_TIMEOUT_SECONDS for every phase (connect, write, read).
- **No redirects:** the request carries the user's read-only token.
- **No proxy settings from the environment:** the AI service is on the internal network.
- **Size cap:** the reply is read up to MAX_REPLY_BYTES and checked field by field.
- **Errors:**
  - the AI service cannot be reached, times out or answers 5xx → 503 `ai_unavailable`
    (Decision 7: "a clean 503");
  - any other non-200 answer or an unusable reply → 502 `ai_bad_response`.
- **Nothing passes through:** the client never sees the AI service's body or error text, the API key
  or the token, and the logs record only the status code and error type.
"""
import logging
from typing import Annotated, List

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.core.exceptions import AppError
from app.schemas.ai import SourceType

logger = logging.getLogger(__name__)

CHAT_PATH = "/v1/chat"
MAX_REPLY_BYTES = 256 * 1024


class AiUnavailableError(AppError):
    status_code = 503
    code = "ai_unavailable"
    default_message = "The AI assistant is not available right now. Please try again later."


class AiBadResponseError(AppError):
    status_code = 502
    code = "ai_bad_response"
    default_message = "The AI assistant could not answer this time. Please try again later."


FollowUp = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class AiServiceReply(BaseModel):
    """What the AI service must answer: the `ai/` package's ChatResponse plus `follow_ups`."""
    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=10000)
    source_type: SourceType
    sources: List[Annotated[str, StringConstraints(max_length=500)]] = Field(default_factory=list, max_length=50)
    data_available: bool
    follow_ups: List[FollowUp] = Field(default_factory=list, max_length=5)


class AiServiceClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float, transport: httpx.BaseTransport = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport  # tests: httpx.MockTransport

    def chat(self, payload: dict) -> AiServiceReply:
        try:
            with httpx.Client(base_url=self._base_url, timeout=self._timeout, transport=self._transport,
                              follow_redirects=False, trust_env=False) as http:
                with http.stream("POST", CHAT_PATH, json=payload, headers={"X-API-Key": self._api_key}) as r:
                    status = r.status_code
                    body = b""
                    if status == 200:
                        for chunk in r.iter_bytes():
                            body += chunk
                            if len(body) > MAX_REPLY_BYTES:
                                break
        except httpx.TimeoutException as exc:
            logger.warning("AI service timed out (%s)", type(exc).__name__)
            raise AiUnavailableError()
        except httpx.HTTPError as exc:  # connection refused, DNS, protocol errors ...
            logger.warning("AI service unreachable (%s)", type(exc).__name__)
            raise AiUnavailableError()

        if status >= 500:
            logger.warning("AI service answered %s", status)
            raise AiUnavailableError()
        if status != 200:  # e.g. 401 / 403: the API key is wrong; 4xx: the contract is not met
            logger.error("AI service refused the request with status %s", status)
            raise AiBadResponseError()
        if len(body) > MAX_REPLY_BYTES:
            logger.error("AI service reply larger than %s bytes", MAX_REPLY_BYTES)
            raise AiBadResponseError()
        try:
            return AiServiceReply.model_validate_json(body)
        except ValidationError as exc:
            # Only the locations of the problems, never their values (they may echo conversation text).
            logger.error("AI service reply not usable: %s", sorted({".".join(map(str, e["loc"])) for e in exc.errors()}))
            raise AiBadResponseError()
