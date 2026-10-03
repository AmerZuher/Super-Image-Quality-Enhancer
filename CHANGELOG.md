# Changelog

User-facing changes to SIQE Studio. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/). When you publish a GitHub release, copy its section here into the release notes; they appear in the app's Update Center.

## [Unreleased]

### Added

- **Erase objects:** paint over what you don't want (a post, a passer-by, a sensor spot) in AI Lab and it is filled in from its surroundings. Only the painted areas change. Uses LaMa (Apache-2.0) on the CPU, about 10 seconds per area.
- **Colorize black and white photos** with the SIGGRAPH 2017 colorizer (BSD-2-Clause). Every detail of the photo is kept; only colour is added. Also a block in Flows.
- **Deblur** slightly blurred or shaken photos with NAFNet (MIT). Runs on the CPU at any size; the plan tells you when it will take minutes. Also a block in Flows.
- **Add your own ONNX models** in AI Lab → Models. Each file is checked by running it on test images, which finds its scale, the image sizes it accepts and its speed on your computer. Files it can't run are refused with a reason and how to re-export them. Added models work in AI Lab and Flows on the CPU, tiled at any image size, and can be removed again.

- **Forge is here: design, train and publish your own models.** Start from SIQE Classic, ESPCN, EDSR-lite, a bicubic-plus-detail ×4 model or a U-Net denoiser, or from just an input and an output, and change it block by block: convolutions, residual and residual dense blocks, channel attention, add and concat, depth-to-space, resize, down and up.
- **Checked as you draw:** every link shows its channels and size, and the model's parameters, compute and training memory update as you go. Blocks that can't work turn red and say why, usually with a one-click fix.
- **Read the code:** the Code tab shows the plain PyTorch module your design compiles to, ready to copy or download. Trained weights load straight into it.
- **Datasets from your Library:** cut training crops from selected images, an album, rules or everything. Training damages each crop differently every time (blur, downscaling, noise and JPEG, each with a range you choose), and a preview shows exactly what the model will learn to undo.
- **Train with live charts:** loss and PSNR on held-out photos (against bicubic) stream in as it learns, with a side-by-side sample from the best checkpoint. Pause, resume or stop at any time; training runs in short chunks so your other AI jobs still get their turn, and picks up exactly where it left off after a restart. If the GPU runs out of memory the batch shrinks automatically; if training becomes unstable it slows down and tells you.
- **Publish to AI Lab:** the best checkpoint is scored on your held-out photos and added to AI Lab as a new version, with a "Trained in Forge" badge and its score. Use it like any other model in AI Lab and Flows, or download its weights.

- **Flows are here.** Chain blocks on a canvas to automate what you repeat: sort images with **If** (orientation, size, tags, faces, anything a smart album can use), edit them (adjustments, your Studio edits, resize, crop to a shape, rotate, trim, place on a canvas, watermark), enhance them with AI (upscale, denoise, remove background, restore faces), then export, save to the Library, tag, add to an album or quarantine.
- **Five recipes to start from:** wallpaper pipeline, product shots, web gallery, old photo restoration and blurry photo triage. Flows save as you edit, and blocks that need fixing turn red and say why.
- **Run on what you choose:** the images selected in the Library ("Run a flow" in the selection bar), an album, a set of rules, or everything. A **dry run** tries a flow on 10 images first and only pretends to change your Library.
- **Batches that keep going:** each image runs on its own, so one broken file never stops the rest. Every image shows its steps, timings, exported files and any error with a fix; each block on the canvas shows how many images went through it last time. Download a run's files as one zip.
- **Watched folders:** a flow can run on new images as they arrive in a folder inside the import folder.
- **API keys and sign-in:** set `SIQE_API_AUTH=keys` and every browser and script needs a key. Create and revoke keys in **Settings → Access**, or with `siqe keys create` where the app runs.
- **The `siqe` command** lists flows, uploads images and runs a flow (by name or from a `.flow.json` file) on files from your computer, then saves the results: `siqe run "Web gallery" ./photos --download ./out`.
- **People in the Library:** faces are counted in every image (only the number is kept) once the face restoration model is installed. Filter with **People**, or use the new **Faces** rule in smart albums and flows.
- New settings: `SIQE_OUTPUT_PATH`, `SIQE_FLOW_CONCURRENCY` and `SIQE_API_AUTH`. `make env` now also creates the `output` folder.

- **The Library is here.** Every image you add is analysed in the background: sharpness, main colour, the date it was taken and where, and a fingerprint for finding copies.
- **Search by describing a photo** ("mountain lake at sunrise"), **find similar images**, and **automatic tags**, after a one-click download of the CLIP search model (578 MB, MIT, runs on the CPU). Without it, the search box matches file names and tags.
- **Duplicates:** resized, recompressed and lightly edited copies are grouped, and the best copy (largest, sharpest, least compressed) is marked to keep. Keep the best of one group or all of them, or mark them as not duplicates.
- **Quarantine:** removing images moves them to quarantine first, hidden from Studio and AI Lab until you restore them or delete them for good.
- **Albums:** smart albums fill themselves from rules (orientation, size, aspect, colour, tags, sharpness, location, date, file name, import folder); hand-picked albums hold what you choose. Any set of filters can be saved as a smart album. Four starter albums are included.
- **Filters** for orientation, low resolution, blur, location, AI results, colour and your most common tags, plus sorting by date added, date taken, name, size, resolution or sharpness.
- **Camera details and location:** see camera, lens, exposure and where a photo was taken, and **remove the location** from originals without re-encoding: the pixels and other camera data stay exactly as they were, and the original waits in quarantine.
- **Import folder:** copy images into the `import` folder (set by `SIQE_IMPORT_PATH`) and they're added within a minute. Files still being copied wait until they're finished, and the originals are never changed.
- Select several images with Ctrl-click or Shift-click (or Ctrl A) to tag them, add them to an album, remove their location or quarantine them together. The Library works on a phone too.
- New settings: `SIQE_IMPORT_PATH`, `SIQE_IMPORT_SCAN_SECONDS` and `SIQE_IMPORT_SETTLE_SECONDS`.

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

- Big AVIF exports are about three times faster (an 8K image: 18 seconds instead of 52), for files about 15% larger. Exports with a target size on large images are quicker too.
- The free disk space SIQE Studio keeps in reserve is capped at 20 GB, so large drives aren't held back, and the "not enough disk" message explains the reserve.
- The app's first load is about a quarter smaller.
- The Overview marks Studio as ready; the other workspaces still describe what's coming.
- The API's default memory cap (`SIQE_API_MEMORY`) is now 1.5 GB, to hold the search model.

### Fixed

- A damaged or truncated image now fails with a clear "can't read this image" message instead of a bare "Error".
- Unexpected failures and timeouts show a stable error with a hint instead of internal details.

- Some interface text could fall back to a system font, because small font files were blocked by the app's security policy.

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
