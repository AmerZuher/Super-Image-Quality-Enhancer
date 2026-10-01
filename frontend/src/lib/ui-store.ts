import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type Theme = "system" | "light" | "dark";

interface UiState {
  theme: Theme;
  paletteOpen: boolean;
  updatesOpen: boolean;
  setTheme: (theme: Theme) => void;
  setPaletteOpen: (open: boolean) => void;
  setUpdatesOpen: (open: boolean) => void;
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

/** Per-browser preferences. Only the theme is persisted. */
export const useUi = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      paletteOpen: false,
      updatesOpen: false,
      setTheme: (theme) => {
        applyTheme(theme);
        set({ theme });
      },
      setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
      setUpdatesOpen: (updatesOpen) => set({ updatesOpen }),
    }),
    {
      name: "siqe-ui",
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ theme: s.theme }),
    },
  ),
);
