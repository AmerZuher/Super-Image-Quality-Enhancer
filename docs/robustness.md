# Robustness: limits, error codes and fallbacks

The rules every feature follows so SIQE Studio degrades instead of crashing. Design rationale is in [architecture.md](architecture.md#5-robustness-and-resource-safety). Items marked **(P0)** to **(P4)** exist today; the rest arrive with the phase noted.

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
| AVIF exports | Encoder effort 4, or 3 above 12 MP (3 to 4 times faster at 8K for files about 15% larger); target-size searches on images over 4 MP measure a smaller copy, then check the real file | 8K AVIF exports taking minutes **(P6)** |
| Uploads and exports paused below | 5% free disk (`SIQE_MIN_FREE_DISK_RATIO`), at most 20 GB on big drives | Filling the disk completely **(P1)**; the 20 GB cap keeps a 2 TB drive from holding back 100 GB **(P6)** |
| Output dimensions | JPEG 65,535 px, WebP 16,383 px, AVIF 16,384 px per side | Encoders failing late on oversized output **(P1)** |
| Abandoned temporary files | Removed after 6 hours when the CPU worker starts | Crashed uploads and exports leaking disk **(P1)** |
| Container memory caps | api 1.5 GB, worker 4 GB, worker-gpu 12 GB, db 1 GB | One process taking the whole machine down **(P0)**; the API's cap rose in P3 to hold the search model's text half (about 250 MB) |
| `SIQE_IMPORT_SCAN_SECONDS` | 60 (minimum 10, 0 turns it off) | Checking the import folder too often **(P3)** |
| `SIQE_IMPORT_SETTLE_SECONDS` | 15 | Importing a file that is still being copied: it must be unchanged this long **(P3)** |
| Import folder | Mounted read-only; files are copied in, never moved or deleted; one scan at a time (database advisory lock); at most 100 imports per scan page | Damaging the user's originals, or two scans importing the same file **(P3)** |
| Library indexing | Batches of 32 images on the CPU worker; one indexer at a time (fixed workflow id); history restarts after 300 batches | A large import monopolising the CPU worker or Temporal history **(P3)** |
| Duplicate grouping | Pairs compared in blocks of 256 rows with 64-bit popcounts | Quadratic memory on large libraries **(P3)** |
| Search model memory | The API reads only the text half of CLIP, tensor by tensor; the worker loads it once per process | Running out of memory while loading **(P3)** |
| Text search results | Only images within 0.08 of the best match and above 0.08 overall (bias-corrected score) | A nonsense query returning the whole library **(P3)** |
| Smart album rules | At most 20 rules; every field and operator is validated; user text is escaped before `LIKE` | SQL injection and runaway queries **(P3)** |
| `SIQE_FLOW_CONCURRENCY` | 4 images at a time per run (1 to 32) | One run taking every CPU worker slot; AI blocks still queue one at a time on the GPU **(P4)** |
| Images per run | 20,000 | Runs too large to follow or undo; run on an album or a filter instead **(P4)** |
| Flow run history | One child workflow per image; the run starts afresh (continue-as-new) every 200 images | Temporal history growing without bound on big batches **(P4)** |
| Flow working files | Lossless PNG (depth and alpha kept) in `tmp/flows/<run>/`, written via a temporary name, removed when the run ends | Quality loss between steps and leftover disk use **(P4)** |
| Dry runs | 10 images unless you choose; exports go to a separate "dry run" folder; tags, albums, quarantine and Save to Library are only simulated | Trying a flow changing the Library **(P4)** |
| Export folder | Inside the run's folder only (`..` and absolute paths refused); names made unique, at most 10,000 per name | Writing outside the output folder or overwriting earlier files **(P4)** |
| Watched folders | One open run per flow; new images join it; it finishes after 60 s without new images; a database advisory lock serialises triggers per flow | Two imports opening two runs, or a run per image **(P4)** |
| API keys | 256-bit, stored as SHA-256 only, shown once; checks cached 30 s (revoking takes effect within 30 s); "last used" written at most every 5 minutes | Leaked keys in the database, and a write per request **(P4)** |
| Browser sign-in | The key in an HttpOnly, SameSite=Strict cookie on `/api`, Secure over HTTPS, 90 days | Page scripts reading the key, and cross-site requests **(P4)** |
| Face counting | On the preview, at most 1,280 px; faces under 20 px ignored; halves the detection size on out-of-memory; waits at most 5 minutes for the GPU worker, then tries again on the next pass | Counting crowds, and the Library waiting behind a long AI job **(P4)** |
| Run downloads | Zips are built on the data volume and deleted after sending; only files the run exported can be fetched | Large zips in memory, and path tricks reading other files **(P4)** |
| Forge graphs | Checked in plain Python on every edit (no GPU, no PyTorch); a run starts only with no problems; patch sizes must fit the model's Down blocks and the dataset's crops | Training jobs that fail minutes in on a shape mistake **(P5)** |
| Forge datasets | Crops of 64 to 1024 px, 1 to 64 per image, at most 20,000 images; smaller images and near-flat crops skipped; images read streamed with libvips; at most 64 validation crops scored | Datasets of empty sky, decompression bombs, and slow validations **(P5)** |
| Forge training | Chunks of about 3 minutes on the GPU queue (one GPU job at a time); exact resume from a checkpoint after each chunk; history restarts every 100 chunks; checkpoints loaded with `weights_only=True` | Hogging the GPU for hours, losing progress to a crash, and unsafe pickles **(P5)** |
| Forge models | Published to `/data/models/forge-<name>-v<n>/` with a checksum and a descriptor; run in full precision through the usual tiled pipeline | User models that bypass tiling or the out-of-memory ladder **(P5)** |
| Erase masks | At most 400 strokes of 4,000 points each; brush radius at most half the image width; at most 24 separate areas per run | Huge request bodies and runs that never end **(P6)** |
| Erase regions | The mask is grown a third past the brush (plus 2 px) so no edge of the object is left for the model to continue; each painted area is cut out with about 2.2 times its size of surroundings (at least 512 px), filled at 512 × 512 by LaMa on the CPU worker and blended back with a feathered edge; nothing outside the painted areas changes | Blurry fills on large images, and seams **(P6)** |
| Deblur | NAFNet (int8 ONNX) on the CPU worker through the tiled pipeline, tiles of at least 384 px in multiples of 16; the plan warns when a run will take minutes (about 30 s per megapixel on 4 cores) | The network failing on small tiles, and surprise waits **(P6)** |
| Colorize | Colour is predicted at 256 × 256 and scaled up; the photo's own lightness (every detail) and transparency are kept | Large photos needing gigabytes of GPU memory **(P6)** |
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
| `model.not_runnable` | 422 | Running the search model (CLIP) as an AI Lab job; it only powers the Library | P3 |
| `erase.mask_required` | 422 | Erasing without painting anything (or with an empty mask) | P6 |
| `erase.bad_mask` | n/a (job error) | The painted strokes reached the worker in a shape it can't read | P6 |
| `erase.too_many_regions` | n/a (job error) | More than 24 separate painted areas in one run; erase in a few passes or join nearby strokes | P6 |
| `library.invalid_rules` | 422 | A filter or album rule with an unknown field, a wrong operator or a value of the wrong type | P3 |
| `library.not_indexed` | 409 | "Find similar" on an image that hasn't been analysed by the search model yet | P3 |
| `library.no_location` | 422 | Removing location from images that have none | P3 |
| `library.location_not_removed` | n/a (per image in the job result) | The file keeps GPS data where it can't be removed without re-encoding; export it instead | P3 |
| `album.not_found` | 404 | No album with that id | P3 |
| `flow.not_found` | 404 | No flow with that id | P4 |
| `flow.run_not_found` | 404 | No run with that id | P4 |
| `flow.recipe_not_found` | 404 | Creating a flow from a recipe that doesn't exist | P4 |
| `flow.invalid` | 422 | The flow can't run yet (no Finish block, a loop, a missing setting…); `problems` lists each one by block | P4 |
| `flow.no_images` | 422 | The chosen images, album or filter has no images in it | P4 |
| `flow.too_many_images` | 422 | More than 20,000 images in one run | P4 |
| `flow.bad_folder` | 422 | A watched folder or export subfolder that points outside its folder | P4 |
| `flow.no_files` | 404 | Downloading a run that exported nothing | P4 |
| `flow.image_missing` | n/a (per image) | The image was removed from the Library during the run | P4 |
| `flow.file_missing` | n/a (per image) | A working file disappeared mid-run; run the flow again | P4 |
| `flow.album_missing` | n/a (per image) | Add to album points at an album that was deleted | P4 |
| `flow.wrong_model` | n/a (per image) | An AI block was given a model for a different task | P4 |
| `flow.too_many_files` | n/a (per image) | More than 10,000 exports with the same name in one folder | P4 |
| `flow.unknown_step` | n/a (per image) | A block type this version doesn't know (from a newer `.flow.json`) | P4 |
| `flow.step_failed` | n/a (per image) | Any other failure in one block; the message says which | P4 |
| `flow.all_failed` | n/a (job error) | Every image in a run failed | P4 |
| `forge.project_not_found` | 404 | No model design with that id | P5 |
| `forge.dataset_not_found` | 404 | No dataset with that id | P5 |
| `forge.run_not_found` | 404 | No training run with that id | P5 |
| `forge.template_not_found` | 404 | Starting a model from a template that doesn't exist | P5 |
| `forge.invalid` | 422 | Training a model whose design still has problems (or is empty) | P5 |
| `forge.patch_multiple` | 422 | The patch size isn't a multiple the model's Down blocks need | P5 |
| `forge.patch_too_big` | 422 | The patch, times the model's scale, is larger than the dataset's crops | P5 |
| `forge.no_images` | 422 or job error | The chosen images, album or filters have no images | P5 |
| `forge.dataset_empty` | job error | No image was big or detailed enough for a crop | P5 |
| `forge.dataset_not_ready` | 409 | Training on, or previewing, a dataset that hasn't finished building | P5 |
| `forge.dataset_busy` | 409 | Rebuilding a dataset that is being built | P5 |
| `forge.dataset_in_use` | 409 | Deleting or rebuilding a dataset a running training uses | P5 |
| `forge.dataset_missing` | job error | The run's dataset no longer exists | P5 |
| `forge.not_running` | 409 | Pausing, resuming or stopping a run that has finished | P5 |
| `forge.run_busy` | 409 | Deleting a run that is still training | P5 |
| `forge.no_sample` | 404 | No validation has run yet, so there is no sample image | P5 |
| `forge.nothing_to_publish` | 409 or 404 | Publishing or downloading weights before the first validation saved a checkpoint | P5 |
| `forge.out_of_memory` | job error | The model doesn't fit in GPU memory even one patch at a time | P5 |
| `forge.diverged` | job error | Twenty steps in a row gave non-finite losses | P5 |
| `forge.model_files_missing` | 409 | Re-adding a published Forge model whose files were removed | P5 |
| `job.unexpected` | n/a (job error) | An activity failed in a way that has no typed error; the details go to the worker's log, never to the UI | P6 |
| `job.timed_out` | n/a (job error) | A worker stopped responding (restart, out of memory) and the job ran out of retries | P6 |
| `auth.required` | 401 | `SIQE_API_AUTH=keys` and the request has no key | P4 |
| `auth.invalid_key` | 401 | The key is wrong or was revoked | P4 |
| `auth.key_not_found` | 404 | Revoking a key that doesn't exist | P4 |
| `auth.last_key` | 409 | Revoking the only key while signed in with it | P4 |
| `album.not_smart` | 422 | Setting rules on a hand-picked album | P3 |
| `album.not_manual` | 422 | Adding images by hand to a smart album | P3 |
| `import.unreadable` | n/a (shown in the import folder card) | A file in the import folder couldn't be read | P3 |

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
| Search model not installed | Library filters, duplicates (by hash) and name and tag search still work; a banner offers the download **(P3)** |
| Library indexing interrupted | The next batch picks up every image that isn't analysed yet; the worker requests a pass at start-up **(P3)** |
| An image fails analysis | It is marked analysed so the batch moves on; the error is logged **(P3)** |
| Import folder missing | The scan records it and the Library says "Folder not found"; nothing else is affected **(P3)** |
| Disk nearly full during an import | The scan stops before copying more; the remaining files wait for the next check **(P3)** |
| One image fails in a flow run | Its error and the step are recorded on that image; the other images carry on; the run fails only if every image failed **(P4)** |
| Worker restarts during a flow run | Each image is its own child workflow; finished steps aren't repeated (exports and Library writes are recorded per step, so retries don't duplicate them) **(P4)** |
| Output folder not writable | Exports go to `outputs/` on the data volume instead, and the run says where; downloads still work **(P4)** |
| An AI model in a flow isn't installed | The run is refused before it starts (`model.not_installed`, naming the model) and the block's settings say to download it in AI Lab; a watched folder skips the run and logs why **(P4)** |
| Face detector not installed | Face filters match nothing and the Library offers the download; everything else works **(P4)** |
| GPU worker missing while counting faces | Counting waits up to 5 minutes, then the Library carries on; images are counted on a later pass **(P4)** |
| Sign-in on and no key yet | The web app shows a sign-in screen with the command that makes a key (`siqe keys create`) **(P4)** |
| GPU out of memory while training | The batch is halved and gradients accumulated, keeping the effective batch; the run's notes say when **(P5)** |
| A training step gives a non-finite loss | The step is skipped and the learning rate halved; twenty in a row stop the run as `forge.diverged`, keeping the best checkpoint **(P5)** |
| Worker restarts during training | The chunk is retried from the last checkpoint, with the same random state **(P5)** |
| Pausing or stopping a run | The running chunk is cancelled, saves a checkpoint and ends; resuming continues from exactly that step **(P5)** |
| Other GPU work while training | It runs between training chunks, so it waits at most about 3 minutes **(P5)** |
| Erase painted on another image | Strokes belong to the image they were painted on; switching images starts a fresh mask, so a mask never lands on the wrong photo **(P6)** |
| An ONNX model file is damaged | The run fails with `model.load_failed`; remove and download the model again **(P6)** |
| First run of a model on a GPU | Peak memory is measured at two tile sizes and stored, so later runs pick the largest tile that fits **(P2)** |

