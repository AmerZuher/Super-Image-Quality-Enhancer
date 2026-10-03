# 0013. Forge ONNX export: torch.export first, checked against PyTorch before it's offered

- **Status:** Accepted, 3 October 2026
- **Raised by:** Phase 6 (Hardening). ADR 0009 deferred ONNX export to this phase.

## Context

Forge already offers a trained model as safetensors weights plus generated PyTorch code. ONNX makes it usable without PyTorch: ONNX Runtime, other apps, phones, and SIQE Studio's own "add your own ONNX model" (ADR 0012). Exporters can produce a file that loads but computes something slightly different, or only accepts the example size it was traced with. Either would be a silent failure for the person downloading it.

## Decision

- **Export on the AI worker**, in a `forge.export` job, from the run's best checkpoint rebuilt as `GraphNet` (the same plan Forge trains). The `ai` image gains `onnx` (Apache-2.0) and `onnxscript` (MIT), which the current exporter needs.
- **`torch.export` with dynamic shapes**: a batch from 1 to 64, and height and width up to 8,192 in steps of the model's patch multiple, so a model with Down blocks keeps accepting every size it can process. If it can't trace a graph, the TorchScript exporter is tried with dynamic axes. The file is a single `.onnx`, input `input`, output `output`, values 0 to 1.
- **Verified before it's offered.** The file is run with ONNX Runtime next to PyTorch on three batch and size combinations it wasn't exported with; it is kept only if shapes match and the largest difference is at most 0.001 (in practice about 1e-6). The run records the step, size, exporter and the measured difference, and the UI shows them and flags an export older than the best checkpoint.

## Alternatives considered

- **Only the TorchScript exporter:** needs only `onnx` and was faster to export here, but it is deprecated and will be removed from PyTorch.
- **Exporting when publishing to AI Lab:** AI Lab runs Forge models through PyTorch already. Making export a separate, explicit step keeps publishing fast and lets people export runs they don't publish.
- **Trusting the exporter without checking:** cheap, but the point of the download is that it works elsewhere; the check costs a second.
