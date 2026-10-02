# 0009. Forge: graphs checked without PyTorch, training in GPU chunks, models published as files

- **Status:** Accepted, 2 October 2026
- **Raised by:** Phase 5 (Forge). The plan promised a visual model builder with live shape checks and one-click fixes, generated PyTorch code, a dataset builder with a visual degradation chain, resumable training with live charts, and publishing a trained model to AI Lab.

## Context

Forge replaces the Jupyter notebook the project started from. The person using it is not expected to write code, but should be able to read what they built. Training is the heaviest work the app does: it can run for hours on the one GPU that AI Lab and Flows also need. The API and CPU worker images have no PyTorch, yet the editor needs feedback on every change. A trained model must then work everywhere AI Lab models work: tiled, with the out-of-memory ladder, in Flows, on any image size.

## Decision

- **A model is a graph document** of blocks and links (`siqe.forge.graph`), like a flow. `analyze()` is plain Python: it infers every block's channels and scale (as a fraction, so ×1/2 then ×2 is exact), lists problems per block with a fix (new settings for one block) where one is obvious, and computes parameters, multiply-adds per pixel, an estimate of training memory, the patch multiple from Down blocks and the receptive field. The API checks each edit in milliseconds; problems are reported, never refused, so a half-drawn model can be saved.
- **One plan, two consumers.** `analyze()` also produces a topologically sorted plan. `GraphNet` (`siqe.ai.archs.forge`) builds modules from it for training and inference; `codegen.generate()` writes the same plan as a standalone PyTorch file that embeds `forge_blocks.py`. Module names match (`b_<block id>`), so the weights load into either; a torch test checks they give identical output.
- **Datasets are clean crops; damage is applied per sample.** Building a dataset (CPU queue) cuts high-resolution PNG crops from Library images (streamed with libvips, flat crops skipped) and holds out every Nth image for validation. The degradation chain (blur, bicubic down by the model's scale, noise, JPEG) is drawn fresh for every training sample from ranges you can change at any time without rebuilding. One dataset serves models of any scale.
- **Training runs in chunks on the GPU queue.** `ForgeTrainWorkflow` runs `forge_train_chunk` for about three minutes at a time, so an upscale you start waits minutes at most, and a crash loses at most one chunk. Each chunk resumes exactly from `last.pt` (model, optimiser, step, batch, RNG states; loaded with `weights_only=True`). Pause and stop are workflow signals that cancel the running chunk; the activity saves a checkpoint before it ends. The workflow continues as new every 100 chunks.
- **Training degrades instead of failing.** Out of memory halves the batch and doubles gradient accumulation, so the effective batch stays the same. A non-finite loss skips the step and halves the learning rate; twenty in a row stop the run as diverged. bfloat16 autocast is used where the GPU supports it.
- **Metrics stream through the database.** Training points (every 25 steps) and validation results (PSNR and SSIM on brightness, with a bicubic baseline) are written to `forge_metrics` and published as `forge.metrics` events; the charts append them live. The best validation checkpoint is kept as `best.safetensors` with a sample image.
- **Publishing writes files, not code.** `forge_publish` scores the best checkpoint on the held-out crops, then copies it to `/data/models/forge-<name>-v<n>/` with a `forge.json` descriptor (plan, scale, colour, receptive field, benchmark, checksum). The registry discovers Forge models from those descriptors, so the API and both workers see a model as soon as it is published and removing the folder removes the model. AI Lab runs them through the same tiled pipeline as catalog models, in full precision.

## Alternatives considered

- **Checking shapes with PyTorch (meta tensors) in a GPU activity:** exact by construction, but each edit would round-trip through Temporal and the GPU worker, which may be busy training. The plain-Python checker keeps editing instant; the parity test keeps it honest.
- **One long training activity:** simpler, but it would hold the GPU for hours, and a crash or a deploy would lose everything since the last checkpoint. Chunks cost a little set-up time (loading the crops and the checkpoint) every three minutes.
- **Pre-computed damaged inputs:** faster data loading, but every change to the damage would need a rebuild, and the model would see the same damage every epoch.
- **Publishing as ONNX:** the plan mentioned ONNX export. Publishing the safetensors and plan instead lets AI Lab reuse its PyTorch path (tiling, OOM ladder, calibration) unchanged. ONNX export arrives with bring-your-own ONNX models in Phase 6.
- **Storing Forge models as catalog rows only:** the catalog is code; user models live on the data volume with their own descriptor so they survive upgrades and can be copied between installs.
