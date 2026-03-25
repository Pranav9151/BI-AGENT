/**
 * Smart BI Agent — Security Hooks
 * Phase 7 Session 9 | T9 (auto-clear), T48 (clipboard footer)
 *
 * useInactivityClear — clears sensitive data after 15min idle
 * copyWithFooter — adds confidentiality notice to clipboard copies
 * useRateLimitFeedback — shows toast when 429 received
 */

import { useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";

const INACTIVITY_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes

/**
 * Auto-clear callback after 15 minutes of inactivity.
 * Resets timer on mouse move, key press, click, scroll.
 */
export function useInactivityClear(onClear: () => void, enabled = true) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onClearRef = useRef(onClear);
  onClearRef.current = onClear;

  useEffect(() => {
    if (!enabled) return;

    const resetTimer = () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        onClearRef.current();
        toast.info("Query results cleared due to inactivity", {
          description: "Data is cleared after 15 minutes for security.",
        });
      }, INACTIVITY_TIMEOUT_MS);
    };

    const events = ["mousemove", "keydown", "click", "scroll", "touchstart"];
    events.forEach((e) => window.addEventListener(e, resetTimer, { passive: true }));
    resetTimer();

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      events.forEach((e) => window.removeEventListener(e, resetTimer));
    };
  }, [enabled]);
}

/**
 * Copy text to clipboard with confidentiality footer (T48).
 */
const FOOTER = "\n\n—\nConfidential — Smart BI Agent | Do not distribute without authorization.";

export function copyWithFooter(text: string, label = "Copied") {
  const withFooter = text + FOOTER;
  navigator.clipboard.writeText(withFooter).then(() => {
    toast.success(label);
  });
}

/**
 * Copy text WITHOUT footer (for SQL which users will paste into editors).
 */
export function copyPlain(text: string, label = "Copied") {
  navigator.clipboard.writeText(text).then(() => {
    toast.success(label);
  });
}