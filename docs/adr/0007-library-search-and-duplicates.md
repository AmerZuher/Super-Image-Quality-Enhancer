# 0007. Library: background indexing, CLIP in numpy, duplicates by hash and embedding

- **Status:** Accepted, 2 October 2026
- **Raised by:** Phase 3 (Library). The plan promised duplicates with keep-best rules, search by description, similar images, smart albums, EXIF and GPS tools, and a hot folder.

## Context

The Library has to organise thousands of photos on the user's own machine, often without a GPU. Search by description needs a vision-language model, but the API and CPU worker images have no PyTorch (it lives only in the 9 GB GPU worker image), and the GPU worker runs one job at a time: a search must never wait behind a 30-minute upscale. Hugging Face, where most CLIP ONNX exports live, was unreachable while building. Every model must allow commercial use.

## Decision

- **Background indexing, not jobs.** `LibraryIndexWorkflow` runs with a fixed id and is started by signal-with-start after every import, AI result, location removal and CLIP install, and when the CPU worker starts. Each batch analyses images that are new or were analysed by an older `ANALYSIS_VERSION`, then the last pass regroups duplicates. Users see "Analysing N images" in the Library, not a job per image.
- **Measurements from the preview.** Perceptual hash (DCT, 64 bit), gradient hash (64 bit), sharpness (variance of the Laplacian at 768 px), main colour family, EXIF date and GPS are read from the 2,048 px preview made at import, so a 100-megapixel photo costs the same as a small one.
- **CLIP ViT-B/32 in numpy.** OpenCLIP's LAION-400M ViT-B/32 (MIT, on GitHub releases) is read without torch by a restricted unpickler (`siqe.ai.pth`, the same allow-list idea as `weights_only=True`), stored as float16 safetensors, and run by a numpy port of the encoders (`siqe.ai.clip`), tested against PyTorch's own attention. About 10 images a second on four cores; a text query takes milliseconds, so the API answers searches itself.
- **Vectors in PostgreSQL.** Embeddings are `vector(512)` with an HNSW index (inner product). Text queries subtract the mean of the tag phrases from the query vector, which removes each image's bias towards matching any text and puts the best match first; results are kept within a window of the best score and above a floor.
- **Automatic tags by zero-shot classification** against a fixed vocabulary of about 70 phrases. A tag needs both a clear softmax share and a lift over the image's average, so featureless images get none. Users can add and remove tags; removing an automatic tag hides it.
- **Duplicates.** Two images are near-duplicates when pHash and dHash are close, or when CLIP similarity is at least 0.95 and the hashes are loosely close. Groups are connected components. The keeper is ranked by resolution, then sharpness, then lossless format and bytes per pixel, then age. AI results are excluded. "Not duplicates" marks the images so they aren't regrouped with each other.
- **Quarantine instead of delete.** Resolving duplicates, removing location and the Quarantine action set `quarantined_at`; quarantined images disappear from Studio and AI Lab until restored. Deleting for good is only possible from quarantine.
- **Smart albums are rules.** A small, validated rule language (`siqe.library.rules`) compiles to SQL; the filter chips use the same rules, so any filter can be saved as an album. Hand-picked albums are a join table.
- **Location removal in place.** The EXIF GPS directory is emptied and XMP GPS fields are overwritten with spaces, keeping the file length, so every other offset (maker notes, ICC profile, image data) stays valid. The clean file becomes a new image; the original goes to quarantine.
- **Import folder.** A host folder is mounted read-only into the CPU worker and checked on a Temporal Schedule. A file is imported once, and only after its size and time have been stable for 15 seconds; each import is an ordinary ingest job.

## Alternatives considered

- **ONNX Runtime for CLIP:** fast and already a dependency, but the exports are on Hugging Face and converting needs torch at install time. numpy is fast enough at this model size and keeps the API image small.
- **Embedding on the GPU worker:** quicker on a GPU, but searches and indexing would queue behind long AI runs, and the API would need a Temporal round trip per query.
- **A larger CLIP (ViT-B/16, ViT-L/14):** better recall at 4 to 20 times the cost on the CPU. ViT-B/32 indexes a 10,000-photo library in under 20 minutes on four cores.
- **Deleting duplicates straight away:** irreversible; quarantine keeps every decision undoable.
- **Re-encoding to strip GPS:** loses quality on JPEG and is slower; the in-place method keeps every other byte.

## Consequences

- The API holds about 250 MB for the text half of CLIP once it is installed; its default memory cap rose from 1 GB to 1.5 GB.
- Changing the analysis (a new hash, a new sharpness scale) means bumping `ANALYSIS_VERSION`; the indexer then re-analyses everything in the background.
- Face-based albums wait for a later phase: face detection needs torch and would run on the GPU queue.
