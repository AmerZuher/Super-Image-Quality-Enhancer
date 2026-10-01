# Robustness: limits, error codes and fallbacks

The rules every feature follows so SIQE Studio degrades instead of crashing. Design rationale is in [architecture.md](architecture.md#5-robustness-and-resource-safety). Items marked **(P0)** exist today; the rest arrive with the phase noted.

## Limits

| Setting | Default | Protects against |
|---|---|---|
| `SIQE_MAX_INPUT_MEGAPIXELS` | 250 | Decompression bombs and inputs no machine can process (P1) |
| `SIQE_GPU_VRAM_RESERVE_MB` | 1536 | Driver and fragmentation headroom on the GPU (P2) |
| Free disk before a job starts | 2 × predicted output | Half-written outputs on a full disk (P1) |
| New jobs paused below | 5% free disk (`min_free_disk_ratio`) | Filling the disk completely (P1) |
| Container memory caps | api 1 GB, worker 4 GB, worker-gpu 12 GB, db 1 GB | One process taking the whole machine down **(P0)** |
| PostgreSQL connections | 200, Temporal capped at 10 per store | Connection exhaustion **(P0)** |
| Event payload | 7,900 bytes; larger events become refetch pointers | NOTIFY's 8,000-byte limit **(P0)** |
| WebSocket queue per browser | 500 events, oldest dropped | A slow or backgrounded tab growing server memory **(P0)** |
| Progress writes | at most 4 per second per job | Fast loops flooding the database **(P0)** |
| Release notes | 20,000 characters per release | Oversized payloads in the Update Center **(P0)** |

## Error codes

Every API error is `application/problem+json` with `code`, `title`, `detail` and, where possible, `fix`.

| Code | HTTP | Meaning | Phase |
|---|---|---|---|
| `request.invalid` | 422 | Missing or malformed fields; `errors` lists them | P0 |
| `request.not_found` | 404 | No such endpoint | P0 |
| `job.not_found` | 404 | No job with that id | P0 |
| `job.already_finished` | 409 | Cancelling a job that already ended | P0 |
| `job.cancel_failed` | 409 | The job engine refused the cancellation | P0 |
| `temporal.unavailable` | 503 | The job engine can't be reached; the job is marked failed | P0 |
| `internal.error` | 500 | Unexpected; details are logged, never returned | P0 |
| `gpu.insufficient_memory` | n/a (job error) | Even the smallest work size didn't fit | P0 (core), P2 (full ladder) |
| `image.too_large` | 413 | Over `SIQE_MAX_INPUT_MEGAPIXELS` | P1 |
| `format.dimension_limit` | 422 | Output too large for the chosen format (WebP 16,383 px, JPEG 65,535 px) | P1 |
| `disk.insufficient_space` | 507 | Not enough free disk for the predicted output | P1 |
| `model.not_installed` | 409 | The model's weights aren't downloaded yet | P2 |

## Fallbacks

| When this fails | SIQE Studio does this |
|---|---|
| GPU out of memory | Free cache and retry, then halve the work size, down to a minimum **(P0 core)**; then halve tile batch and tile size, then move the job to CPU (P2) |
| No GPU or no CUDA | Runs on CPU and says so on the Overview **(P0)** |
| GPU worker down | GPU activities wait in the queue (up to 10 minutes for the self-test) and finish when it returns **(P0)** |
| Worker crash mid-job | Temporal reschedules the activity after its heartbeat times out **(P0)**; long jobs resume from their tile manifest (P2) |
| Temporal down | Job creation returns `temporal.unavailable`; browsing still works **(P0)** |
| Live event stream down | The browser reconnects with backoff and falls back to polling every 3 to 5 seconds **(P0)** |
| GitHub unreachable | The Update Center shows the last known releases and says the check failed **(P0)** |
| Model weights missing | Shows a Download button instead of failing (P2) |

## Input edge cases (P1 and P2)

| Case | Handling |
|---|---|
| EXIF rotation | Applied on import; pixels and metadata agree |
| CMYK, Adobe RGB, wide-gamut profiles | Converted to an sRGB working space via ICC |
| 16-bit images | Kept 16-bit through classic ops; models run in float |
| Alpha channel | RGB goes through the model; alpha is upscaled separately |
| Grayscale, palette, 1-bit | Normalised on import; original mode remembered for export |
| Animated GIF, WebP, APNG | Frames processed individually, or the first frame with a notice |
| HEIC and AVIF | Supported via libvips and pillow-heif |
| Truncated or corrupt files | Rejected cleanly; the asset is marked unreadable |
| Smaller than a tile or kernel | Padded, processed, cropped |
| Extreme aspect ratios | The tiler handles any shape |
| Y-channel models on RGB | Correct YCbCr conversion; chroma upscaled with Lanczos |
| NaN or out-of-range model output | Detected, clamped and flagged on the job |
| Same file uploaded twice | Recognised by hash; the existing asset is offered |
| Half-copied files in hot folders | Picked up only after the size is stable for 2 seconds |
