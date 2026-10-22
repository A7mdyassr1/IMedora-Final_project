# IMedora AI Subsystem — Local Setup

Independent from the backend (which doesn't exist yet) and from the
database (no direct DB access - everything goes through `DataProvider`).
Works today with zero external services via `MockDataProvider`.

## 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r ai/requirements.txt
```

## 2. Configure (optional for now)

```bash
cp ai/.env.example ai/.env
```

Every setting defaults to a mock implementation, so this step isn't
required until a real LLM/embedding provider is wired up in a later
phase.

## 3. Run the tests

```bash
python -m pytest ai/tests/ -v
```

## Everyday commands

| Task | Command |
|---|---|
| Run all AI tests | `python -m pytest ai/tests/ -v` |
| Run just one phase's tests | `python -m pytest ai/tests/test_models.py -v` |
| Get a working DataProvider in a script/REPL | `from ai.services.data.factory import get_data_provider` |

## Progress

- **Phase AI-1 (done):** full `ai/` folder skeleton; 18 Pydantic models
  in `ai/models/` (status/priority/risk fields typed as `Literal`
  unions matching the real Postgres enums exactly, not invented);
  abstract interfaces `DataProvider` (34 methods), `LLMService`,
  `EmbeddingService`, `VectorStore`; env-driven `AISettings`
  (`ai/config.py`) defaulting entirely to mock. 24 tests.
- **Phase AI-2 (done):** `MockDataProvider` - a complete, deterministic
  implementation of every `DataProvider` method, backed by a
  hand-written dataset (`ai/services/data/mock_dataset.py`) consistent
  with the real database's naming (Cairo Medical Center, DEV-001
  Philips Ventilator, etc.). `get_data_provider()` factory
  (`ai/services/data/factory.py`) is the single switch point for
  mock → real backend later. 42 tests (40 provider + 2 factory),
  verified against known values, not just "doesn't crash."
- **Phase AI-3 (next):** device/maintenance/ticket/risk/qa/inventory
  tools - thin, typed wrappers around `DataProvider` that agents call.
- **Phase AI-4:** deterministic analytics tools.
- **Phase AI-5:** general medical-device knowledge base.
- **Phase AI-6:** RAG pipeline (ingestion → chunking → embeddings →
  vector store → retrieval).
- **Phase AI-7:** LLM service implementation(s).
- **Phase AI-8 – AI-12:** Chatbot, Knowledge, Analytics, Report, and
  Orchestrator agents.
- **Phase AI-13:** evaluation framework.
- **Phase AI-14:** CLI.
- **Phase AI-15:** final integration test.

**66 tests passing** (24 + 42) against the mock implementation, no
external services required.
