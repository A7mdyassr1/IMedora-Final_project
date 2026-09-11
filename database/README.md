# IMedora Database

Holds everything related to the database layer, independent of any specific backend framework.

## Structure

```
migrations/  # Version-controlled schema migrations
seeds/       # Seed/fixture data for local development and testing
schemas/     # Schema definitions / diagrams (source of truth once finalized)
```

## Status

**No final schema has been designed yet.** The data model will be defined once the overall architecture and domain requirements (devices, maintenance, tickets, risk, quality, AI) are agreed upon by the team. This folder currently only holds the structural placeholders.
