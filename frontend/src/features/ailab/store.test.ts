import { describe, expect, it } from "vitest";
import { strokesFor, useAiLabStore } from "./store";

describe("erase strokes", () => {
  it("belong to the image they were painted on", () => {
    const { addStroke } = useAiLabStore.getState();
    addStroke("a", { points: [[0.5, 0.5]], radius: 0.02 });
    expect(strokesFor(useAiLabStore.getState(), "a")).toHaveLength(1);
    addStroke("b", { points: [[0.1, 0.1]], radius: 0.02 });
    expect(strokesFor(useAiLabStore.getState(), "a")).toHaveLength(0);
    expect(strokesFor(useAiLabStore.getState(), "b")).toHaveLength(1);
  });

  it("give selectors the same empty list each time, so React doesn't re-render forever", () => {
    const state = useAiLabStore.getState();
    expect(strokesFor(state, "none")).toBe(strokesFor(state, "none"));
  });
});
