# 0008. Flows: documents of blocks, one child workflow per image, API keys

- **Status:** Accepted, 2 October 2026
- **Raised by:** Phase 4 (Flows). The plan promised a visual node editor, batch runs that survive failures, recipes, hot folders, a REST API with keys and a `siqe run` command, and (moved from P3) face-based album rules.

## Context

Flows chain the operations the other workspaces already have: edits from Studio, models from AI Lab, rules and albums from the Library. Runs can cover thousands of images, mix CPU and GPU steps, and must keep going when one image is broken. They should be startable from the editor, from a script and from a watched folder, and behave the same way each time. The app usually runs for one person on their own machine, but people do expose it on a home network.

## Decision

- **A flow is a JSON document** of blocks and connections, validated against a block catalog (`siqe.flows.catalog`) that also drives the editor's palette and settings forms. Problems are reported per block rather than refusing to save, so a half-built flow can be kept; only a flow without problems can run or watch a folder. The same document is the `.flow.json` file used for sharing and by `siqe run`.
- **One child workflow per image.** `FlowRunWorkflow` claims pending items with `FOR UPDATE SKIP LOCKED` a few at a time (`SIQE_FLOW_CONCURRENCY`, default 4) and runs `FlowItemWorkflow` for each, then continues-as-new every 200 images. Item rows in PostgreSQL, not workflow state, are the source of truth for progress, so the UI and the API read them directly.
- **The graph is walked in workflow code**, one activity per block. Branches are followed in order with a path key, so working files and recorded outputs have stable names and a retried activity finds its earlier result. Edit blocks reuse the Studio pipeline on libvips; AI blocks reuse the AI Lab functions on the GPU queue, where the GPU worker still runs one activity at a time.
- **Lossless working files.** Between blocks an image is a PNG that keeps 16-bit depth and transparency; only Finish blocks encode for delivery.
- **Dry runs simulate Library changes** and export to a separate folder, so trying a flow is safe.
- **Folder watching rides on Library indexing.** The indexer, after analysing, grouping duplicates and counting faces, hands newly imported images to watching flows; each flow keeps one open run that new images join, closed after a minute of quiet. Rules in If blocks therefore see tags, duplicates and faces.
- **Faces are counted, not recognised.** RetinaFace, already shipped with GFPGAN (MIT), counts faces on each preview on the GPU queue. Only the count is stored. This gives the `faces` rule for filters, smart albums and If blocks without any face database.
- **Optional API keys.** `SIQE_API_AUTH=off` (default) keeps today's behaviour for a local install. `keys` requires a key from every client: scripts send it as a bearer token, the web app signs in once and keeps it in an HttpOnly, SameSite=Strict cookie. Keys are random 256-bit tokens stored as SHA-256 hashes; the first one is made with `siqe keys create` inside the container. The check is an ASGI middleware, so the WebSocket is covered too.
- **One CLI.** `siqe` keeps its server commands and gains `flows list`, `upload` and `run`, which talk HTTP to a running app (`SIQE_URL`, `SIQE_API_KEY`).

## Alternatives considered

- **One workflow per run that loops over images:** simpler, but Temporal's history grows with every activity, one bad image needs careful handling, and parallelism is harder to cap. Child workflows isolate failures and keep histories small.
- **Compiling a flow to a single activity per image:** fewer round trips, but CPU and GPU steps can't share one worker, retries would redo every step, and the UI couldn't show progress per block.
- **Users and passwords:** heavier than this single-person app needs, and scripts need tokens anyway. Keys cover both; a reverse proxy with its own login remains an option.
- **Sessions signed by a server secret:** would need secret management and wouldn't end when a key is revoked. Storing the key itself in an HttpOnly cookie means revoking it signs every browser out.
- **A watched folder per flow, separate from the import folder:** a second mount and scanner. Reusing the import folder means images are in the Library, analysed and de-duplicated before a flow sees them.
