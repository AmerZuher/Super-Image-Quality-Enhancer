# 0002. PostgreSQL with pgvector as the only stateful service

- **Status:** Accepted, 1 October 2026

## Context

The app stores relational data (assets, renditions, jobs), document-shaped data (edit stacks, flow and model graphs, EXIF), embeddings for similarity search, and perceptual hashes for duplicate detection. The API and several worker processes write at the same time. Temporal also needs a SQL store.

## Decision

Use **PostgreSQL 18 with the pgvector extension** for everything persistent: application tables, JSONB documents, vectors (HNSW indexes) and binary hashes (pgvector `bit` type with Hamming distance). Temporal uses two databases in the same server. Live events use PostgreSQL `LISTEN/NOTIFY`, sent in the same transaction as the change they describe.

Image files are not stored in the database; they live on the `data` volume, addressed by content hash.

## Alternatives considered

- **MongoDB:** flexible documents, but JSONB already covers them, and it would add an engine without adding a capability. Its SSPL license also conflicts with the commercial-safe preference.
- **SQLite:** zero operations, but only one writer at a time, and fragile file locking across containers. Kept as a possible future "portable mode".
- **Redis/Valkey for events:** unnecessary once Temporal replaced Celery (see ADR 0003).

## Consequences

- One stateful service to back up: the `pgdata` volume (plus the `data` volume for files).
- `max_connections` is raised to 200 and Temporal's pools are capped to leave room for the app.
- NOTIFY payloads are limited to 8,000 bytes; larger events are sent as pointers and the client refetches.
