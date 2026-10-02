import { create } from "zustand";
import type { RuleSet } from "@/lib/api/client";
import type { Sort } from "./api";

interface LibraryState {
  selected: string[];
  anchor: string | null;
  rules: RuleSet;
  sort: Sort;
  order: "asc" | "desc";
  /** Click: select one. Toggle (Ctrl/⌘): add or remove. Range (Shift): from the anchor in ``order``. */
  select: (id: string, mode: "one" | "toggle" | "range", order: string[]) => void;
  setSelected: (ids: string[]) => void;
  clear: () => void;
  setRules: (rules: RuleSet) => void;
  setSort: (sort: Sort, order: "asc" | "desc") => void;
}

export const useLibraryStore = create<LibraryState>((set) => ({
  selected: [],
  anchor: null,
  rules: { match: "all", rules: [] },
  sort: "added",
  order: "desc",
  select: (id, mode, order) =>
    set((s) => {
      if (mode === "one") return { selected: [id], anchor: id };
      if (mode === "toggle") {
        const has = s.selected.includes(id);
        return { selected: has ? s.selected.filter((x) => x !== id) : [...s.selected, id], anchor: id };
      }
      const from = s.anchor ? order.indexOf(s.anchor) : -1;
      const to = order.indexOf(id);
      if (from === -1 || to === -1) return { selected: [id], anchor: id };
      const [a, b] = from < to ? [from, to] : [to, from];
      return { selected: Array.from(new Set([...s.selected, ...order.slice(a, b + 1)])) };
    }),
  setSelected: (ids) => set({ selected: ids, anchor: ids.at(-1) ?? null }),
  clear: () => set({ selected: [], anchor: null }),
  setRules: (rules) => set({ rules }),
  setSort: (sort, order) => set({ sort, order }),
}));
