import { describe, expect, it } from "vitest";
import type { OpSpec } from "@/lib/api/client";
import { dragRect, fitRatio } from "./components/CropOverlay";
import {
  activeOps,
  cropBox,
  EMPTY_DOC,
  flipView,
  isEdited,
  outputSize,
  plannedSize,
  rotateView,
  roundHalfEven,
  setCrop,
  setEnabled,
  setParam,
  setToggle,
} from "./doc";

const amount = { name: "amount", label: "Amount", min: -100, max: 100, step: 1, default: 0, unit: "" };
const SPECS: OpSpec[] = [
  {
    id: "exposure",
    label: "Exposure",
    group: "light",
    description: "",
    params: [{ ...amount, name: "ev", min: -4, max: 4, step: 0.01, unit: "EV" }],
  },
  { id: "contrast", label: "Contrast", group: "light", description: "", params: [amount] },
  { id: "black_white", label: "Black & white", group: "color", description: "", params: [] },
  {
    id: "sharpen",
    label: "Sharpen",
    group: "detail",
    description: "",
    params: [
      { ...amount, min: 0, max: 300 },
      { ...amount, name: "radius", min: 0.5, max: 5, default: 1 },
    ],
  },
];

describe("edit document", () => {
  it("adds ops in catalogue order and drops them at their defaults", () => {
    let doc = setParam(EMPTY_DOC, SPECS, "contrast", "amount", 20);
    doc = setParam(doc, SPECS, "exposure", "ev", 0.5);
    expect(doc.ops.map((e) => e.id)).toEqual(["exposure", "contrast"]);
    doc = setParam(doc, SPECS, "contrast", "amount", 0);
    expect(doc.ops.map((e) => e.id)).toEqual(["exposure"]);
  });

  it("clamps values to the parameter range", () => {
    const doc = setParam(EMPTY_DOC, SPECS, "exposure", "ev", 9);
    expect(doc.ops[0]?.params.ev).toBe(4);
  });

  it("drops sharpen when its amount is zero even if the radius changed", () => {
    let doc = setParam(EMPTY_DOC, SPECS, "sharpen", "radius", 2);
    expect(doc.ops).toHaveLength(0);
    doc = setParam(doc, SPECS, "sharpen", "amount", 50);
    expect(doc.ops[0]?.params).toEqual({ amount: 50, radius: 1 });
  });

  it("toggles parameterless ops and hides disabled ones from rendering", () => {
    let doc = setToggle(EMPTY_DOC, SPECS, "black_white", true);
    expect(activeOps(doc)).toEqual({ black_white: {} });
    doc = setEnabled(doc, "black_white", false);
    expect(activeOps(doc)).toEqual({});
    expect(isEdited(doc)).toBe(true);
  });

  it("rotating the view four times returns to the start, crop included", () => {
    let doc = setCrop(EMPTY_DOC, { x: 0.1, y: 0.2, w: 0.5, h: 0.3 });
    doc = flipView(doc, "h");
    const start = doc.geometry;
    for (let i = 0; i < 4; i++) doc = rotateView(doc, 1);
    expect(doc.geometry).toEqual(start);
    expect(rotateView(rotateView(doc, 1), -1).geometry).toEqual(start);
  });

  it("rotates the crop with the view and swaps flips", () => {
    let doc = setCrop(EMPTY_DOC, { x: 0, y: 0, w: 0.5, h: 0.25 });
    doc = flipView(doc, "h");
    doc = rotateView(doc, 1);
    expect(doc.geometry.rotate).toBe(90);
    expect(doc.geometry.flip_h).toBe(false);
    expect(doc.geometry.flip_v).toBe(true);
    // Flipped: x 0.5..1, y 0..0.25. Rotated clockwise: x 0.75..1, y 0.5..1.
    expect(doc.geometry.crop).toEqual({ x: 0.75, y: 0.5, w: 0.25, h: 0.5 });
  });

  it("a full-frame crop is no crop", () => {
    expect(setCrop(EMPTY_DOC, { x: 0, y: 0, w: 1, h: 1 }).geometry.crop).toBeNull();
  });
});

describe("sizes match the server", () => {
  it("rounds halves to even like Python", () => {
    expect([0.5, 1.5, 2.5, 187.5, 2.4].map(roundHalfEven)).toEqual([0, 2, 2, 188, 2]);
  });

  it("computes crop boxes and output sizes", () => {
    expect(cropBox(100, 50, { x: 0.25, y: 0.5, w: 0.5, h: 0.5 })).toEqual([25, 25, 50, 25]);
    const geometry = { rotate: 90 as const, flip_h: false, flip_v: false, crop: null };
    expect(outputSize(640, 400, geometry)).toEqual([400, 640]);
    expect(plannedSize(400, 640, 300)).toEqual([188, 300]);
    expect(plannedSize(400, 640, null)).toEqual([400, 640]);
  });
});

describe("crop dragging", () => {
  const start = { x: 0.2, y: 0.2, w: 0.4, h: 0.4 };

  it("moves inside the image", () => {
    expect(dragRect(start, "move", 0.9, 0, null)).toEqual({ x: 0.6, y: 0.2, w: 0.4, h: 0.4 });
  });

  it("resizes from a corner and keeps a locked ratio", () => {
    const r = dragRect(start, "se", 0.2, 0.05, 1);
    expect(r.w).toBeCloseTo(r.h);
    expect(r.x).toBeCloseTo(0.2);
    expect(r.y).toBeCloseTo(0.2);
  });

  it("keeps the ratio when an edge pushes past the image", () => {
    const r = dragRect(start, "e", 0.6, 0, 2);
    expect(r.x + r.w).toBeLessThanOrEqual(1.000001);
    expect(r.w / r.h).toBeCloseTo(2);
  });

  it("fits a ratio inside the current crop", () => {
    const r = fitRatio({ x: 0, y: 0, w: 1, h: 1 }, 2);
    expect(r).toEqual({ x: 0, y: 0.25, w: 1, h: 0.5 });
  });
});
