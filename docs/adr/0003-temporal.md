# 0003. Temporal for job orchestration instead of Celery

- **Status:** Accepted, 1 October 2026. Supersedes the Celery + Valkey design in plan v2.
- **Raised by:** the owner, during plan review ("what about Temporal?")

## Context

SIQE Studio's work is long-running and multi-step: tiled upscales of 8K+ images that take minutes, pipelines over thousands of images, and training runs that last hours and must pause and resume. Workers will crash, restart and run out of memory. The plan v2 design used Celery and listed the custom pieces needed to make that safe: a job state machine, heartbeats, a reaper, resume logic and progress pub/sub.

## Decision

Use **Temporal** (server 1.32, Python SDK 1.34), with PostgreSQL as its store.

- Workflows (deterministic orchestration) live in `siqe.workflows`; all I/O lives in activities in `siqe.activities`.
- Task queues: `siqe-cpu` (all workflows plus CPU activities) and `siqe-gpu` (GPU activities, at most one at a time per worker).
- The `jobs` table remains the user-facing record; each job maps to one workflow (`job-<uuid>`).
- Progress is reported through throttled database updates that double as Temporal heartbeats.

## Alternatives considered

- **Celery + Valkey:** mature and familiar, but durability, resume, cancellation and long-running orchestration would all be custom code.
- **arq, Dramatiq, Postgres queues (procrastinate):** lighter, but the same gaps as Celery for long, multi-step work.

## Consequences

- Built in: retries with backoff, heartbeat-based failure detection, cooperative cancellation, signals for pause and resume, schedules, and a per-job history in the Temporal UI.
- Workflow code must be deterministic. Enforced by convention (AGENTS.md) and by a unit test that runs every workflow through Temporal's sandbox.
- Large batches must page through child workflows and use `continue-as-new` to stay under history limits.
- Valkey is removed. Temporal adds one server container (about 100 MB RAM idle) and a one-shot schema job.
- The `temporalio/auto-setup` image is frozen at 1.23, so the stack uses `temporalio/server` plus an `admin-tools` schema job, and `siqe init` registers the namespace.
