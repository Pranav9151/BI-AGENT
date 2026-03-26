/**
 * Smart BI Agent — Animation Utilities
 * Session 12 | World-class micro-interactions
 *
 * Pure CSS + React hooks — no external dependencies.
 * Performance: GPU-accelerated transforms only, no layout thrashing.
 */

import { useState, useEffect, useRef, useCallback } from "react";

// ─── Animate on Mount ───────────────────────────────────────────────────────

/**
 * Returns className that triggers on-mount animation.
 * Usage: <div className={useAnimateIn("fade-up", 100)}>
 */
export function useAnimateIn(variant: "fade-up" | "fade-in" | "slide-right" | "scale" = "fade-up", delayMs = 0) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setVisible(true), delayMs);
    return () => clearTimeout(t);
  }, [delayMs]);

  const base = "transition-all duration-500 ease-out";
  const hidden: Record<string, string> = {
    "fade-up": "opacity-0 translate-y-4",
    "fade-in": "opacity-0",
    "slide-right": "opacity-0 -translate-x-4",
    "scale": "opacity-0 scale-95",
  };
  const shown = "opacity-100 translate-y-0 translate-x-0 scale-100";

  return `${base} ${visible ? shown : hidden[variant]}`;
}

// ─── Staggered Children ─────────────────────────────────────────────────────

/**
 * Returns delay for staggered list animations.
 * Usage: items.map((item, i) => <div style={{ transitionDelay: stagger(i) }}>)
 */
export function stagger(index: number, baseMs = 50, maxMs = 400): string {
  return `${Math.min(index * baseMs, maxMs)}ms`;
}

// ─── Count Up Animation ─────────────────────────────────────────────────────

/**
 * Animates a number from 0 to target.
 * Usage: const display = useCountUp(1234, 1000);
 */
export function useCountUp(target: number, durationMs = 1200, startOnMount = true) {
  const [current, setCurrent] = useState(0);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (!startOnMount || target === 0) { setCurrent(target); return; }

    const start = performance.now();
    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / durationMs, 1);
      // Ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setCurrent(Math.round(eased * target));
      if (progress < 1) rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, durationMs, startOnMount]);

  return current;
}

// ─── Keyboard Shortcuts ─────────────────────────────────────────────────────

type ShortcutMap = Record<string, () => void>;

/**
 * Register global keyboard shortcuts.
 * Usage: useKeyboardShortcuts({ "ctrl+enter": handleSubmit, "ctrl+s": handleSave });
 */
export function useKeyboardShortcuts(shortcuts: ShortcutMap) {
  const shortcutsRef = useRef(shortcuts);
  shortcutsRef.current = shortcuts;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const parts: string[] = [];
      if (e.ctrlKey || e.metaKey) parts.push("ctrl");
      if (e.shiftKey) parts.push("shift");
      if (e.altKey) parts.push("alt");
      parts.push(e.key.toLowerCase());
      const combo = parts.join("+");

      const fn = shortcutsRef.current[combo];
      if (fn) { e.preventDefault(); fn(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
}

// ─── Intersection Observer (scroll reveal) ──────────────────────────────────

export function useScrollReveal(threshold = 0.1) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setVisible(true); obs.disconnect(); } },
      { threshold }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);

  return { ref, visible };
}

// ─── CSS Keyframes (inject once) ────────────────────────────────────────────

const KEYFRAMES = `
@keyframes sbi-pulse-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
  50% { box-shadow: 0 0 20px 4px rgba(59, 130, 246, 0.15); }
}
@keyframes sbi-shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
@keyframes sbi-float {
  0%, 100% { transform: translateY(0px); }
  50% { transform: translateY(-6px); }
}
@keyframes sbi-gradient-shift {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
.sbi-pulse-glow { animation: sbi-pulse-glow 3s ease-in-out infinite; }
.sbi-shimmer { background: linear-gradient(90deg, transparent 25%, rgba(255,255,255,0.05) 50%, transparent 75%); background-size: 200% 100%; animation: sbi-shimmer 2s infinite; }
.sbi-float { animation: sbi-float 4s ease-in-out infinite; }
.sbi-gradient-shift { background-size: 200% 200%; animation: sbi-gradient-shift 8s ease infinite; }
`;

let injected = false;
export function injectAnimations() {
  if (injected) return;
  const style = document.createElement("style");
  style.textContent = KEYFRAMES;
  document.head.appendChild(style);
  injected = true;
}