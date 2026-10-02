# 0006. AI models: a pinned catalog, safe loading, tiled runs, and results as new images

- **Status:** Accepted, 2 October 2026
- **Raised by:** Phase 2 (AI Lab). The owner asked for commercial-safe models only, and that 8K images must not run out of memory on smaller GPUs.

## Context

AI Lab runs third-party networks on the owner's images and GPU (an RTX 3090, 24 GB), but SIQE Studio must also work on 8 GB cards and on the CPU. Model files are large, come from the internet, and in PyTorch's `.pth` format can contain code. Hugging Face was blocked in the environment this phase was built in.

## Decision

- **Catalog in code.** `siqe.ai.manifest` lists each model's files with URL, exact size and SHA-256, license and summary. A unit test rejects any license outside MIT, BSD-3-Clause and Apache-2.0. Every source is a GitHub release asset (or, for SIQE Classic, the original `v10.h5` at a fixed commit of this repository).
- **Downloads are jobs.** `ModelInstallWorkflow` streams to `tmp/`, hashes while downloading, resumes with HTTP Range after a dropped connection, and moves the file into `models/<id>/` only when size and hash match. SIQE Classic is converted to safetensors at install.
- **Safe loading.** `.pth` files load with `torch.load(weights_only=True)`; safetensors and ONNX can't run code. spandrel only receives the resulting state dict.
- **Tiled runs with a memory governor.** Upscale, denoise and face models run on the GPU queue through `siqe.ai.tiling.run_tiled`: uniform padded tiles, batch and tile size from a per-GPU memory calibration, and the fallback ladder (retry, halve batch, halve tile, CPU) when memory runs out. Results are assembled on disk. Finished tiles are kept, so retries resume.
- **Results are new images.** A run never changes its source. The result is a new asset with `parent_id` and a `derivation` record (model, device, tile, time, fallbacks), so it can be compared at full resolution, edited in Studio and exported like any other image.
- **CPU where it is enough.** Background removal (ISNet at 1024 px) runs through ONNX Runtime on the CPU worker, leaving the GPU free.

## Alternatives considered

- **Download from Hugging Face:** most model hubs are there, but it was unreachable while building; GitHub releases cover every model shipped now.
- **Results as layers in the Studio edit stack:** neat, but AI output can't be re-rendered on every export (minutes per run), and the edit document would need cached pixels. A linked image is simpler and keeps the original untouched.
- **onnxruntime-gpu for everything:** a second CUDA runtime next to PyTorch's would add gigabytes to the image and version conflicts.

## Consequences

- Adding a model means adding a manifest entry with its checksum and license, and checking spandrel supports it (or writing the architecture, as for SIQE Classic and RetinaFace).
- Erase (LaMa), colorize (DDColor), deblur and bring-your-own ONNX are deferred to Phase 6: their usable weights are on Hugging Face.
- The first run of each model on a GPU takes a few seconds longer while memory is measured.
