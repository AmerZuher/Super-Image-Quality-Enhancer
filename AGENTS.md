# AGENTS.md

Guidelines for AI coding agents (and humans) working in this repository. Read this file in full before changing anything. Keep it short and current: if you change structure, commands or conventions, update it in the same change.

## What this is

**SIQE Studio** is a self-hosted image platform: enhance (AI super-resolution and restoration), edit, organise, automate, and design and train your own models. It runs as a Docker Compose stack on the user's machine, usually for one person, often with an NVIDIA GPU (the owner's is an RTX 3090, 24 GB).

- Architecture and decisions: [docs/architecture.md](docs/architecture.md) and [docs/adr/](docs/adr/)
- Limits, error codes, fallbacks: [docs/robustness.md](docs/robustness.md)
- Product plan and UI mockups: [docs/plan/blueprint.html](docs/plan/blueprint.html)
- Current phase: **P5 (Forge) done; P6 (Hardening) next; P7 (model packages, text and image to image) planned** in [docs/plan/phase7-model-packages.md](docs/plan/phase7-model-packages.md). All five workspaces are live.

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
| `backend/src/siqe/imaging/` | Admission (`io.inspect`), working space, edit document, adjustment formulas, export, GPS reading and in-place removal (`metadata`) |
| `backend/src/siqe/storage/` | Content-addressed media store on the data volume |
| `backend/src/siqe/assets/` | Asset and rendition rows, their events, and `ingest.add_file` (shared by uploads and the import folder) |
| `backend/src/siqe/ai/` | Model catalog (`manifest`), downloads (`registry`), tiling and the OOM ladder (`tiling`), memory planning (`governor`, `plan`), the run pipeline, faces, background removal, torch-free checkpoint reading (`pth`) and CLIP in numpy (`clip`); `runtime` and `archs/` need torch |
| `backend/src/siqe/library/` | Library: per-image analysis, CLIP embedder and tags, duplicates, smart-album rules (SQL and Python), search, face counts, the import folder and its schedule |
| `backend/src/siqe/forge/` | Forge: block catalog, graph checks and plan (`graph`, torch-free), code generation (`codegen`), templates, degradation (`degrade`), datasets, training settings, the trainer (`trainer`, torch) and benchmark (`publish`), rows and events (`records`) |
| `backend/src/siqe/flows/` | Flows: block catalog (`catalog`), document checks (`document`), recipes, edit operations (`ops`), run records and starting runs (`start`, also the folder trigger) |
| `backend/src/siqe/auth/` | API keys (`keys`) and the optional sign-in middleware (`middleware`, `SIQE_API_AUTH=keys`) |
| `backend/src/siqe/system/` | Container-aware CPU, memory and disk readings |
| `backend/src/siqe/updates/` | GitHub release checks for the Update Center |
| `frontend/src/app/` | Router, app shell, command palette, Update Center drawer |
| `frontend/src/features/` | One folder per page or workspace; `studio/gl/` holds the WebGL preview, `ailab/` the model library and compare viewer, `library/` the grid, filters, albums and inspector, `flows/` the editor (React Flow), runs and run dialog, `forge/` the model canvas, datasets, training charts and publishing, `access/` sign-in and API keys |
| `frontend/src/components/ui/` | Lattice design-system primitives |
| `frontend/src/lib/api/` | Generated OpenAPI types (`schema.d.ts`), client, queries |
| `frontend/e2e/` | Playwright tests; `gallery.spec.ts` captures README screenshots |
| `deploy/` | Caddyfile, Temporal config and schema script |
| `import/` | The Library's import folder in development (mounted read-only into the worker; not in git) |
| `output/` | Where flows export files in development (mounted into the API and worker; not in git) |

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

The `siqe` command also talks to a running app (`SIQE_URL`, `SIQE_API_KEY`): `siqe flows list`, `siqe upload <files>`, `siqe run <flow name or .flow.json> <files> [--dry-run] [--download DIR]`. Inside the container: `docker compose exec api siqe keys create|list|revoke`.

Single tests: `cd backend && uv run pytest tests/unit/test_tiling.py -k ladder` · `cd frontend && pnpm vitest run src/lib/format.test.ts` · `cd frontend && pnpm exec playwright test e2e/smoke.spec.ts`. `e2e/shader-parity.spec.ts` needs no running stack. PyTorch tests (`tests/unit/test_ai_torch.py`, `test_forge_torch.py`) skip without torch; run them in the `ai` image or after `uv sync --extra ai`, with `SIQE_TEST_MODELS` pointing at downloaded weights (the CLIP tokenizer test needs `bpe_simple_vocab_16e6.txt.gz` there too).

## Golden rules

Breaking one of these is a bug, even if tests pass.

