# Robustness: limits, error codes and fallbacks

The rules every feature follows so SIQE Studio degrades instead of crashing. Design rationale is in [architecture.md](architecture.md#5-robustness-and-resource-safety). Items marked **(P0)**, **(P1)** or **(P2)** exist today; the rest arrive with the phase noted.

## Limits

| Setting | Default | Protects against |
|---|---|---|
| `SIQE_MAX_INPUT_MEGAPIXELS` | 250 | Decompression bombs and inputs no machine can process; checked from the header before any pixel is decoded **(P1)** |
| `SIQE_MAX_UPLOAD_MB` | 2048 | One upload filling the data volume; uploads stream to disk, never into memory **(P1)** |
| `SIQE_GPU_VRAM_RESERVE_MB` | 1536 | Driver and fragmentation headroom on the GPU; tile and batch sizes are chosen to leave it free **(P2)** |
| `SIQE_MAX_OUTPUT_MEGAPIXELS` | 1000 | AI results too large to store or export; 8K ×4 (531 MP) fits **(P2)** |
| AI result assembly | On disk (memory-mapped), never in RAM | A 500-megapixel result needing gigabytes of memory **(P2)** |
| One model loaded on the GPU | The GPU worker runs one job at a time and keeps one model | Two models competing for VRAM **(P2)** |
| Model downloads | Size and SHA-256 must match the manifest; resumed with HTTP Range | Corrupted or tampered weights **(P2)** |
| Free disk before an export starts | 2 × predicted output | Half-written outputs on a full disk **(P1)** |
| Uploads and exports paused below | 5% free disk (`min_free_disk_ratio`) | Filling the disk completely **(P1)** |
| Output dimensions | JPEG 65,535 px, WebP 16,383 px, AVIF 16,384 px per side | Encoders failing late on oversized output **(P1)** |
| Abandoned temporary files | Removed after 6 hours when the CPU worker starts | Crashed uploads and exports leaking disk **(P1)** |
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
| `gpu.insufficient_memory` | n/a (job error) | Out of memory even with the smallest tile on the CPU | P2 |
| `upload.too_large` | 413 | The upload is over `SIQE_MAX_UPLOAD_MB` | P1 |
| `upload.empty` | 400 | The upload had no bytes | P1 |
| `image.too_large` | 413 | Over `SIQE_MAX_INPUT_MEGAPIXELS` | P1 |
| `image.unreadable` | 422 | Not an image, or truncated or corrupt | P1 |
| `image.unsupported_format` | 415 | An image format SIQE Studio can't open | P1 |
| `asset.not_found` | 404 | No image with that id | P1 |
| `asset.not_ready` | 409 | The image is still being prepared, or failed to load | P1 |
| `media.not_found` | 404 | A preview, tile or file is missing on disk, or the path is outside the image's folder | P1 |
| `edit.invalid` | 422 | Unknown operation, duplicate operation or a value out of range in the edit document | P1 |
| `export.invalid` | 422 | Export settings that don't fit together (for example a target size for PNG) | P1 |
| `export.target_unreachable` | n/a (job error) | Even the lowest quality is larger than the target size | P1 |
| `rendition.not_found` | 404 | No export with that id | P1 |
| `rendition.not_ready` | 409 | Downloading an export that hasn't finished | P1 |
| `format.dimension_limit` | 422 | Output too large for the chosen format (WebP 16,383 px, JPEG 65,535 px) | P1 |
| `disk.insufficient_space` | 507 | Not enough free disk for the upload or the predicted output | P1 |
| `model.not_found` | 404 | No model with that id in the catalog | P2 |
| `model.not_installed` | 409 | The model's weights aren't downloaded yet (for face restoration: GFPGAN) | P2 |
| `model.busy` | 409 | Removing a model while it is downloading | P2 |
| `model.download_failed` | n/a (job error) | The download was interrupted or the server refused it; retried automatically, resuming the partial file | P2 |
| `model.checksum_mismatch` | n/a (job error) | The downloaded file didn't match its published SHA-256 and was deleted | P2 |
| `model.load_failed` | n/a (job error) | The weights couldn't be loaded safely (for example a pickle with code in it) | P2 |
| `ai.output_too_large` | 422 | The result would exceed `SIQE_MAX_OUTPUT_MEGAPIXELS` | P2 |

## Fallbacks

| When this fails | SIQE Studio does this |
|---|---|
| GPU out of memory | Free cache and retry, halve the tile batch, halve the tile size (down to 64 px, splitting the tiles still to do), then move the job to the CPU; each step is shown on the job and remembered for that model and GPU **(P2)** |
| No GPU or no CUDA | Runs on CPU and says so on the Overview **(P0)** |
| GPU worker down | GPU activities wait in the queue (up to 10 minutes for the self-test) and finish when it returns **(P0)** |
| Export cancelled mid-encode | libvips is told to stop, the partial file is deleted and nothing replaces the last good export **(P1)** |
| Worker crash mid-job | Temporal reschedules the activity after its heartbeat times out **(P0)**; AI runs resume from the last finished tile, kept in the heartbeat and the on-disk result **(P2)** |
| Temporal down | Job creation returns `temporal.unavailable`; browsing still works **(P0)** |
| Live event stream down | The browser reconnects with backoff and falls back to polling every 3 to 5 seconds **(P0)** |
| GitHub unreachable | The Update Center shows the last known releases and says the check failed **(P0)** |
| Model weights missing | AI Lab shows a Download button; runs are refused with `model.not_installed` before queuing **(P2)** |
| First run of a model on a GPU | Peak memory is measured at two tile sizes and stored, so later runs pick the largest tile that fits **(P2)** |

## Input edge cases (P1 and P2)

| Case | Handling |
|---|---|
| EXIF rotation | Applied on import; pixels and metadata agree **(P1)** |
| CMYK, Adobe RGB, wide-gamut profiles | Converted to an sRGB working space via ICC **(P1)** |
| 16-bit images | Kept 16-bit through classic ops and PNG/TIFF export **(P1)**; models run in float (P2) |
| Alpha channel | RGB goes through the model; alpha is upscaled separately **(P2)** |
| Grayscale, palette, 1-bit | Normalised on import; original mode remembered for export |
| Animated GIF, WebP, APNG | Frames processed individually, or the first frame with a notice |
| HEIC and AVIF | Supported via libvips and pillow-heif |
| Truncated or corrupt files | Rejected cleanly with `image.unreadable`; nothing is stored **(P1)** |
| Smaller than a tile or kernel | Padded, processed, cropped **(P2)** |
| Extreme aspect ratios | The tiler handles any shape **(P2)** |
| Y-channel models on RGB | Correct YCbCr conversion; chroma upscaled with Lanczos (SIQE Classic) **(P2)** |
| NaN or out-of-range model output | Replaced and clamped; the count is shown on the job **(P2)** |
| Same file uploaded twice | Recognised by SHA-256; the existing image is returned with `duplicate: true` **(P1)** |
| Half-copied files in hot folders | Picked up only after the size is stable for 2 seconds |
