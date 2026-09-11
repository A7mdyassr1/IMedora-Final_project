# IMedora Tests

Cross-cutting test suites, mirroring the top-level services:

```
frontend/   # End-to-end / integration tests for the frontend application
backend/    # Integration tests for the backend API (unit tests live in backend/tests)
ai/         # Integration tests for the AI service (unit tests live in ai/tests)
```

Note: each service (`frontend/`, `backend/`, `ai/`) may also maintain its own unit tests colocated within its own directory. This top-level `tests/` folder is reserved for tests that span multiple services or verify end-to-end behavior.

No tests have been written yet, since no application features have been implemented.
