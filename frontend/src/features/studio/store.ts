/**
 * Editor state for the open image: the edit document, undo and redo, and autosave.
 *
 * Changes with the same label in quick succession (a slider drag, arrow-key nudges) merge
 * into one history step. Saving is debounced; the server's copy is never pulled back over
 * what the user is doing.
 */
import { create } from "zustand";
import { saveEdits } from "./api";
import { type Doc, EMPTY_DOC, toServer } from "./doc";
import type { CompareMode } from "./gl/renderer";

const MERGE_MS = 900;
const SAVE_DELAY_MS = 500;
const HISTORY_LIMIT = 100;

export type SaveState = "saved" | "pending" | "saving" | "error";
export type Panel = "adjust" | "crop" | "export";

interface Step {
  doc: Doc;
  label: string;
}

interface EditorState {
  assetId: string | null;
  doc: Doc;
  past: Step[];
  future: Step[];
  lastLabel: string | null;
  lastAt: number;
  save: SaveState;
  saveError: string | null;
  panel: Panel;
  compare: CompareMode;
  split: number;
  holdBefore: boolean;
  /** Locked crop aspect ratio (width / height in output pixels), or null for free. */
  cropAspect: number | null;
  inspecting: boolean;

  load: (assetId: string, doc: Doc) => void;
  update: (label: string, change: (doc: Doc) => Doc) => void;
  undo: () => void;
  redo: () => void;
  setPanel: (panel: Panel) => void;
  setCompare: (mode: CompareMode) => void;
  setSplit: (split: number) => void;
  setHoldBefore: (hold: boolean) => void;
  setCropAspect: (aspect: number | null) => void;
  setInspecting: (open: boolean) => void;
  flush: () => Promise<void>;
}

let timer: ReturnType<typeof setTimeout> | undefined;
let inflight: Promise<void> | null = null;

async function persist(): Promise<void> {
  clearTimeout(timer);
  timer = undefined;
  const { assetId, doc, save } = useEditor.getState();
  if (!assetId || save === "saved") return;
  useEditor.setState({ save: "saving", saveError: null });
  try {
    await saveEdits(assetId, toServer(doc));
    // Only mark saved if nothing changed while the request was in flight.
    const now = useEditor.getState();
    if (now.assetId === assetId && now.doc === doc) useEditor.setState({ save: "saved" });
  } catch (error) {
    const now = useEditor.getState();
    if (now.assetId === assetId) {
      useEditor.setState({
        save: "error",
        saveError: error instanceof Error ? error.message : "The edits couldn't be saved.",
      });
    }
  }
}

function schedule(): void {
  clearTimeout(timer);
  timer = setTimeout(() => {
    inflight = persist().finally(() => {
      inflight = null;
    });
  }, SAVE_DELAY_MS);
}

export const useEditor = create<EditorState>((set, get) => ({
  assetId: null,
  doc: EMPTY_DOC,
  past: [],
  future: [],
  lastLabel: null,
  lastAt: 0,
  save: "saved",
  saveError: null,
  panel: "adjust",
  compare: "after",
  split: 0.5,
  holdBefore: false,
  cropAspect: null,
  inspecting: false,

  load: (assetId, doc) =>
    set({ assetId, doc, past: [], future: [], lastLabel: null, lastAt: 0, save: "saved", saveError: null }),

  update: (label, change) => {
    const state = get();
    const next = change(state.doc);
    if (next === state.doc || JSON.stringify(next) === JSON.stringify(state.doc)) return;
    const now = Date.now();
    const merge = state.lastLabel === label && now - state.lastAt < MERGE_MS && state.past.length > 0;
    set({
      doc: next,
      past: merge ? state.past : [...state.past, { doc: state.doc, label }].slice(-HISTORY_LIMIT),
      future: [],
      lastLabel: label,
      lastAt: now,
      save: "pending",
    });
    schedule();
  },

  undo: () => {
    const { past, future, doc } = get();
    const step = past.at(-1);
    if (!step) return;
    set({
      doc: step.doc,
      past: past.slice(0, -1),
      future: [{ doc, label: step.label }, ...future],
      lastLabel: null,
      save: "pending",
    });
    schedule();
  },

  redo: () => {
    const { past, future, doc } = get();
    const step = future[0];
    if (!step) return;
    set({
      doc: step.doc,
      past: [...past, { doc, label: step.label }],
      future: future.slice(1),
      lastLabel: null,
      save: "pending",
    });
    schedule();
  },

  setPanel: (panel) => set({ panel }),
  setCompare: (compare) => set({ compare }),
  setSplit: (split) => set({ split: Math.min(1, Math.max(0, split)) }),
  setHoldBefore: (holdBefore) => set({ holdBefore }),
  setCropAspect: (cropAspect) => set({ cropAspect }),
  setInspecting: (inspecting) => set({ inspecting }),

  /** Save now (before switching images or exporting). */
  flush: async () => {
    if (inflight) await inflight;
    if (get().save === "pending" || get().save === "error") await persist();
  },
}));
