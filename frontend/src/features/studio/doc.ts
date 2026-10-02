/**
 * The edit document, mirrored from backend/src/siqe/imaging/edits.py.
 *
 * Every helper is pure and returns a new document, so undo and redo are just snapshots.
 * Geometry is applied first (rotate clockwise, then flip, then crop in normalised
 * coordinates of the rotated and flipped image), then adjustments in catalogue order.
 */
import type { EditDocument, OpSpec } from "@/lib/api/client";

export type Rotation = 0 | 90 | 180 | 270;

export interface CropRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Geometry {
  rotate: Rotation;
  flip_h: boolean;
  flip_v: boolean;
  crop: CropRect | null;
}

export interface Entry {
  id: string;
  enabled: boolean;
  params: Record<string, number>;
}

export interface Doc {
  version: 1;
  geometry: Geometry;
  ops: Entry[];
}

/** Active ops keyed by id, the shape the renderer and the server pipeline consume. */
export type ActiveOps = Record<string, Record<string, number>>;

export const IDENTITY_GEOMETRY: Geometry = { rotate: 0, flip_h: false, flip_v: false, crop: null };
export const EMPTY_DOC: Doc = { version: 1, geometry: IDENTITY_GEOMETRY, ops: [] };

const FULL: CropRect = { x: 0, y: 0, w: 1, h: 1 };

export function fromServer(raw: EditDocument | Record<string, unknown> | undefined | null): Doc {
  const source = (raw ?? {}) as Partial<EditDocument>;
  const g = source.geometry;
  return {
    version: 1,
    geometry: {
      rotate: (g?.rotate ?? 0) as Rotation,
      flip_h: Boolean(g?.flip_h),
      flip_v: Boolean(g?.flip_v),
      crop: g?.crop ? { x: g.crop.x, y: g.crop.y, w: g.crop.w, h: g.crop.h } : null,
    },
    ops: (source.ops ?? []).map((e) => ({ id: e.id, enabled: e.enabled ?? true, params: { ...e.params } })),
  };
}

export function toServer(doc: Doc): EditDocument {
  return { version: 1, geometry: doc.geometry, ops: doc.ops };
}

export function specById(specs: readonly OpSpec[], id: string): OpSpec | undefined {
  return specs.find((s) => s.id === id);
}

export function entry(doc: Doc, id: string): Entry | undefined {
  return doc.ops.find((e) => e.id === id);
}

export function paramValue(doc: Doc, spec: OpSpec, name: string): number {
  const param = spec.params.find((p) => p.name === name);
  return entry(doc, spec.id)?.params[name] ?? param?.default ?? 0;
}

/** True when an op changes nothing, matching the server's rule for dropping it. */
export function isNoop(spec: OpSpec, params: Record<string, number>): boolean {
  if (spec.params.length === 0) return false;
  if (spec.id === "sharpen" || spec.id === "vignette") return (params.amount ?? 0) === 0;
  return spec.params.every((p) => (params[p.name] ?? p.default) === p.default);
}

