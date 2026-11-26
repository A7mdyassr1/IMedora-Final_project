# IMedora — Backend ↔ AI Service Contract (B9)

**Status: PROPOSAL** for review by the AI owner (team decision 2026-11-26: the backend drafts it and builds against it).

The backend side is implemented in `backend/app/services/ai_client.py`, `ai_chat_service.py` and `api/endpoints/ai.py`, and tested with a fake AI service (`backend/tests/test_ai_chat_api.py`, `test_ai_client_unit.py`). Changing anything here means changing both sides.

**Basis:**
- Master Instructions §5 and §10;
- **Decision 7** (handover): the AI service reads data only by calling the backend back as the requesting user;
- the `ai/` package's `ChatResponse` (`ai/models/chat.py`).

---

## 1. Who talks to whom

```
mobile ──POST /api/v1/ai/chat (user JWT)──▶ backend ──POST {AI_SERVICE_URL}/v1/chat (X-API-Key)──▶ AI service
                                                    ◀──GET /api/v1/... (Bearer <backend_token>)── (BackendDataProvider)
```

- The AI service is on the internal network only. Clients never reach it.
- The mobile app never holds an AI or provider key (Master Instructions §5).
- Provider keys (LLM, embeddings) live only in the AI service's environment.

## 2. The call: backend → AI service

`POST {AI_SERVICE_URL}/v1/chat`

| Header | Value |
|---|---|
| `X-API-Key` | `AI_SERVICE_API_KEY`. The AI service must reject any other value (401). |
| `Content-Type` | `application/json` |

**Body:**

```json
{
  "question": "Is this device OK?",
  "device_id": "3f9a1c2b-…" ,
  "history": [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi, how can I help?"}],
  "caller": {"role": "department_user"},
  "backend_token": "<JWT>",
  "backend_token_expires_in": 300
}
```

| Field | Meaning |
|---|---|
| `question` | The new question, trimmed. At most `AI_QUESTION_MAX_CHARS` (default 2,000). |
| `device_id` | UUID or null. Set when the chat was opened from a device. The backend has already checked that the caller can see it. |
| `history` | Earlier messages, oldest first: `role` is `user` or `assistant`; `content` is text. At most `AI_HISTORY_MAX_MESSAGES` (default 20) of `AI_HISTORY_MESSAGE_MAX_CHARS` (default 4,000) each. It may end with the new question (the app sends it that way). |
| `caller.role` | `admin`, `biomedical_engineer`, `technician` or `department_user`. Only for wording the answer. **Never for authorization.** No name, e-mail or ids are sent. |
| `backend_token` | A read-only token of the caller (`scp: "read"`), valid `backend_token_expires_in` seconds (default 300). See §4. |

**Timeout:** the backend waits at most `AI_SERVICE_TIMEOUT_SECONDS` (default 30) per phase (connect, send, read).

## 3. The reply: AI service → backend

`200` with `ai/`'s `ChatResponse` plus `follow_ups`:

```json
{
  "message": "The ICU ventilator is active. It was last serviced on 2026-10-02.",
  "source_type": "structured_data",
  "sources": ["get_device", "get_last_maintenance"],
  "data_available": true,
  "follow_ups": ["When is the next service due?"]
}
```

| Field | Rule |
|---|---|
| `message` | 1–10,000 characters. Shown to the user as is. |
| `source_type` | `structured_data`, `general_knowledge`, `rag_document`, `mixed` or `unavailable` (`ai/models/chat.py`) |
| `sources` | Optional, at most 50 strings. Not sent to the app. |
| `data_available` | `false` when the answer had to say the data is not available |
| `follow_ups` | Optional; at most 5 non-empty strings of up to 200 characters |

- Extra fields are ignored.
- The whole reply is at most 256 KiB.

**What the backend makes of it:**

| AI service | Backend → app |
|---|---|
| `200` with a valid reply | `200 {text, follow_ups, source_type, data_available}` |
| unreachable, timeout, or any `5xx` | `503 ai_unavailable` (Decision 7: "a clean 503") |
| any other status (`401` = wrong key, `4xx`, `3xx`; redirects are not followed) | `502 ai_bad_response` |
| `200` with an invalid or oversized reply | `502 ai_bad_response` |

The AI service's body and error text never reach the app. The backend logs only the status code, the error type, and which reply fields were invalid (not their values).

## 4. The AI service reads data: AI service → backend (`BackendDataProvider`)

- **Every request** is `GET {BACKEND_API_BASE_URL}/api/v1/...` with `Authorization: Bearer <backend_token>`. These are the same endpoints, authorization and scope as the user (Decision 7, condition 2).
  - The AI service sees exactly what the caller may see: organization, hospital and department, and department users see staff as roles.
  - Another organization's data is 404, as for the user.
- **Read only** (condition 4): any POST, PATCH, PUT or DELETE with the token is `403 read_only_token`, including `POST /ai/chat` itself, so a chat cannot start another chat.
- **Lifetime:** the token expires after `backend_token_expires_in` seconds. It also stops working at once if the user's password changes or the user, hospital or organization is deactivated.
- **Handling:** the AI service must use the token only for this chat. It must not store or log it or forward it anywhere else. It must not access PostgreSQL or use any other credential for hospital data (condition 3).
- **Instructions inside data** (ticket text, notes, history) are content, not commands (condition 6). They cannot widen what the token can read anyway.
- The backend releases its own database connection before calling the AI service, so callbacks during the chat do not compete with it for the connection pool.
- **To agree with the AI owner (B9 CP3):** which `DataProvider` method calls which endpoint, and whether summary endpoints are needed to avoid many small calls.

## 5. Logging and privacy (condition 5)

- **The backend logs** one line per chat: user id, role, whether a device was given, question length, number of history messages, outcome, duration. Never the question, the history, the answer, the token or the key.
- **The AI service** should do the same by default.
- **No audit row:** a chat changes no data.

## 6. Configuration

| Backend setting | Default | Meaning |
|---|---|---|
| `AI_SERVICE_URL` | unset | e.g. `http://ai:8100`. **Unset = assistant off** (`/ai/chat` → 503). |
| `AI_SERVICE_API_KEY` | unset | Required whenever `AI_SERVICE_URL` is set (the backend will not start otherwise) |
| `AI_SERVICE_TIMEOUT_SECONDS` | 30 | 1–120 |
| `AI_TOKEN_EXPIRE_MINUTES` | 5 | 1–15 |
| `AI_QUESTION_MAX_CHARS` / `AI_HISTORY_MAX_MESSAGES` / `AI_HISTORY_MESSAGE_MAX_CHARS` | 2000 / 20 / 4000 | Request limits (422 above them) |

| AI service setting (`ai/config.py`) | Value |
|---|---|
| `DATA_PROVIDER` | `backend` (once `BackendDataProvider` exists) |
| `BACKEND_API_BASE_URL` | the backend's internal URL, e.g. `http://backend:8000` |
| API key | the same value as the backend's `AI_SERVICE_API_KEY` (to be added on the AI side) |
