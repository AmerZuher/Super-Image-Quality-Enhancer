# 0010. Model packages: multi-file models installed by a workflow, with opt-in personal-use licences

- **Status:** Proposed, 2 October 2026 (to be accepted, or revised, when Phase 7 lands)
- **Raised by:** your request to install models such as Qwen-Image-2.1 for text to image and image to image, as installable packages, in a new Phase 7.

## Context

Every model so far is one or two files under about 1 GB, run through the tiled pipeline. Image generation models are different: a 7B to 20B transformer, an 8B vision-language text encoder and a VAE, 15 to 60 GB on disk, several precision variants, and a multi-step sampling loop instead of tiles. They need more GPU memory than a 3090 has unless components are loaded one at a time, quantised or offloaded.

Licences differ too. Qwen-Image releases through 2512 and Edit-2511 are Apache-2.0. Qwen-Image-2.1 uses the Qwen Research License: research and evaluation only, commercial use by separate grant. SIQE Studio's rule so far has been commercial-safe models only (rule 11, ADR 0006). On 2 October 2026 you chose to ship the Apache-2.0 models by default and offer 2.1 as an opt-in package for personal use.

## Decision (proposed)

- **A package is a catalog entry of components.** Each component is a pinned file (URL, size, SHA-256) with variants (for example bf16, FP8, int8, GGUF); a package declares the tasks it provides, its licence class and its hardware needs per variant. Components shared between packages are stored once and reference-counted.
- **Installation is a workflow.** `PackageInstallWorkflow` checks disk, GPU memory, the worker's memory limit and licence acceptance before downloading; downloads resume and are verified per file on the CPU worker; a smoke test on the GPU worker must produce an image before the package counts as installed.
- **Two licence classes.** `commercial` packages follow rule 11 unchanged. `personal` packages are never installed by default: the install request must carry the id and version of the licence you accepted, which is stored with the time; their cards, results and flows carry a "Personal use only" chip, and results record the licence in their derivation.
- **Generation is a GPU workflow** with step progress and cancellation between steps. Components load one at a time and are released after use; out-of-memory steps down through more offloading before failing with a suggestion, and the settings that worked are remembered per package and GPU.
- **Results are Library images** carrying the prompt, seed, settings and model, like AI Lab results today.
- **Runtime:** pinned `diffusers` and `transformers` releases in the `ai` image. If a package's published files don't load there, they are converted once at install time.

## Alternatives considered

- **Strict commercial-only:** keeps rule 11 simple, but excludes Qwen-Image-2.1, which you want for personal use. Opt-in with recorded acceptance keeps the default install commercial-safe.
- **Embedding ComfyUI:** it already runs these models, but brings its own server, node graph and plugin ecosystem (with mixed licences) into the stack, alongside Flows. Using `diffusers` keeps one job engine, one GPU queue and one memory policy.
- **One file per model, as today:** can't express shared text encoders, precision variants or install-time conversion.
- **Downloading on first use:** a 20 to 60 GB download would block a generation for an hour; an explicit install with preflight checks fails early and shows progress.