1. **Workflows are deterministic.** No I/O, network, database, file access, `datetime.now()`, randomness or threads in `siqe/workflows/`. Put that work in an activity. Import activity modules inside `workflow.unsafe.imports_passed_through()`. `tests/unit/test_workflows.py` runs every workflow through Temporal's sandbox; register new workflows in `siqe.workers.runner.WORKFLOWS`.
2. **Activities are idempotent and report progress.** Use `siqe.jobs.progress.ProgressReporter` (it throttles writes and heartbeats). Write outputs to a temporary file and rename into place. Long activities must heartbeat so cancellation and crash detection work.
3. **GPU work runs only in activities on the `siqe-gpu` queue.** Never run two GPU jobs concurrently, and never call `.cuda()` from API code. Run image models through `siqe.ai.tiling.run_tiled` (or `run_with_halving` for other GPU work) so out-of-memory degrades instead of crashing. Import torch only inside GPU activities or `siqe.ai.runtime`/`archs`: the CPU worker and API images have no torch.
4. **Never load a full-resolution user image naively.** Check user files with `siqe.imaging.io.inspect` (header only) and open them with `siqe.imaging.io.open_image` (libvips, streamed). Don't call `PIL.Image.open` or `cv2.imread` on user files.
5. **Errors are typed.** Raise `siqe.core.errors.AppError` (or a subclass) with a stable dotted `code` and a `fix` hint. Add new codes to `docs/robustness.md`. Never return ad-hoc error dicts or leak exception text from unexpected errors.
6. **Schema changes go through Alembic.** Add a new migration in `siqe/db/migrations/versions/`. Never edit a migration that has been released.
7. **The frontend only talks to the backend through the generated client.** After changing a route or schema, run `make gen-api` and commit `frontend/openapi.json` and `schema.d.ts`. CI fails on drift. The one exception is the upload in `features/studio/uploads.ts`, which uses XHR for progress but takes its path and types from the schema.
8. **Edit formulas live in three places that must agree:** `siqe/imaging/ops.py`, `features/studio/gl/glsl.ts` and `gl/reference.ts`. After changing one, change the others and run `uv run python -m siqe.imaging.parity` to regenerate the shared fixture; the backend, Vitest and Playwright parity tests check all three (ADR 0005).
9. **Library indexing stays in the background.** New ways of adding images must wake the indexer (`siqe.workflows.assets.wake_indexer` or `siqe.library.trigger.request_index`). If you change how images are measured, bump `siqe.library.analysis.ANALYSIS_VERSION` so existing images are re-analysed. Never delete images directly from Library features: move them to quarantine.
10. **Flow blocks come from the catalog.** A new block is a `NodeSpec` in `siqe.flows.catalog` (params validated there, which also drives the editor's form) plus its handling in `siqe.flows.ops` (edits) or `siqe.activities.flows` (conditions, AI, finishes). Finish blocks must record their output per step (`_record`) so a retried activity never exports or saves twice, and must honour dry runs. Flow If blocks and smart albums share `siqe.library.rules`: a new rule field needs both `compile_rule` (SQL) and `matches_rule` (Python), and the frontend's `rules.ts`.
11. **No model weights in git.** Models are added to `siqe.ai.manifest` with URL, size, sha256 and license (ADR 0006). Commercial-safe licenses only (MIT, BSD-3-Clause, Apache-2.0; no CodeFormer, no non-commercial Depth Anything sizes). The one planned exception (P7, ADR 0010): a package with a personal-use licence, such as Qwen-Image-2.1, may be offered only as opt-in, never installed by default, installed only after the user accepts its licence in the app, and labelled "Personal use only" wherever it is used. Load `.pth` with `weights_only=True` (or, without torch, `siqe.ai.pth`); prefer safetensors or ONNX.
12. **Gold means AI.** In the UI, gold (`--gold`, `variant="ai"`) marks things that run an AI model. Use cyan for everything else. Colours come from tokens in `frontend/src/styles/tokens.css`; never hard-code hex values in components. Every view must work in dark and light themes and at phone width.
13. **Status needs more than colour.** States (ok, warning, error) always pair a colour with an icon and a label.
14. **Forge's checker, models and code agree.** `siqe.forge.graph.analyze` (plain Python) is the only source of shapes and of the plan; `GraphNet` (`ai/archs/forge.py`) and `siqe.forge.codegen` both build from that plan with the same module names, so weights load into either. A new block needs its spec in `siqe.forge.catalog`, its shape and cost in `graph.py`, its module in `ai/archs/forge_blocks.py` and its constructor in `codegen`; `tests/unit/test_forge_torch.py` checks that the generated code and `GraphNet` give identical output. Training stays in chunks on the GPU queue and must save a checkpoint when cancelled.

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