function ordered(specs: readonly OpSpec[], ops: Entry[]): Entry[] {
  const order = new Map(specs.map((s, i) => [s.id, i]));
  return ops.slice().sort((a, b) => (order.get(a.id) ?? 99) - (order.get(b.id) ?? 99));
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function setParam(doc: Doc, specs: readonly OpSpec[], opId: string, name: string, value: number): Doc {
  const spec = specById(specs, opId);
  const param = spec?.params.find((p) => p.name === name);
  if (!spec || !param) return doc;
  const current = entry(doc, opId);
  const params: Record<string, number> = {};
  for (const p of spec.params) params[p.name] = current?.params[p.name] ?? p.default;
  params[name] = clamp(value, param.min, param.max);
  const rest = doc.ops.filter((e) => e.id !== opId);
  if (isNoop(spec, params)) return { ...doc, ops: rest };
  return { ...doc, ops: ordered(specs, [...rest, { id: opId, enabled: current?.enabled ?? true, params }]) };
}

/** On/off ops without parameters, such as black & white. */
export function setToggle(doc: Doc, specs: readonly OpSpec[], opId: string, on: boolean): Doc {
  const rest = doc.ops.filter((e) => e.id !== opId);
  if (!on) return { ...doc, ops: rest };
  if (entry(doc, opId)) return doc;
  return { ...doc, ops: ordered(specs, [...rest, { id: opId, enabled: true, params: {} }]) };
}

export function setEnabled(doc: Doc, opId: string, enabled: boolean): Doc {
  return { ...doc, ops: doc.ops.map((e) => (e.id === opId ? { ...e, enabled } : e)) };
}

export function removeOp(doc: Doc, opId: string): Doc {
  return { ...doc, ops: doc.ops.filter((e) => e.id !== opId) };
}

export function resetGroup(doc: Doc, specs: readonly OpSpec[], group: string): Doc {
  const ids = new Set(specs.filter((s) => s.group === group).map((s) => s.id));
  return { ...doc, ops: doc.ops.filter((e) => !ids.has(e.id)) };
}

export function activeOps(doc: Doc): ActiveOps {
  const out: ActiveOps = {};
  for (const e of doc.ops) if (e.enabled) out[e.id] = e.params;
  return out;
}

export function isEdited(doc: Doc): boolean {
  const g = doc.geometry;
  return doc.ops.length > 0 || g.rotate !== 0 || g.flip_h || g.flip_v || g.crop !== null;
}

// ---------------------------------------------------------------------------- geometry

/** Map a rectangle through a 90° clockwise rotation of the image it lives in. */
export function rotateRectCW(r: CropRect): CropRect {
  return { x: 1 - r.y - r.h, y: r.x, w: r.h, h: r.w };
}

function tidyCrop(r: CropRect | null): CropRect | null {
  if (!r) return null;
  const round = (v: number) => Math.round(v * 1e6) / 1e6;
  const out = { x: round(r.x), y: round(r.y), w: round(r.w), h: round(r.h) };
  if (out.x <= 0 && out.y <= 0 && out.w >= 1 && out.h >= 1) return null;
  return out;
}

/**
 * Rotate what the user sees by 90° (1 = clockwise, -1 = counter-clockwise).
 * Rotating a flipped view swaps the flip axes: rot90 ∘ flipH = flipV ∘ rot90.
 */
export function rotateView(doc: Doc, direction: 1 | -1): Doc {
  let g = doc.geometry;
  const turns = direction === 1 ? 1 : 3;
  for (let i = 0; i < turns; i++) {
    g = {
      rotate: ((g.rotate + 90) % 360) as Rotation,
      flip_h: g.flip_v,
      flip_v: g.flip_h,
      crop: g.crop ? rotateRectCW(g.crop) : null,
    };
  }
  return { ...doc, geometry: { ...g, crop: tidyCrop(g.crop) } };
}

export function flipView(doc: Doc, axis: "h" | "v"): Doc {
  const g = doc.geometry;
  const c = g.crop;
  return {
    ...doc,
    geometry: {
      ...g,
      flip_h: axis === "h" ? !g.flip_h : g.flip_h,
      flip_v: axis === "v" ? !g.flip_v : g.flip_v,
      crop: c
        ? axis === "h"
          ? tidyCrop({ ...c, x: 1 - c.x - c.w })
          : tidyCrop({ ...c, y: 1 - c.y - c.h })
        : null,
    },
  };
}

export function setCrop(doc: Doc, crop: CropRect | null): Doc {
  return { ...doc, geometry: { ...doc.geometry, crop: tidyCrop(crop) } };
}

export function resetGeometry(doc: Doc): Doc {
  return { ...doc, geometry: IDENTITY_GEOMETRY };
}

/** Python's round(): halves go to the even neighbour. Keeps sizes identical to the server's. */
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (Math.abs(diff - 0.5) < 1e-9) return floor % 2 === 0 ? floor : floor + 1;
  return Math.round(value);
}

/** Size of the rotated, flipped image (before crop). */
export function rotatedSize(width: number, height: number, rotate: Rotation): [number, number] {
  return rotate === 90 || rotate === 270 ? [height, width] : [width, height];
}

/** Pixel crop box, mirroring crop_box() in pipeline.py. */
export function cropBox(
  width: number,
  height: number,
  crop: CropRect | null,
): [number, number, number, number] {
  if (!crop) return [0, 0, width, height];
  const left = Math.min(width - 1, Math.max(0, roundHalfEven(crop.x * width)));
  const top = Math.min(height - 1, Math.max(0, roundHalfEven(crop.y * height)));
  const w = Math.max(1, Math.min(width - left, roundHalfEven(crop.w * width)));
  const h = Math.max(1, Math.min(height - top, roundHalfEven(crop.h * height)));
  return [left, top, w, h];
}

export function outputSize(width: number, height: number, geometry: Geometry): [number, number] {
  const [rw, rh] = rotatedSize(width, height, geometry.rotate);
  const [, , w, h] = cropBox(rw, rh, geometry.crop);
  return [w, h];
}

/** Final size after an optional longest-side limit, mirroring planned_size() in export.py. */
export function plannedSize(
  width: number,
  height: number,
  maxSide: number | null | undefined,
): [number, number] {
  const longest = Math.max(width, height);
  if (maxSide && longest > maxSide) {
    const scale = maxSide / longest;
    return [Math.max(1, roundHalfEven(width * scale)), Math.max(1, roundHalfEven(height * scale))];
  }
  return [width, height];
}

export function cropOrFull(geometry: Geometry): CropRect {
  return geometry.crop ?? FULL;
}
