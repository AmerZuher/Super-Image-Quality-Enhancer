# 0011. Erase, colorize and deblur: ONNX on the CPU worker, whole-image models outside the tiler

- **Status:** Accepted, 3 October 2026
- **Raised by:** Phase 6 (Hardening). The plan promised more restoration tasks in AI Lab and Flows: removing objects, colourising black and white photos and sharpening blurred ones, all commercial-safe.

## Context

AI Lab's run pipeline was built for tiled image-to-image models on the GPU: spandrel checkpoints, scaled ×1 to ×4, each tile independent. The new tasks don't all fit that shape. An eraser needs a mask and works on whole regions, not tiles: a tile boundary through the hole would leave a seam the model can't see across. A colourizer looks at the whole photo to decide that the sky is blue. Commercial-safe weights are also scarcer here: CodeFormer-style restorers and many inpainting and deblurring checkpoints are non-commercial, and some only exist on Hugging Face, which some sandboxes block.

## Decision

- **Models:** LaMa for erase (Apache-2.0) and NAFNet for deblur (MIT), both as ONNX files from the OpenCV Zoo, pinned to a commit; the SIGGRAPH 2017 colorizer (BSD-2-Clause) from its authors' bucket. BSD-2-Clause joins the allowed licences.
- **ONNX Runtime on the CPU worker.** A small `OnnxBackend` (`siqe.ai.onnx_model`) gives ONNX models the same interface as PyTorch ones, so deblurring goes through the tiled pipeline unchanged: context, seam blending, the result assembled on disk, resume after a crash. The catalog gains `multiple` and `min_input` because NAFNet needs tiles of at least 384 px in multiples of 16. The images keep CPU-only ONNX Runtime: these models are a few seconds per tile on four cores, and keeping them off the GPU means they never wait behind training.
- **Erase works by region, not by tile.** The browser sends strokes in image-relative units (0 to 1), not a mask bitmap, so the request stays small whatever the image size and the mask matches the full-resolution original. Nearby strokes are grouped into regions; each is cut out with about 2.2 times its size of surroundings, filled at LaMa's fixed 512 × 512, scaled back and blended in with a feathered mask. Pixels outside the painted areas are copied unchanged.
- **Colorize recombines in CIELAB.** The network predicts colour (a and b) from lightness at 256 × 256 on the GPU worker. Colour is scaled up and joined with the original's full-resolution lightness, so no detail is lost and memory stays flat at any image size. The network is a torch port with the original module names, so the checkpoint loads with `weights_only=True`.
- **Routing stays in the catalog.** `CPU_ARCHS` (ISNet, ONNX, LaMa) run on the CPU worker; `TILED_ARCHS` go through the tiler; the rest are single-pass. Plans for CPU models say so and warn when a run will take minutes.

## Alternatives considered

- **Tiling the eraser:** reuses the pipeline, but every tile edge crossing a hole becomes a seam, and LaMa's fixed input size means most tiles would be resized anyway.
- **Sending a mask image:** simple, but a full-resolution 8K mask is tens of megabytes per run, and scaling a preview-sized mask up gives jagged edges.
- **Running these models on the GPU with onnxruntime-gpu:** faster, but a second CUDA runtime in the `ai` image (larger, version-locked to the driver) and contention with training. Revisit if deblur speed becomes a complaint.
- **DDColor or DeOldify for colour:** better colours, but their weights are non-commercial or unclear. SIGGRAPH17 is older and plainer, and safe to ship.
