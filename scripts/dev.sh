#!/usr/bin/env bash
# Runs the API, both workers and the Vite dev server locally with hot reload.
# Infrastructure (PostgreSQL, Temporal) must be up: `make dev-services`.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
[ -f .env ] && source .env
set +a

export SIQE_DATABASE_URL="postgresql+asyncpg://siqe:${POSTGRES_PASSWORD}@127.0.0.1:5432/siqe"
export SIQE_TEMPORAL_ADDRESS="127.0.0.1:7233"
export SIQE_DATA_DIR="${SIQE_DATA_DIR:-$PWD/data}"
export SIQE_IMPORT_DIR="${SIQE_IMPORT_DIR:-$PWD/import}"
export SIQE_ENVIRONMENT=development
export SIQE_LOG_JSON=false

pids=()
cleanup() {
  trap - INT TERM EXIT
  kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(cd backend && uv run siqe init)
(cd backend && uv run siqe api --reload --host 127.0.0.1) & pids+=($!)
(cd backend && uv run siqe worker cpu) & pids+=($!)
(cd backend && uv run siqe worker gpu) & pids+=($!)
(cd frontend && pnpm dev) & pids+=($!)

echo "API http://127.0.0.1:8000/api/docs  ·  App http://localhost:5173  ·  Ctrl+C stops everything"
wait -n
