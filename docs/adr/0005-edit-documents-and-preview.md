# 0005. Edit documents rendered twice: WebGL in the browser, libvips on the server

- **Status:** Accepted, 2 October 2026
- **Raised by:** Phase 1 (Studio). The plan promised a live GPU preview and full-resolution exports from the same edits.

## Context

Studio edits must feel instant while the user drags a slider, but the exported file must be rendered at full resolution, possibly 250 megapixels, which no browser can hold. The two renderings have to agree, or the export won't look like the preview.

## Decision

- Edits are a **JSON edit document** stored on the asset: geometry (rotate clockwise, flip, crop in normalised coordinates of the rotated image) then a fixed, canonical list of adjustments. The original file is never modified. Ops at their defaults are dropped, so an untouched image has an empty document.
- The **server** renders the document with libvips, streamed, at full resolution, in a Temporal activity (`ExportWorkflow`). Working space is sRGB-encoded float with alpha kept apart; 16-bit sources stay 16-bit.
- The **browser** renders the same document on the 2048 px preview with a WebGL 2 shader: one draw per change, plus a cached two-pass blur for sharpening.
- Every formula is written in `siqe/imaging/ops.py` (scalar and libvips versions), `gl/glsl.ts` (GLSL) and `gl/reference.ts` (TypeScript). `python -m siqe.imaging.parity` writes a shared fixture of 160 cases; the backend test, a Vitest test and a Playwright test that runs the real shader on the GPU all check against it.
- The editor autosaves the document (debounced `PUT /api/assets/{id}/edits`) and keeps undo history in the browser.

## Alternatives considered

- **Server-rendered previews on every change:** simple and always identical, but each slider move becomes a job and a round trip. Too slow to feel like an editor.
- **Canvas 2D or CSS filters in the browser:** can't express the formulas exactly (white balance in linear light, tone curves), so preview and export would drift.
- **WebGPU:** not yet available in every browser the owner uses; WebGL 2 is.

## Consequences

- Changing or adding an adjustment means editing three files and regenerating the fixture; the tests fail until all three agree.
- Spatial ops (sharpen, vignette) are checked by separate tests, since the fixture covers pointwise stages only. The preview scales the sharpen radius by the preview size, so very fine sharpening is only fully visible in the export.
- The full-resolution inspector shows original pixels (deep-zoom tiles made at import); edits appear in exports.
