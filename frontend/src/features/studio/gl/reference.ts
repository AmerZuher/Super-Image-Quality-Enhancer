/**
 * Line-for-line TypeScript copy of ADJUST in glsl.ts, used by unit tests to check the uniform
 * derivation against the server's fixture without a GPU.
 */
import { STAGE, type Uniforms } from "./uniforms";

const LUMA: [number, number, number] = [0.2126, 0.7152, 0.0722];
type RGB = [number, number, number];

const toLinear = (x: number) => {
  const v = Math.max(x, 0);
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};
const toSrgb = (x: number) => {
  const v = Math.max(x, 0);
  return v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
};
const clamp01 = (x: number) => Math.min(Math.max(x, 0), 1);
const luma = (c: RGB) => LUMA[0] * c[0] + LUMA[1] * c[1] + LUMA[2] * c[2];
const map = (c: RGB, f: (v: number, i: number) => number): RGB => [f(c[0], 0), f(c[1], 1), f(c[2], 2)];

export function adjustPixel(rgb: RGB, u: Uniforms): RGB {
  let c: RGB = [...rgb];
  const on = (bit: number) => (u.stages & bit) !== 0;
  if (on(STAGE.whiteBalance)) c = map(c, (v, i) => toSrgb(toLinear(v) * u.gain[i as 0 | 1 | 2]));
  if (on(STAGE.levels)) c = map(c, (v) => (v - u.levels[0]) / (u.levels[1] - u.levels[0]));
  if (on(STAGE.tone)) {
    c = map(c, (v) => {
      const cc = clamp01(v);
      const inv = 1 - cc;
      return v + cc * inv * inv * u.tone[0] + cc * cc * inv * u.tone[1];
    });
  }
  if (on(STAGE.contrast)) c = map(c, (v) => (v - 0.5) * u.contrast + 0.5);
  if (on(STAGE.vibrance)) {
    const lum = luma(c);
    const sat = clamp01(Math.max(...c) - Math.min(...c));
    const f = 1 + u.vibrance * (1 - sat);
    c = map(c, (v) => lum + (v - lum) * f);
  }
  if (on(STAGE.saturation)) {
    const lum = luma(c);
    c = map(c, (v) => lum + (v - lum) * u.saturation);
  }
  if (on(STAGE.blackWhite)) {
    const lum = luma(c);
    c = [lum, lum, lum];
  }
  return map(c, clamp01);
}
