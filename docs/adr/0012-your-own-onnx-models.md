# 0012. Your own ONNX models: checked by running them, installed as files, run on the CPU

- **Status:** Accepted, 3 October 2026
- **Raised by:** Phase 6 (Hardening). The plan promised bring-your-own ONNX models in AI Lab and Flows.

## Context

People find upscalers and restoration models on sites like OpenModelDB, or export their own from PyTorch, and want to use them here. An ONNX file is safe to load (no pickled code), but it says little about how to use it: input names, sometimes symbolic shapes, nothing about scale, value range or the size steps a U-Net needs. Guessing wrong gives seams, a black result or a crash many minutes into a large image. The CPU worker has 4 GB of memory, and the API should never load a model at all.

## Decision

- **Upload, then check in a job.** `POST /api/models/onnx` streams the file to `tmp/` (at most 1 GB, hashed as it arrives) and starts `ModelImportWorkflow` on the CPU queue. The API reserves the model id by creating its staging folder, so two imports of the same name can't collide.
- **The check runs the model.** `siqe.ai.onnx_import.probe` accepts one float N×C×H×W input with 1 or 3 channels and dynamic height and width. It runs a test gradient at 64 px, then 128, 256 and 384, until the model accepts one. From that it measures the scale (a whole number from 1 to 8, the same in both directions), the size step (the smallest of 1 to 64 that gives a correct output size), whether output is 0..1 or 0..255, and seconds per megapixel on this CPU. Anything else is refused with a typed error and a fix ("export with dynamic_axes").
- **Installed as files, like Forge models.** A passing model is moved into `models/user-<name>/` with `model.json` (name, task, checksum, the probe's findings) by renaming a finished folder. The registry discovers these descriptors, so every process sees the model at once, and removing the folder removes it. Models that enlarge are upscalers; same-size models are listed under denoise or deblur, as you choose.
- **Always on the CPU worker, always tiled.** User models run through `OnnxBackend` and the same tiled pipeline as the built-in ONNX deblur model, with the size step and minimum tile the check found. The API marks AI Lab runs for the CPU worker (`AiRunRequest.on_cpu`), and `flow_run_start` marks Flows blocks that use a CPU model (`queue: "cpu"`), because workflows can't look models up themselves.

## Alternatives considered

- **Asking the user for scale, range and size step:** most people don't know them, and a wrong answer fails late. Measuring takes a few seconds.
- **Checking in the API:** simpler, but it would load untrusted, possibly large models into the API process, which has a 1.5 GB memory cap.
- **Running user models on the GPU with onnxruntime-gpu:** see ADR 0011. The measured speed is shown on each model so people can judge, and the plan warns when a run will take minutes.
- **Fixed-size models (padding each tile to the model's size):** possible, but rare among image-to-image exports and easy to fix at export time, so they are refused with that fix.
