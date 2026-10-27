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
| Call a tool by name | `build_registry(get_data_provider()).call("get_device", device_id="dev-001")` |

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
- **Phase AI-3 (done):** 34 tools (device 8, maintenance 6, ticket 6,
  risk 5, QA 5, inventory 4) in `ai/tools/*/`, one per `DataProvider`
  method. Every tool is wrapped by `@tool` (`ai/tools/base.py`): it
  always returns a `ToolResult` and never raises; "not found" is
  `success=True, found=False` (so an agent says "no such device" instead
  of inventing one); a real fault is `success=False` with the error.
  Current risk and risk history are separate tools. Statistics tools
  echo the filters actually applied. `ai/tools/registry.py` binds all
  tools to a provider (`build_registry(provider)`) and is the only
  thing agents will use. Also fixed the mock provider silently ignoring
  department/date filters in its statistics methods. 55 new tests.
- **Phase AI-4 (next):** deterministic analytics tools.
- **Phase AI-5:** general medical-device knowledge base.
- **Phase AI-6:** RAG pipeline (ingestion → chunking → embeddings →
  vector store → retrieval).
- **Phase AI-7:** LLM service implementation(s).
- **Phase AI-8 – AI-12:** Chatbot, Knowledge, Analytics, Report, and
  Orchestrator agents.
- **Phase AI-13:** evaluation framework.
- **Phase AI-14:** CLI.
- **Phase AI-15:** final integration test.

**121 tests passing** against the mock implementation, no external
services required.
