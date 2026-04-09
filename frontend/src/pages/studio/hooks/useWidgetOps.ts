/**
 * Smart BI Agent — useWidgetOps hook (Phase 12)
 * Widget CRUD, query execution, drag-reorder, AI dashboard generation.
 *
 * ★ KEY CHANGE: Field-well queries now use /query/structured endpoint
 *   instead of buildSql() + LLM passthrough. This means:
 *   - The BACKEND generates SQL (with proper JOINs from FK detection)
 *   - No more cross-join cartesian products
 *   - No LLM token consumption for field-well queries
 *   - Falls back to client buildSql() if structured endpoint fails
 *
 * ★ Anomaly detection receives xAxisType for proper classification.
 */

import { useState, useCallback } from "react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { toNumber } from "@/components/QueryResults";
import { detectAnomalies } from "@/lib/anomaly-detection";
import { buildSql } from "../lib/sql-builder";
import {
  type StudioDashboard,
  type CanvasWidget,
  type WidgetMode,
  type WidgetSize,
  newWidget,
} from "../lib/widget-types";
import type { QueryResponse, StructuredQueryResponse } from "@/types/query";

interface UseWidgetOpsArgs {
  dashboard: StudioDashboard;
  setDashboard: React.Dispatch<React.SetStateAction<StudioDashboard>>;
  selWidgetId: string | null;
  setSelWidgetId: (id: string | null) => void;
  setDrillDown: (d: { label: string; column: string } | null) => void;
}

