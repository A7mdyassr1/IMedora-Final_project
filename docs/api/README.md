# API Documentation

This folder will contain API contract documentation for IMedora's backend, including:

- Endpoint listings per domain (auth, users, hospitals, departments, devices, maintenance, tickets, parts, reports, risk management, quality assurance, AI assistant)
- Request/response schemas
- Authentication and authorization requirements
- Versioning strategy

Written so far:

- [`mobile-contract.md`](mobile-contract.md): what the Flutter app calls and how each response field maps to its Dart models (B8; `/ai/chat` added in B9).
- [`ai-service-contract.md`](ai-service-contract.md): the backend ↔ AI service interface behind `/ai/chat` (B9; a proposal for the AI owner).

The full, always-current endpoint reference is the backend's OpenAPI page, `/docs`, on a running server.
