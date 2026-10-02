# Changelog

User-facing changes to SIQE Studio. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/). When you publish a GitHub release, copy its section here into the release notes; they appear in the app's Update Center.

## [Unreleased]

### Added

- **AI Lab is here.** Upscale ×2, ×3 or ×4, remove noise, cut out the subject, or restore faces. Every result becomes a new image linked to its original, which never changes.
- **Model library:** seven commercial-safe models download with one click from their authors' GitHub releases, are checked against a published checksum, and can be removed again. Interrupted downloads pick up where they stopped.
- **SIQE Classic is back:** the original Super Image Quality Enhancer model, ported from its Keras weights.
- **Face restoration** with GFPGAN, on its own or as an option when upscaling.
- **See the plan before you run:** result size, GPU or CPU, tiles, memory and disk, with warnings when something won't fit.
- **Any size, any GPU:** images are processed in tiles that fit your GPU's memory, measured on the first run. If memory still runs out, the run steps down (smaller batches, smaller tiles, then the CPU) instead of failing, and tells you.
- **Full-resolution compare** of an original and its result: a split divider or synced side-by-side view, zoomable down to single pixels.
- AI results open in Studio for editing and export like any other image, and carry an AI badge.
- New setting `SIQE_MAX_OUTPUT_MEGAPIXELS` (default 1000) caps the size of AI results.

- **Studio is here.** Upload images by dropping them anywhere on the page or with Add images; each one gets a thumbnail, a preview and full-resolution zoom tiles. The same file uploaded twice is recognised and opened instead of stored again.
- **Live editing:** exposure, contrast, highlights, shadows, whites, blacks, temperature, tint, vibrance, saturation, black and white, sharpen and vignette, previewed instantly on your graphics card. Your original file is never changed.
- **Edit stack and history:** switch any adjustment off or remove it, undo and redo (Ctrl Z, Ctrl Shift Z), or jump back to any step. Edits save automatically.
- **Crop, rotate and flip** with draggable handles and aspect presets (1:1, 3:2, 4:3, 16:9, 4:5, 9:16 or the original shape).
- **Compare** your edit with the original: split view with a draggable divider, side by side, or a difference view. Hold `\` to see the original.
- **Histogram** with warnings when shadows or highlights are clipped.
- **Export** to JPEG, PNG, WebP, AVIF or TIFF at full resolution, with a longest-side limit and an optional target file size. Camera data and GPS location are removed by default. Exports show live progress, can be cancelled, and stay available to download.
- **Inspect** (press `I`) opens the original at full resolution with smooth zoom, down to single pixels.
- New setting `SIQE_MAX_UPLOAD_MB` (default 2048) caps the size of one upload.

### Changed

- The Overview marks Studio as ready; the other workspaces still describe what's coming.

## [0.1.0] - Foundation

The first version of the rebuilt platform. It replaces the original Super Image Quality Enhancer app, and absorbs the ideas from Image-modifier and Image-Modifier-.

### Added

- **Overview:** live health of every service, the GPU (name, video memory, temperature, utilisation), memory and disk, updated every few seconds.
- **System self-test:** sends a job through the whole pipeline and benchmarks your hardware (image engine speed and GPU throughput), with live progress and cancel.
- **Update Center:** the version button in the top bar tells you when a new release is out and shows its release notes and the command to update.
- **Jobs page** with live progress for everything that runs.
- **Command palette** (Ctrl K) for pages, actions and theme.
- Dark and light themes, and a layout that works on a phone.
- Previews of the five workspaces (Studio, AI Lab, Library, Flows, Forge) describing what each phase brings.
- One-command install with Docker Compose, CPU by default, NVIDIA GPU with `make up-gpu`.

### Changed

- The old TensorFlow app, Next.js frontend and notebook have been removed. Your original model returns as "SIQE Classic" in the AI Lab phase. The old code remains in git history.