export function useWidgetOps({
  dashboard,
  setDashboard,
  selWidgetId,
  setSelWidgetId,
  setDrillDown,
}: UseWidgetOpsArgs) {
  const [dragWidgetId, setDragWidgetId] = useState<string | null>(null);

  // ── CRUD ──────────────────────────────────────────────────────────────────

  const addWidget = useCallback(() => {
    const w = newWidget(dashboard.connectionId, dashboard.widgets.length + 1);
    setDashboard((d) => ({ ...d, widgets: [...d.widgets, w] }));
    setSelWidgetId(w.id);
  }, [dashboard.connectionId, dashboard.widgets.length, setDashboard, setSelWidgetId]);

  const removeWidget = useCallback(
    (id: string) => {
      setDashboard((d) => ({ ...d, widgets: d.widgets.filter((w) => w.id !== id) }));
      if (selWidgetId === id) setSelWidgetId(null);
    },
    [selWidgetId, setDashboard, setSelWidgetId]
  );

  const duplicateWidget = useCallback(
    (id: string) => {
      const src = dashboard.widgets.find((w) => w.id === id);
      if (!src) return;
      const clone: CanvasWidget = {
        ...src,
        id: crypto.randomUUID(),
        title: `${src.title} (copy)`,
        result: null,
        loading: false,
        error: null,
        aiInsight: null,
      };
      setDashboard((d) => {
        const idx = d.widgets.findIndex((w) => w.id === id);
        const widgets = [...d.widgets];
        widgets.splice(idx + 1, 0, clone);
        return { ...d, widgets };
      });
      setSelWidgetId(clone.id);
      toast.success("Widget duplicated");
    },
    [dashboard.widgets, setDashboard, setSelWidgetId]
  );

  const updateWidget = useCallback(
    (id: string, u: Partial<CanvasWidget>) => {
      setDashboard((d) => ({
        ...d,
        widgets: d.widgets.map((w) => (w.id === id ? { ...w, ...u } : w)),
      }));
    },
    [setDashboard]
  );

  // ── Drag Reorder ──────────────────────────────────────────────────────────

  const handleDragStart = useCallback((id: string) => setDragWidgetId(id), []);

  const handleDragOver = useCallback(
    (e: React.DragEvent, targetId: string) => {
      e.preventDefault();
      if (!dragWidgetId || dragWidgetId === targetId) return;
      setDashboard((d) => {
        const widgets = [...d.widgets];
        const fromIdx = widgets.findIndex((w) => w.id === dragWidgetId);
        const toIdx = widgets.findIndex((w) => w.id === targetId);
        if (fromIdx === -1 || toIdx === -1) return d;
        const [moved] = widgets.splice(fromIdx, 1);
        widgets.splice(toIdx, 0, moved);
        return { ...d, widgets };
      });
    },
    [dragWidgetId, setDashboard]
  );

  const handleDragEnd = useCallback(() => setDragWidgetId(null), []);

  // ── AI Insight Generation ─────────────────────────────────────────────────

  function generateInsight(
    columns: string[],
    rows: Record<string, unknown>[]
  ): string | null {
    if (rows.length === 0 || columns.length < 2) return null;
    const vals = rows
      .map((r) => toNumber(r[columns[1]]))
      .filter((v): v is number => v !== null);
    if (vals.length <= 1) return null;

    const total = vals.reduce((a, b) => a + b, 0);
    const max = Math.max(...vals);
    const maxIdx = vals.indexOf(max);
    const topLabel = String(rows[maxIdx]?.[columns[0]] ?? "");
    const pct = ((max / total) * 100).toFixed(1);
    const fmtTotal =
      total >= 1e6
        ? (total / 1e6).toFixed(1) + "M"
        : total >= 1e3
          ? (total / 1e3).toFixed(1) + "K"
          : total.toLocaleString();
    return `Top: ${topLabel} (${pct}% of total). ${vals.length} data points, total ${fmtTotal}.`;
  }

  // ── Query Execution ───────────────────────────────────────────────────────

  const runWidget = useCallback(
    async (wid: string) => {
      const w = dashboard.widgets.find((x) => x.id === wid);
      if (!w) return;
      const conn = w.connectionId || dashboard.connectionId;
      if (!conn) {
        toast.error("No connection");
        return;
      }

      setDashboard((d) => ({
        ...d,
        widgets: d.widgets.map((x) =>
          x.id === wid ? { ...x, loading: true, error: null } : x
        ),
      }));

      try {
        let columns: string[];
        let rows: Record<string, unknown>[];
        let sql: string | null = null;
        let rowCount: number;
        let truncated: boolean;

        if (w.mode === "nlq" && w.nlQuestion) {
          // ── AI Query Mode: use LLM endpoint ──
          const result = await api.post<QueryResponse>("/query/", {
            question: w.nlQuestion,
            connection_id: conn,
          });
          columns = result.columns;
          rows = result.rows;
          sql = result.sql;
          rowCount = result.row_count;
          truncated = result.truncated;
        } else {
          // ── Field Wells Mode: use structured query endpoint ──
          // ★ NEW: Send structured field specs to backend.
          // Backend detects FK relationships and generates proper JOINs.
          // No LLM tokens consumed. No cross-join risk.

          if (!w.xAxis && w.values.length === 0) {
            setDashboard((d) => ({
              ...d,
              widgets: d.widgets.map((x) =>
                x.id === wid ? { ...x, loading: false, error: "Assign fields first" } : x
              ),
            }));
            return;
          }

          try {
            // Build structured request
            const dimensions = [
              ...(w.xAxis ? [{ table: w.xAxis.table, column: w.xAxis.column, type: w.xAxis.type, agg: "NONE" }] : []),
              ...(w.legend ? [{ table: w.legend.table, column: w.legend.column, type: w.legend.type, agg: "NONE" }] : []),
            ];
            const measures = w.values.map((v) => ({
              table: v.table,
              column: v.column,
              type: v.type,
              agg: v.agg,
            }));

            const structuredResult = await api.post<StructuredQueryResponse>(
              "/query/structured",
              {
                connection_id: conn,
                dimensions,
                measures,
                filters: [],
                limit: 500,
              }
            );

            columns = structuredResult.columns;
            rows = structuredResult.rows;
            sql = structuredResult.sql;
            rowCount = structuredResult.row_count;
            truncated = structuredResult.truncated;

            if (structuredResult.joins_generated.length > 0) {
              toast.success(
                `Auto-joined ${structuredResult.tables_used.length} tables via FK relationships`,
                { duration: 4000 }
              );
            }
          } catch (structErr) {
            // ★ FALLBACK: If structured endpoint fails (e.g., old backend),
            // fall back to client-side SQL builder + LLM passthrough
            const build = buildSql(w);
            if (build.error) {
              setDashboard((d) => ({
                ...d,
                widgets: d.widgets.map((x) =>
                  x.id === wid ? { ...x, loading: false, error: build.error } : x
                ),
              }));
              return;
            }
            if (!build.sql) {
              setDashboard((d) => ({
                ...d,
                widgets: d.widgets.map((x) =>
                  x.id === wid ? { ...x, loading: false, error: "Assign fields first" } : x
                ),
              }));
              return;
            }
            sql = build.sql;
            const fallbackResult = await api.post<QueryResponse>("/query/", {
              question: `Execute: ${sql}`,
              connection_id: conn,
            });
            columns = fallbackResult.columns;
            rows = fallbackResult.rows;
            rowCount = fallbackResult.row_count;
            truncated = fallbackResult.truncated;
          }
        }

        // Build result in QueryResponse shape for compatibility
        const result: QueryResponse = {
          question: w.nlQuestion || "",
          sql: sql || "",
          columns,
          rows,
          row_count: rowCount,
          duration_ms: 0,
          truncated,
          conversation_id: "",
          message_id: "",
          provider_type: "",
          model: "",
          llm_latency_ms: 0,
          insight: null,
        };

        const insight = generateInsight(columns, rows);

        setDashboard((d) => ({
          ...d,
          widgets: d.widgets.map((x) =>
            x.id === wid
              ? { ...x, result, loading: false, error: null, generatedSql: sql, aiInsight: insight }
              : x
          ),
        }));

        // ★ Anomaly detection is limited to structured field-well visuals.
        // NLQ-generated widgets (Overview/Breakdown/Trend) often compare
        // sparse aggregate snapshots and can produce noisy % delta toasts.
        if (w.mode === "fields") {
          const xAxisType = w.xAxis?.type;
          const anomalies = detectAnomalies(result, w.title || "Visual", xAxisType);
          if (anomalies.length > 0) {
            const a = anomalies[0];
            if (a.severity === "critical") {
              toast.error(a.message, {
                duration: 8000,
                action: {
                  label: "Investigate",
                  onClick: () => setDrillDown({ label: a.label, column: a.column }),
                },
              });
            } else {
              toast(a.message, {
                duration: 6000,
                action: {
                  label: "Investigate",
                  onClick: () => setDrillDown({ label: a.label, column: a.column }),
                },
              });
            }
          }
        }
      } catch (err) {
        let msg = err instanceof ApiRequestError ? err.message : "Query failed";
        const lower = msg.toLowerCase();
        if (lower.includes("connect") || lower.includes("password") || lower.includes("authentication")) {
          msg += " — Check database credentials in Settings → Connections.";
        } else if (lower.includes("provider") || lower.includes("llm") || lower.includes("groq") || lower.includes("api key")) {
          msg += " — Check AI provider in Settings → LLM Providers.";
        } else if (lower.includes("circuit breaker")) {
          msg = "AI provider temporarily unavailable. Retry in 60 seconds.";
        }
        setDashboard((d) => ({
          ...d,
          widgets: d.widgets.map((x) =>
            x.id === wid ? { ...x, loading: false, error: msg } : x
          ),
        }));
      }
    },
    [dashboard, setDashboard, setDrillDown]
  );

  const refreshAll = useCallback(() => {
    dashboard.widgets.forEach((w) => {
      if (w.result || w.generatedSql || w.nlQuestion) runWidget(w.id);
    });
    if (dashboard.widgets.length > 0) {
      toast.success(`Refreshing ${dashboard.widgets.length} visuals…`);
    }
  }, [dashboard.widgets, runWidget]);

  // ── AI Dashboard Generation ───────────────────────────────────────────────

  const handleAiGenerate = useCallback(
    async (prompt: string) => {
      if (!prompt.trim() || !dashboard.connectionId) return;
      toast.success("AI is building your dashboard…");
      try {
        const questions = [
          prompt.trim(),
          `Give me a summary breakdown related to: ${prompt.trim()}`,
          `Show the trend over time for: ${prompt.trim()}`,
        ];
        const widgets: CanvasWidget[] = questions.map((q, i) => ({
          ...newWidget(dashboard.connectionId, i + 1),
          mode: "nlq" as WidgetMode,
          nlQuestion: q,
          title: i === 0 ? "Overview" : i === 1 ? "Breakdown" : "Trend",
          size: (i === 0 ? "lg" : "md") as WidgetSize,
          chartType: i === 0 ? "bar" : i === 1 ? "pie" : "area",
        }));
        setDashboard((d) => ({ ...d, title: prompt.trim().slice(0, 40), widgets }));
        for (const w of widgets) {
          setTimeout(() => runWidget(w.id), 500 * widgets.indexOf(w));
        }
      } catch (err) {
        const msg = err instanceof ApiRequestError ? err.message : "AI generation failed";
        toast.error(msg, { description: "Make sure you have an active AI provider and database connection configured.", duration: 8000 });
      }
    },
    [dashboard.connectionId, setDashboard, runWidget]
  );

  return {
    dragWidgetId,
    addWidget,
    removeWidget,
    duplicateWidget,
    updateWidget,
    handleDragStart,
    handleDragOver,
    handleDragEnd,
    runWidget,
    refreshAll,
    handleAiGenerate,
  };
}
