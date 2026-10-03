import { create } from "zustand";
import type { ModelTask } from "@/lib/api/client";

/** One brush stroke, in units of the image: points are 0..1 of width and height, radius of width. */
export interface Stroke {
  points: [number, number][];
  radius: number;
}

export const BRUSHES = [
  { label: "Small", radius: 0.008 },
  { label: "Medium", radius: 0.018 },
  { label: "Large", radius: 0.035 },
] as const;

interface AiLabState {
  task: ModelTask;
  setTask: (task: ModelTask) => void;
  /** Strokes belong to one image; switching images starts a new mask. */
  maskAsset: string | null;
  strokes: Stroke[];
  radius: number;
  setRadius: (radius: number) => void;
  addStroke: (assetId: string, stroke: Stroke) => void;
  undo: () => void;
  clear: () => void;
}

export const useAiLabStore = create<AiLabState>((set) => ({
  task: "upscale",
  setTask: (task) => set({ task }),
  maskAsset: null,
  strokes: [],
  radius: BRUSHES[1].radius,
  setRadius: (radius) => set({ radius }),
  addStroke: (assetId, stroke) =>
    set((s) => ({
      maskAsset: assetId,
      strokes: s.maskAsset === assetId ? [...s.strokes, stroke] : [stroke],
    })),
  undo: () => set((s) => ({ strokes: s.strokes.slice(0, -1) })),
  clear: () => set({ strokes: [] }),
}));

/** Shared so selectors return the same empty list each time (a new one would re-render forever). */
const NO_STROKES: Stroke[] = [];

/** The strokes for ``assetId`` (none if they were painted on another image). */
export function strokesFor(state: Pick<AiLabState, "maskAsset" | "strokes">, assetId: string): Stroke[] {
  return state.maskAsset === assetId ? state.strokes : NO_STROKES;
}
