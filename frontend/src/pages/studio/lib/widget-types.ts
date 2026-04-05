/**
 * Smart BI Agent — Studio Widget Types
 * Extracted from StudioPage.tsx monolith for modularity.
 */

import type { QueryResponse } from "@/types/query";

// ─── Core Types ──────────────────────────────────────────────────────────────

export type ColType = "numeric" | "text" | "date";
export type AggFunc = "SUM" | "COUNT" | "AVG" | "MIN" | "MAX" | "NONE";
export type WidgetSize = "sm" | "md" | "lg" | "xl" | "full";
export type WidgetMode = "fields" | "nlq";

export interface FieldAssignment {
  column: string;
  table: string;
  type: ColType;
  agg: AggFunc;
}

export interface CanvasWidget {
  id: string;
  title: string;
  mode: WidgetMode;
  xAxis: FieldAssignment | null;
  values: FieldAssignment[];
  legend: FieldAssignment | null;
  nlQuestion: string;
  chartType: string;
  size: WidgetSize;
  connectionId: string;
  result: QueryResponse | null;
  loading: boolean;
  error: string | null;
  generatedSql: string | null;
  aiInsight: string | null;
}

export interface StudioDashboard {
  id: string;
  title: string;
  description: string;
  connectionId: string;
  widgets: CanvasWidget[];
  columns: number;
  updatedAt: string;
}

// ─── Constants ───────────────────────────────────────────────────────────────

export const SIZES: Record<WidgetSize, { span: string; h: number }> = {
  sm:   { span: "col-span-12 sm:col-span-6 md:col-span-3", h: 220 },
  md:   { span: "col-span-12 sm:col-span-6 md:col-span-4", h: 300 },
  lg:   { span: "col-span-12 md:col-span-6", h: 360 },
  xl:   { span: "col-span-12 md:col-span-8", h: 400 },
  full: { span: "col-span-12", h: 440 },
};

export const AGGS: AggFunc[] = ["SUM", "COUNT", "AVG", "MIN", "MAX", "NONE"];

export const CHART_OPTIONS: { value: string; label: string }[] = [
  { value: "auto",           label: "Auto" },
  { value: "bar",            label: "Bar" },
  { value: "horizontal_bar", label: "H-Bar" },
  { value: "stacked_bar",    label: "Stack" },
  { value: "line",           label: "Line" },
  { value: "area",           label: "Area" },
  { value: "pie",            label: "Pie" },
  { value: "donut",          label: "Donut" },
  { value: "scatter",        label: "Scatter" },
  { value: "gauge",          label: "Gauge" },
  { value: "waterfall",      label: "Fall" },
  { value: "funnel",         label: "Funnel" },
  { value: "scorecard",      label: "KPI" },
  { value: "table",          label: "Table" },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

export function toColType(t: string): ColType {
  const s = t.toLowerCase();
  if (/int|numeric|decimal|float|double|real|money|serial|bigint/.test(s)) return "numeric";
  if (/date|time|timestamp/.test(s)) return "date";
  return "text";
}

export function defaultAgg(t: ColType): AggFunc {
  return t === "numeric" ? "SUM" : "COUNT";
}

export function newWidget(connectionId: string, n: number): CanvasWidget {
  return {
    id: crypto.randomUUID(),
    title: `Visual ${n}`,
    mode: "fields",
    xAxis: null,
    values: [],
    legend: null,
    nlQuestion: "",
    chartType: "auto",
    size: "md",
    connectionId,
    result: null,
    loading: false,
    error: null,
    generatedSql: null,
    aiInsight: null,
  };
}

// ─── Dashboard Serialization ─────────────────────────────────────────────────

export function serializeDashboard(d: StudioDashboard) {
  return {
    name: d.title,
    description: d.description,
    config: {
      title: d.title,
      description: d.description,
      columns: d.columns,
      connection_id: d.connectionId,
      widgets: d.widgets.map((w) => ({
        id: w.id,
        title: w.title,
        mode: w.mode,
        chart_type: w.chartType,
        size: w.size,
        connection_id: w.connectionId,
        x_axis: w.xAxis,
        values_fields: w.values,
        legend: w.legend,
        nl_question: w.nlQuestion,
        generated_sql: w.generatedSql,
      })),
    },
  };
}

export function deserializeWidgets(widgets: any[], fallbackConn: string): CanvasWidget[] {
  return (widgets || []).map((w: any) => ({
    id: w.id || crypto.randomUUID(),
    title: w.title || "Untitled",
    mode: w.mode || "fields",
    xAxis: w.x_axis || null,
    values: w.values_fields || [],
    legend: w.legend || null,
    nlQuestion: w.nl_question || "",
    chartType: w.chart_type || "auto",
    size: w.size || "md",
    connectionId: w.connection_id || fallbackConn,
    result: null,
    loading: false,
    error: null,
    generatedSql: w.generated_sql || null,
    aiInsight: null,
  }));
}
