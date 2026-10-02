import { describe, expect, it } from "vitest";
import type { ActiveOps } from "../doc";
import fixture from "../ops_parity.json";
import { adjustPixel } from "./reference";
import { blurHalfWidth, STAGE, uniformsFor } from "./uniforms";

describe("browser formulas match the server", () => {
  it.each(fixture.cases.map((c, i) => [i, c] as const))("case %i", (_, c) => {
    const out = adjustPixel(c.rgb as [number, number, number], uniformsFor(c.ops as unknown as ActiveOps));
    for (let i = 0; i < 3; i++) {
      expect(Math.abs((out[i] ?? 0) - (c.expected[i] ?? 0))).toBeLessThanOrEqual(fixture.tolerance);
    }
  });
});

describe("uniformsFor", () => {
  it("enables nothing for an untouched image", () => {
    expect(uniformsFor({}).stages).toBe(0);
  });

  it("enables spatial stages only when present", () => {
    const u = uniformsFor({ sharpen: { amount: 120, radius: 2 }, vignette: { amount: -40, midpoint: 0.3 } });
    expect(u.stages).toBe(STAGE.sharpen | STAGE.vignette);
    expect(u.sharpen).toEqual([1.2, 2]);
    expect(u.vignette).toEqual([-0.4, 0.3]);
  });

  it("matches libvips' kernel size for the blur", () => {
    expect(blurHalfWidth(1)).toBe(1);
    expect(blurHalfWidth(0.1)).toBe(1);
    expect(blurHalfWidth(5)).toBe(8);
    expect(blurHalfWidth(100)).toBe(64);
  });
});
