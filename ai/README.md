# IMedora AI Service

A separate service/module for AI-driven capabilities, decoupled from the core backend so it can evolve independently (models, RAG pipelines, tool integrations, and future ML) without affecting core API stability.

## Structure

```
agents/       # Agent definitions / orchestration logic
rag/          # Retrieval-augmented generation: retrievers, indexing, knowledge base integration
prompts/      # Prompt templates used by agents and tools
tools/        # Tool definitions the agent can call (e.g. device lookup, ticket creation)
services/     # Service-layer glue (API endpoints for the AI service, if run standalone)
models/       # ML model artifacts / interfaces (future predictive maintenance)
data/         # Local data used for retrieval or evaluation (gitignored — not for real data)
evaluation/   # Evaluation scripts/datasets for agent and RAG quality
tests/        # AI service test suite
```

## Planned Capabilities

- **Conversational assistant** — help users report faults, answer device questions, retrieve device/maintenance information.
- **RAG** — retrieval over medical device documentation and maintenance history.
- **Tool calling** — structured actions such as creating tickets or pulling maintenance records.
- **Maintenance recommendations** — initial, rule-based or LLM-assisted suggestions based on history.
- **Future predictive maintenance** — machine learning models for failure prediction and anomaly detection, integrated via `models/` and `data/` without disrupting the agent/RAG layers.

## Integration

The AI service is intended to be consumed by the backend (as an internal service) and/or the frontend `ai-assistant` feature, via a well-defined API contract (to be documented in `docs/ai/`).

## Status

No agents, RAG pipelines, or ML models have been implemented yet — this is the initial scaffold only.
