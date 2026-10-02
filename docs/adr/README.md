# Architecture decision records

One short file per decision that shapes the codebase. Add a new record (next number) when you make or reverse such a decision, and update [../architecture.md](../architecture.md) to match. Never edit an accepted record's decision; supersede it with a new one.

| # | Decision | Status |
|---|---|---|
| [0001](0001-stack.md) | FastAPI backend, Vite + React SPA frontend | Accepted |
| [0002](0002-database.md) | PostgreSQL with pgvector as the only stateful service | Accepted |
| [0003](0003-temporal.md) | Temporal for job orchestration instead of Celery | Accepted |
| [0004](0004-update-center.md) | In-app Update Center fed by GitHub releases | Accepted |
| [0005](0005-edit-documents-and-preview.md) | Edit documents rendered by WebGL in the browser and libvips on the server | Accepted |
