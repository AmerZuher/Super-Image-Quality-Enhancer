#!/bin/bash
# SessionStart hook for Claude Code on the web: installs backend (uv) and frontend (pnpm)
# dependencies so `make check` (lint, type-check, unit tests) works immediately.
# Idempotent and non-interactive. Docker-based targets (make up, e2e) are not prepared here.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# Python toolchain: uv, then the Python version the backend pins (3.12).
if ! command -v uv >/dev/null 2>&1; then
  pip install --quiet --root-user-action=ignore uv
fi
uv python install 3.12 >/dev/null

# Backend dependencies, including dev tools (ruff, mypy, pytest).
(cd backend && uv sync --frozen)

# Frontend: pnpm at the version pinned in package.json, then dependencies.
PNPM_VERSION=$(sed -n 's/.*"packageManager": "pnpm@\([^"]*\)".*/\1/p' frontend/package.json)
if ! command -v pnpm >/dev/null 2>&1 || [ "$(pnpm --version)" != "${PNPM_VERSION}" ]; then
  npm install --global --silent "pnpm@${PNPM_VERSION}"
fi
(cd frontend && pnpm install --frozen-lockfile)

echo "SIQE Studio dependencies ready: backend (uv) and frontend (pnpm)."
