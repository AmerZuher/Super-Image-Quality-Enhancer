# AGENTS.md

Guidelines for AI coding agents (and humans) working in this repository. Read this file in full before changing anything. Keep it short and current: if you change structure, commands or conventions, update it in the same change.

## What this is

**SIQE Studio** is a self-hosted image platform: enhance (AI super-resolution and restoration), edit, organise, automate, and design and train your own models. It runs as a Docker Compose stack on the user's machine, usually for one person, often with an NVIDIA GPU (the owner's is an RTX 3090, 24 GB).

- Architecture and decisions: [docs/architecture.md](docs/architecture.md) and [docs/adr/](docs/adr/)
- Limits, error codes, fallbacks: [docs/robustness.md](docs/robustness.md)
- Product plan and UI mockups: [docs/plan/blueprint.html](docs/plan/blueprint.html)
- Current phase: **P0 foundation done; P1 (Studio and storage) next.** Workspaces other than Overview are preview pages until their phase lands.

## Map

| Path | What lives there |
|---|---|
| `backend/src/siqe/api/` | FastAPI app, routes, response schemas |
| `backend/src/siqe/core/` | Settings (`SIQE_*` env), logging, typed errors |
| `backend/src/siqe/db/` | SQLAlchemy models, session, Alembic migrations |
| `backend/src/siqe/workflows/` | Temporal workflows: deterministic orchestration only |
| `backend/src/siqe/activities/` | Temporal activities: all I/O, CPU and GPU work |
| `backend/src/siqe/jobs/` | Job rows and throttled progress reporting |
| `backend/src/siqe/workers/` | Worker processes (`siqe worker cpu|gpu`) and heartbeats |
| `backend/src/siqe/events/` | PostgreSQL LISTEN/NOTIFY publisher and WebSocket hub |
| `backend/src/siqe/ai/` | GPU discovery, OOM handling; governor, tiling and model registry from P2 |
| `backend/src/siqe/system/` | Container-aware CPU, memory and disk readings |
| `backend/src/siqe/updates/` | GitHub release checks for the Update Center |
| `frontend/src/app/` | Router, app shell, command palette, Update Center drawer |
| `frontend/src/features/` | One folder per page or workspace |
| `frontend/src/components/ui/` | Lattice design-system primitives |
| `frontend/src/lib/api/` | Generated OpenAPI types (`schema.d.ts`), client, queries |
| `frontend/e2e/` | Playwright tests; `gallery.spec.ts` captures README screenshots |
| `deploy/` | Caddyfile, Temporal config and schema script |

## Commands

```bash
make env               # create .env with a generated database password
make up                # build and run everything on CPU  →  http://localhost:8080
make up-gpu            # same, with the NVIDIA GPU
make dev-services      # only PostgreSQL + Temporal, published on localhost
make dev               # API, workers and Vite with hot reload (after dev-services)
make check             # lint + type-check + unit tests, backend and frontend (what CI runs first)
make test-integration  # API tests against a running stack
make e2e               # Playwright against a running stack
make gen-api           # regenerate frontend/openapi.json and schema.d.ts after changing an endpoint
make gallery           # refresh gallery/*.png (stack must be running)
make ops               # Temporal UI on http://localhost:8233
```

Single tests: `cd backend && uv run pytest tests/unit/test_oom.py -k halves` · `cd frontend && pnpm vitest run src/lib/format.test.ts` · `cd frontend && pnpm exec playwright test e2e/smoke.spec.ts`.

## Golden rules

Breaking one of these is a bug, even if tests pass.

1. **Workflows are deterministic.** No I/O, network, database, file access, `datetime.now()`, randomness or threads in `siqe/workflows/`. Put that work in an activity. Import activity modules inside `workflow.unsafe.imports_passed_through()`. `tests/unit/test_workflows.py` runs every workflow through Temporal's sandbox; register new workflows in `siqe.workers.runner.WORKFLOWS`.
2. **Activities are idempotent and report progress.** Use `siqe.jobs.progress.ProgressReporter` (it throttles writes and heartbeats). Write outputs to a temporary file and rename into place. Long activities must heartbeat so cancellation and crash detection work.
3. **GPU work runs only in activities on the `siqe-gpu` queue.** Never run two GPU jobs concurrently, and never call `.cuda()` from API code. Wrap GPU work in `siqe.ai.oom.run_with_halving` (P2: the governor) so out-of-memory degrades instead of crashing.
4. **Never load a full-resolution user image naively.** From P1, open images only through the imaging admission helper (header-only size check, streaming via libvips). Don't call `PIL.Image.open` or `cv2.imread` on user files.
5. **Errors are typed.** Raise `siqe.core.errors.AppError` (or a subclass) with a stable dotted `code` and a `fix` hint. Add new codes to `docs/robustness.md`. Never return ad-hoc error dicts or leak exception text from unexpected errors.
6. **Schema changes go through Alembic.** Add a new migration in `siqe/db/migrations/versions/`. Never edit a migration that has been released.
7. **The frontend only talks to the backend through the generated client.** After changing a route or schema, run `make gen-api` and commit `frontend/openapi.json` and `schema.d.ts`. CI fails on drift.
8. **No model weights in git.** Models are added by manifest (source URL, sha256, license) from P2. Commercial-safe licenses only (no CodeFormer, no non-commercial Depth Anything sizes). Load `.pth` with `weights_only=True`; prefer safetensors or ONNX.
9. **Gold means AI.** In the UI, gold (`--gold`, `variant="ai"`) marks things that run an AI model. Use cyan for everything else. Colours come from tokens in `frontend/src/styles/tokens.css`; never hard-code hex values in components. Every view must work in dark and light themes and at phone width.
10. **Status needs more than colour.** States (ok, warning, error) always pair a colour with an icon and a label.

## Definition of done

- `make check` passes; behaviour changes have tests (unit, integration or e2e).
- New settings are added to `Settings` **and** documented in `.env.example`.
- New error codes and limits are in `docs/robustness.md`.
- If the UI changed visibly, `make gallery` was run and the screenshots committed.
- `CHANGELOG.md` has an entry under "Unreleased", written for users.
- Architecture-level changes update `docs/architecture.md` and add an ADR.

## Conventions

- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`). Small and focused.
- **Python:** 3.12, Ruff (line length 110), strict mypy, async everywhere I/O happens. Blocking CPU or GPU work inside async activities goes through `asyncio.to_thread`.
- **TypeScript:** strict, Biome formatting (2 spaces, double quotes, line width 110), `@/` imports from `src/`. Server state in TanStack Query; UI-only state in Zustand.
- **Copy:** plain, specific, active voice. Buttons say what happens ("Run self-test"). Errors say what went wrong and how to fix it.
- **Dependencies:** pnpm's minimum-release-age check stays on. Don't add exclusions; pin a slightly older version instead. Prefer libraries with permissive licenses.
- **Releases:** tag `vX.Y.Z` and publish a GitHub release with user-facing notes. Those notes appear in the in-app Update Center; `release.yml` publishes the images.

## Environment notes for cloud agents

- In Claude Code on the web, `.claude/hooks/session-start.sh` installs backend and frontend dependencies at session start, so `make check` works right away. Docker targets still need a Docker daemon.
- Docker builds in sandboxed environments may need a proxy CA: the Dockerfiles accept an optional BuildKit secret `extra_ca` (never stored in the image).
- `huggingface.co` and `download.pytorch.org` may be blocked in some sandboxes; GitHub-hosted model weights still work.
- If Playwright can't download browsers, set `PW_CHROMIUM_PATH` to an installed Chromium.
