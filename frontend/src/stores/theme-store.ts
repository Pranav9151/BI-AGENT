/**
 * Smart BI Agent — Theme Store (Phase 11)
 * Dark / OLED deep dark mode toggle
 * Persists choice to localStorage
 */
import { create } from "zustand";

type ThemeMode = "dark" | "oled";

interface ThemeState {
  mode: ThemeMode;
  setMode: (m: ThemeMode) => void;
  toggle: () => void;
}

export const useThemeStore = create<ThemeState>((set) => ({
  mode: (() => {
    try {
      const stored = localStorage.getItem("sbi-theme");
      if (stored === "oled") return "oled" as ThemeMode;
    } catch {}
    return "dark" as ThemeMode;
  })(),

  setMode: (m) => {
    set({ mode: m });
    try { localStorage.setItem("sbi-theme", m); } catch {}
    applyTheme(m);
  },

  toggle: () => {
    set((s) => {
      const next = s.mode === "dark" ? "oled" : "dark";
      try { localStorage.setItem("sbi-theme", next); } catch {}
      applyTheme(next);
      return { mode: next };
    });
  },
}));

function applyTheme(mode: ThemeMode) {
  const root = document.documentElement;
  if (mode === "oled") {
    root.classList.add("oled-mode");
  } else {
    root.classList.remove("oled-mode");
  }
}

// Apply on load
try {
  const stored = localStorage.getItem("sbi-theme");
  if (stored === "oled") document.documentElement.classList.add("oled-mode");
} catch {}
