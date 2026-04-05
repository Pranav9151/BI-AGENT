/**
 * Smart BI Agent — useUndoRedo hook
 *
 * Provides undo/redo capability for any state.
 * Uses a history stack with configurable max depth.
 *
 * Usage:
 *   const { state, setState, undo, redo, canUndo, canRedo } = useUndoRedo(initialState);
 *
 * The hook stores snapshots on every setState call and allows
 * navigating backward/forward through the history.
 *
 * Designed for dashboard state where each widget add/remove/reorder
 * should be undoable.
 */

import { useState, useCallback, useRef, useMemo } from "react";

interface UndoRedoState<T> {
  past: T[];
  present: T;
  future: T[];
}

const MAX_HISTORY = 50;

export function useUndoRedo<T>(initialState: T) {
  const [history, setHistory] = useState<UndoRedoState<T>>({
    past: [],
    present: initialState,
    future: [],
  });

  // Batch flag to prevent recording intermediate states
  const batchRef = useRef(false);

  const setState = useCallback(
    (updater: T | ((prev: T) => T)) => {
      setHistory((h) => {
        const newPresent =
          typeof updater === "function"
            ? (updater as (prev: T) => T)(h.present)
            : updater;

        // Don't record if in a batch or if state hasn't changed
        if (batchRef.current || newPresent === h.present) {
          return { ...h, present: newPresent };
        }

        return {
          past: [...h.past, h.present].slice(-MAX_HISTORY),
          present: newPresent,
          future: [], // Clear future on new action
        };
      });
    },
    []
  );

  const undo = useCallback(() => {
    setHistory((h) => {
      if (h.past.length === 0) return h;
      const previous = h.past[h.past.length - 1];
      const newPast = h.past.slice(0, -1);
      return {
        past: newPast,
        present: previous,
        future: [h.present, ...h.future],
      };
    });
  }, []);

  const redo = useCallback(() => {
    setHistory((h) => {
      if (h.future.length === 0) return h;
      const next = h.future[0];
      const newFuture = h.future.slice(1);
      return {
        past: [...h.past, h.present],
        present: next,
        future: newFuture,
      };
    });
  }, []);

  /**
   * Execute a batch of state changes that count as a single undo step.
   * Only the final state is recorded in history.
   */
  const batch = useCallback(
    (fn: (set: (u: T | ((prev: T) => T)) => void) => void) => {
      // Save current state as the "before" snapshot
      setHistory((h) => {
        const beforeState = h.present;
        batchRef.current = true;

        // Execute the batch function — it may call setState multiple times
        // but none of those will be recorded individually
        fn((updater) => {
          setHistory((h2) => ({
            ...h2,
            present:
              typeof updater === "function"
                ? (updater as (prev: T) => T)(h2.present)
                : updater,
          }));
        });

        batchRef.current = false;

        // After batch, record a single history entry
        return {
          past: [...h.past, beforeState].slice(-MAX_HISTORY),
          present: h.present,
          future: [],
        };
      });
    },
    []
  );

  const canUndo = history.past.length > 0;
  const canRedo = history.future.length > 0;
  const historyLength = history.past.length;

  return {
    state: history.present,
    setState,
    undo,
    redo,
    canUndo,
    canRedo,
    historyLength,
    batch,
  };
}