## Input edge cases

`tests/integration/test_input_formats.py` and `test_robustness.py` check these against a running stack.


| Case | Handling |
|---|---|
| EXIF rotation | Applied on import; pixels and metadata agree **(P1, checked in P6)** |
| CMYK, Adobe RGB, wide-gamut profiles | Converted to an sRGB working space via ICC **(P1)** |
| 16-bit images | Kept 16-bit through classic ops and PNG/TIFF export **(P1)**; models run in float (P2) |
| Alpha channel | RGB goes through the model; alpha is upscaled separately **(P2)** |
| Grayscale, palette, 1-bit | Opened and converted to sRGB on import; exports are RGB **(P1, checked in P6)** |
| Animated GIF, WebP, APNG | The first frame is used **(P1, checked in P6)** |
| HEIC and AVIF | Opened by libvips (libheif) **(P1, AVIF checked in P6)** |
| Truncated or corrupt files | A damaged header is refused at upload with `image.unreadable` **(P1)**; damage further in (a file cut off mid-copy) is found while preparing the image, which then fails with `image.unreadable` and a fix, never raw decoder text **(P6)** |
| Smaller than a tile or kernel | Padded, processed, cropped **(P2, checked in P6)** |
| Extreme aspect ratios | The tiler handles any shape **(P2)** |
| Y-channel models on RGB | Correct YCbCr conversion; chroma upscaled with Lanczos (SIQE Classic) **(P2)** |
| NaN or out-of-range model output | Replaced and clamped; the count is shown on the job **(P2)** |
| Same file uploaded twice | Recognised by SHA-256; the existing image is returned with `duplicate: true` **(P1)**; from the import folder it is recorded as a duplicate **(P3)** |
| Half-copied files in the import folder | Imported only when size and modification time have been unchanged for `SIQE_IMPORT_SETTLE_SECONDS` **(P3)** |
| Resized, recompressed or lightly edited copies | Grouped as near-duplicates by perceptual hash, or by CLIP similarity with loosely matching hashes; the largest, sharpest, least compressed copy is kept **(P3)** |
| Abstract images (gradients, colour fields) | Not grouped on CLIP similarity alone, which rates them alike **(P3)** |
| Featureless images (a flat colour) | Get no automatic tags **(P3)** |
| GPS in EXIF and XMP (JPEG, PNG, WebP, TIFF, HEIC) | Removed in place without changing the file length or pixels; PNG checksums are recomputed **(P3)** |
