/**
 * Turns active ops into the numbers the shader needs. Shared by the WebGL renderer, the
 * TypeScript reference and the shader parity test, so all three agree by construction.
 * Formulas: backend/src/siqe/imaging/ops.py.
 */
import type { ActiveOps } from "../doc";

export const STAGE = {
  whiteBalance: 1,
  levels: 2,
  tone: 4,
  contrast: 8,
  vibrance: 16,
  saturation: 32,
  blackWhite: 64,
  sharpen: 128,
  vignette: 256,
} as const;

export interface Uniforms {
  stages: number;
  /** Per-channel linear-light gain: white balance × 2^EV. */
  gain: [number, number, number];
  /** Black point and white point of the levels stretch. */
  levels: [number, number];
  /** Shadow and highlight bump strengths (0.35 × 6.75 × amount). */
  tone: [number, number];
  contrast: number;
  vibrance: number;
  saturation: number;
  /** Detail gain and Gaussian sigma in full-resolution pixels. */
  sharpen: [number, number];
  /** Vignette strength (amount / 100) and midpoint. */
  vignette: [number, number];
}

const TONE = 0.35 * 6.75;

function amount(ops: ActiveOps, id: string, name = "amount", fallback = 0): number {
  return ops[id]?.[name] ?? fallback;
}

export function uniformsFor(ops: ActiveOps): Uniforms {
  const has = (id: string) => id in ops;
  let stages = 0;
  if (has("temperature") || has("tint") || has("exposure")) stages |= STAGE.whiteBalance;
  if (has("whites") || has("blacks")) stages |= STAGE.levels;
  if (has("shadows") || has("highlights")) stages |= STAGE.tone;
  if (has("contrast")) stages |= STAGE.contrast;
  if (has("vibrance")) stages |= STAGE.vibrance;
  if (has("saturation")) stages |= STAGE.saturation;
  if (has("black_white")) stages |= STAGE.blackWhite;
  if (has("sharpen")) stages |= STAGE.sharpen;
  if (has("vignette")) stages |= STAGE.vignette;

  const t = amount(ops, "temperature") / 100;
  const n = amount(ops, "tint") / 100;
  const k = 2 ** amount(ops, "exposure", "ev");
  return {
    stages,
    gain: [(1 + 0.25 * t) * k, (1 - 0.25 * n) * k, (1 - 0.25 * t) * k],
    levels: [(-0.15 * amount(ops, "blacks")) / 100, 1 - (0.25 * amount(ops, "whites")) / 100],
    tone: [(TONE * amount(ops, "shadows")) / 100, (TONE * amount(ops, "highlights")) / 100],
    contrast: 1 + amount(ops, "contrast") / 100,
    vibrance: amount(ops, "vibrance") / 100,
    saturation: 1 + amount(ops, "saturation") / 100,
    sharpen: [amount(ops, "sharpen") / 100, amount(ops, "sharpen", "radius", 1)],
    vignette: [amount(ops, "vignette") / 100, amount(ops, "vignette", "midpoint", 0.5)],
  };
}

/**
 * Half-width of the blur kernel, matching libvips gaussblur's default min_ampl of 0.2:
 * the mask keeps every tap whose weight is at least a fifth of the peak.
 */
export function blurHalfWidth(sigma: number): number {
  return Math.min(64, Math.max(1, Math.floor(sigma * Math.sqrt(-2 * Math.log(0.2)))));
}
