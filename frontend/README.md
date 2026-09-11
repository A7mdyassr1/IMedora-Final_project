# IMedora Frontend

Web application for the IMedora platform. Framework choice (React/Vue/etc.) is TBD — this structure is framework-agnostic and intended to scale with a multi-feature SaaS product.

## Structure

```
src/
├── components/   # Shared, reusable UI components (buttons, tables, modals, etc.)
├── pages/        # Top-level routed views
├── layouts/      # Page shells / layout wrappers (e.g. dashboard layout, auth layout)
├── features/     # Business features, one folder per domain (see below)
├── services/     # API client(s) and integration logic
├── hooks/        # Shared custom hooks
├── utils/        # Generic helper functions
├── types/        # Shared type definitions
├── assets/       # Static assets (images, icons, fonts)
└── config/       # App-level configuration (env access, constants)
public/           # Static public files served as-is
```

## Feature Modules

Each business domain lives in its own folder under `src/features/` so teams can work in parallel with minimal conflicts:

- `auth/` — authentication & authorization
- `devices/` — medical device management
- `maintenance/` — preventive & corrective maintenance
- `tickets/` — maintenance ticketing system
- `analytics/` — analytics & reporting dashboards
- `risk-management/` — device risk identification & assessment
- `quality-assurance/` — QA compliance & KPI tracking
- `ai-assistant/` — AI chatbot / agent UI

Each feature folder is expected to contain its own components, hooks, and services scoped to that domain once implementation begins.

## Status

No application code has been implemented yet — this is the initial scaffold only.
