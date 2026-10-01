# SIQE Studio backend

Python package `siqe`: the FastAPI service, the Temporal workers and the `siqe` CLI. See the root [README](../README.md) and [docs/architecture.md](../docs/architecture.md) for the full picture.

```bash
uv sync                       # API + dev tools
uv sync --extra ai            # adds PyTorch for the GPU worker
uv run pytest                 # unit tests
uv run pytest -m integration  # needs `make up` running
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

| Command | What it does |
|---|---|
| `siqe init` | Applies database migrations and registers the Temporal namespace (idempotent) |
| `siqe api` | Runs the HTTP API on port 8000 |
| `siqe worker cpu` / `siqe worker gpu` | Runs a Temporal worker for the CPU or GPU task queue |
| `siqe openapi` | Prints the OpenAPI schema (used to generate the frontend client) |
| `siqe version` | Prints the version |
