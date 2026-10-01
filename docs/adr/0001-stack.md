# 0001. FastAPI backend, Vite + React SPA frontend

- **Status:** Accepted, 1 October 2026
- **Deciders:** Amer Zuher ALriahy (owner), Claude (proposal)

## Context

The platform's core work (super-resolution, restoration, segmentation, training) runs on PyTorch and ONNX Runtime, which only have first-class Python APIs. The app runs on the user's own machine, usually for one person, and its interface is canvas-heavy: live WebGL previews, node editors and deep-zoom viewers.

## Decision

- **Backend:** Python 3.12 with FastAPI, Pydantic v2 and SQLAlchemy 2 (async). One package, `siqe`, provides the API, the Temporal workers and the CLI.
- **Frontend:** a Vite + React 19 + TypeScript single-page app. Caddy serves the static build and proxies `/api`.
- **Contract:** FastAPI's OpenAPI schema is committed as `frontend/openapi.json`, and the TypeScript types are generated from it. CI fails if they drift.

## Alternatives considered

- **Node or Go API with a Python sidecar:** two backend languages and a network hop per job. Rejected.
- **Django:** synchronous-first and heavier than an API-only service needs.
- **Litestar:** comparable to FastAPI technically, but a smaller ecosystem.
- **Next.js (plan v1):** server rendering adds a Node runtime and a server/client boundary with no benefit for a local, single-user, canvas-heavy app.

## Consequences

- No Node process at runtime; the web image is about 94 MB.
- The frontend can later be wrapped as a desktop app (Tauri) without a rewrite.
- TypeScript stays on 5.9 because TypeScript 7 lacks the compiler API `openapi-typescript` uses.
