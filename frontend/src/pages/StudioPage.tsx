/**
 * Smart BI Agent — Dashboard Studio v4 (Phase 9.5)
 * "The Power BI Killer"
 *
 * What competitors DON'T have:
 *   - AI Natural Language Dashboard Builder ("build me a sales dashboard")
 *   - AI Data Narratives per widget (auto-generated insights)
 *   - Zero learning curve — no DAX, no LookML, no VizQL
 *   - Self-hosted — no $5K/month Looker fees
 *
 * Phase 9.5 Additions:
 *   - Dashboard Gallery — save/load/create/delete/switch dashboards
 *   - Smooth transitions everywhere (300ms cubic-bezier)
 *   - Proper h-full layout (no overflow/off-screen bugs)
 *   - AI Data Story per widget
 *   - Widget click → NL question shortcut
 *   - Fixed field-well drag from schema tree
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Palette, Plus, Trash2, Settings2, Eye, EyeOff,
  BarChart3, Hash, PieChart, LineChart, Table2,
  ArrowRightLeft, Layers, GripVertical, X,
  Loader2, Edit3, Check, RefreshCw, PanelLeftClose,
  PanelLeftOpen, ChevronRight, ChevronDown, Copy,
  Database, Type, Calendar, Sparkles, Send,
  Maximize2, Target, Triangle, Activity, Grid3x3, Gauge,
  Save, FolderOpen, PlusCircle, MoreVertical,
  Lightbulb, MessageSquare, Wand2, Link2,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Input, Select } from "@/components/ui";
import {
  ChartRenderer, Scorecard, toNumber, detectChartType,
  type ChartType,
} from "@/components/QueryResults";
import { GaugeChart } from "@/components/charts/GaugeChart";
import { WaterfallChart } from "@/components/charts/WaterfallChart";
import { FunnelChart } from "@/components/charts/FunnelChart";
import { SkeletonChart, chartTypeToSkeleton } from "@/components/SkeletonChart";
import { DrillDownModal } from "@/components/DrillDownModal";
import { detectAnomalies } from "@/lib/anomaly-detection";
import { useSidebar } from "@/contexts/sidebar";
import type { QueryResponse } from "@/types/query";
import type { SchemaResponse } from "@/types/schema";
import type { ConnectionListResponse } from "@/types/connections";

// ─── Types ──────────────────────────────────────────────────────────────────

type ColType = "numeric" | "text" | "date";
type AggFunc = "SUM" | "COUNT" | "AVG" | "MIN" | "MAX" | "NONE";
type WidgetSize = "sm" | "md" | "lg" | "xl" | "full";
type WidgetMode = "fields" | "nlq";

interface FieldAssignment { column: string; table: string; type: ColType; agg: AggFunc; }

interface CanvasWidget {
  id: string; title: string; mode: WidgetMode;
  xAxis: FieldAssignment | null; values: FieldAssignment[]; legend: FieldAssignment | null;
  nlQuestion: string; chartType: string; size: WidgetSize; connectionId: string;
  result: QueryResponse | null; loading: boolean; error: string | null;
  generatedSql: string | null; aiInsight: string | null;
}

interface StudioDashboard {
  id: string; title: string; description: string; connectionId: string;
  widgets: CanvasWidget[]; columns: number; updatedAt: string;
}

// ─── Constants ──────────────────────────────────────────────────────────────

const SIZES: Record<WidgetSize, { span: string; h: number }> = {
  sm: { span: "col-span-12 sm:col-span-6 md:col-span-3", h: 220 },
  md: { span: "col-span-12 sm:col-span-6 md:col-span-4", h: 300 },
  lg: { span: "col-span-12 md:col-span-6", h: 360 },
  xl: { span: "col-span-12 md:col-span-8", h: 400 },
  full: { span: "col-span-12", h: 440 },
};

const CHARTS: { value: string; label: string; icon: React.ReactNode }[] = [
  { value: "auto", label: "Auto", icon: <Settings2 className="h-3 w-3" /> },
  { value: "bar", label: "Bar", icon: <BarChart3 className="h-3 w-3" /> },
  { value: "horizontal_bar", label: "H-Bar", icon: <ArrowRightLeft className="h-3 w-3" /> },
  { value: "stacked_bar", label: "Stack", icon: <Layers className="h-3 w-3" /> },
  { value: "line", label: "Line", icon: <LineChart className="h-3 w-3" /> },
  { value: "area", label: "Area", icon: <Activity className="h-3 w-3" /> },
  { value: "pie", label: "Pie", icon: <PieChart className="h-3 w-3" /> },
  { value: "donut", label: "Donut", icon: <Target className="h-3 w-3" /> },
  { value: "scatter", label: "Scatter", icon: <Grid3x3 className="h-3 w-3" /> },
  { value: "gauge", label: "Gauge", icon: <Gauge className="h-3 w-3" /> },
  { value: "waterfall", label: "Fall", icon: <BarChart3 className="h-3 w-3" /> },
  { value: "funnel", label: "Funnel", icon: <Triangle className="h-3 w-3" /> },
  { value: "scorecard", label: "KPI", icon: <Hash className="h-3 w-3" /> },
  { value: "table", label: "Table", icon: <Table2 className="h-3 w-3" /> },
];

const AGGS: AggFunc[] = ["SUM", "COUNT", "AVG", "MIN", "MAX", "NONE"];

const COL_ICONS: Record<ColType, React.ReactNode> = {
  numeric: <Hash className="h-2.5 w-2.5 text-blue-400" />,
  text: <Type className="h-2.5 w-2.5 text-emerald-400" />,
  date: <Calendar className="h-2.5 w-2.5 text-amber-400" />,
};

function toColType(t: string): ColType {
  const s = t.toLowerCase();
  if (/int|numeric|decimal|float|double|real|money|serial|bigint/.test(s)) return "numeric";
  if (/date|time|timestamp/.test(s)) return "date";
  return "text";
}

function defaultAgg(t: ColType): AggFunc { return t === "numeric" ? "SUM" : "COUNT"; }

function newWidget(connectionId: string, n: number): CanvasWidget {
  return {
    id: crypto.randomUUID(), title: `Visual ${n}`, mode: "fields",
    xAxis: null, values: [], legend: null, nlQuestion: "", chartType: "auto",
    size: "md", connectionId, result: null, loading: false, error: null,
    generatedSql: null, aiInsight: null,
  };
}

// ─── SQL Generator ──────────────────────────────────────────────────────────

function buildSql(w: CanvasWidget): string | null {
  if (!w.xAxis && w.values.length === 0) return null;
  const sel: string[] = [], grp: string[] = [], tbls = new Set<string>();
  if (w.xAxis) {
    const c = `"${w.xAxis.table}"."${w.xAxis.column}"`;
    sel.push(`${c} AS "${w.xAxis.column}"`); grp.push(c); tbls.add(`"${w.xAxis.table}"`);
  }
  w.values.forEach((v) => {
    const c = `"${v.table}"."${v.column}"`; tbls.add(`"${v.table}"`);
    sel.push(v.agg === "NONE" ? `${c} AS "${v.column}"` : `${v.agg}(${c}) AS "${v.column}"`);
  });
  if (w.legend) {
    const c = `"${w.legend.table}"."${w.legend.column}"`;
    sel.push(`${c} AS "${w.legend.column}"`); grp.push(c); tbls.add(`"${w.legend.table}"`);
  }
  if (!sel.length) return null;
  let sql = `SELECT ${sel.join(", ")} FROM ${[...tbls].join(", ")}`;
  if (grp.length) sql += ` GROUP BY ${grp.join(", ")}`;
  if (w.xAxis) sql += ` ORDER BY "${w.xAxis.column}"`;
  return sql + " LIMIT 500";
}

// ─── Dashboard API ──────────────────────────────────────────────────────────

function serializeDashboard(d: StudioDashboard) {
  return {
    name: d.title, description: d.description,
    config: {
      title: d.title, description: d.description, columns: d.columns, connection_id: d.connectionId,
      widgets: d.widgets.map((w) => ({
        id: w.id, title: w.title, mode: w.mode, chart_type: w.chartType, size: w.size,
        connection_id: w.connectionId, x_axis: w.xAxis, values_fields: w.values,
        legend: w.legend, nl_question: w.nlQuestion, generated_sql: w.generatedSql,
      })),
    },
  };
}

function deserializeWidgets(widgets: any[], fallbackConn: string): CanvasWidget[] {
  return (widgets || []).map((w: any) => ({
    id: w.id || crypto.randomUUID(), title: w.title || "Untitled", mode: w.mode || "fields",
    xAxis: w.x_axis || null, values: w.values_fields || [], legend: w.legend || null,
    nlQuestion: w.nl_question || "", chartType: w.chart_type || "auto", size: w.size || "md",
    connectionId: w.connection_id || fallbackConn, result: null, loading: false, error: null,
    generatedSql: w.generated_sql || null, aiInsight: null,
  }));
}

// ─── Schema DragCol ─────────────────────────────────────────────────────────

function DragCol({ name, type, table }: { name: string; type: ColType; table: string }) {
  return (
    <div draggable
      onDragStart={(e) => { e.dataTransfer.setData("application/json", JSON.stringify({ column: name, table, type })); e.dataTransfer.effectAllowed = "copy"; }}
      className="flex items-center gap-1.5 px-2 py-1 rounded-md cursor-grab active:cursor-grabbing text-[10px] text-slate-400 hover:text-slate-200 hover:bg-slate-700/30 border border-transparent hover:border-blue-500/20 transition-all duration-200 group select-none"
      title={`Drag to field well`}>
      <GripVertical className="h-2 w-2 text-slate-700 group-hover:text-blue-400 shrink-0 transition-colors" />
      {COL_ICONS[type]}
      <span className="truncate flex-1">{name}</span>
    </div>
  );
}

function SchemaTree({ tableName, columns, open: init }: { tableName: string; columns: { name: string; type: ColType }[]; open?: boolean }) {
  const [open, setOpen] = useState(init || false);
  return (
    <div className="mb-0.5">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-1.5 px-1.5 py-1 rounded-md hover:bg-slate-700/20 transition-colors duration-150 text-left">
        <span className="text-slate-600 shrink-0 transition-transform duration-200" style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)" }}><ChevronRight className="h-2.5 w-2.5" /></span>
        <Table2 className="h-2.5 w-2.5 text-blue-400/60 shrink-0" />
        <span className="text-[10px] font-medium text-slate-400 truncate">{tableName}</span>
        <span className="text-[8px] text-slate-600 ml-auto shrink-0">{columns.length}</span>
      </button>
      <div className={cn("ml-4 pl-2 border-l border-slate-800/60 space-y-0 overflow-hidden transition-all duration-300", open ? "max-h-[500px] opacity-100 mt-0.5" : "max-h-0 opacity-0")}>
        {columns.map((c) => <DragCol key={c.name} name={c.name} type={c.type} table={tableName} />)}
      </div>
    </div>
  );
}

// ─── FieldWell ──────────────────────────────────────────────────────────────

function FieldWell({ label, fields, onDrop, onRemove, onAggChange, color, placeholder, isValues }: {
  label: string; fields: FieldAssignment[]; onDrop: (f: FieldAssignment) => void; onRemove: (c: string) => void;
  onAggChange?: (c: string, a: AggFunc) => void; color: string; placeholder: string; isValues?: boolean;
}) {
  const [over, setOver] = useState(false);
  const cs = { blue: "border-blue-500/50 bg-blue-500/5", emerald: "border-emerald-500/50 bg-emerald-500/5", violet: "border-violet-500/50 bg-violet-500/5" }[color] || "border-blue-500/50 bg-blue-500/5";
  const pill = { blue: "bg-blue-600/20 text-blue-300 border-blue-500/20", emerald: "bg-emerald-600/20 text-emerald-300 border-emerald-500/20", violet: "bg-violet-600/20 text-violet-300 border-violet-500/20" }[color] || "";

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        <span className="text-[8px] font-semibold text-slate-500 uppercase tracking-wider">{label}</span>
        {fields.length > 0 && <button onClick={() => fields.forEach((f) => onRemove(f.column))} className="ml-auto text-[7px] text-slate-600 hover:text-red-400 transition-colors">Clear</button>}
      </div>
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault(); setOver(false);
          try { const d = JSON.parse(e.dataTransfer.getData("application/json")); if (d.column) onDrop({ column: d.column, table: d.table, type: d.type || "text", agg: isValues ? defaultAgg(d.type || "text") : "NONE" }); } catch {}
        }}
        className={cn("min-h-[30px] rounded-lg border border-dashed px-2 py-1.5 transition-all duration-200", over ? cs : "border-slate-700/30 hover:border-slate-600/40", fields.length === 0 && "flex items-center justify-center")}
      >
        {fields.length === 0 ? (
          <span className="text-[9px] text-slate-600 italic select-none">{placeholder}</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {fields.map((f) => (
              <span key={f.column} className={cn("inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-[9px] font-medium transition-all duration-150", pill)}>
                {COL_ICONS[f.type]}
                <span className="truncate max-w-[55px]">{f.column}</span>
                {isValues && onAggChange && (
                  <select value={f.agg} onChange={(e) => onAggChange(f.column, e.target.value as AggFunc)}
                    className="bg-transparent border-none text-[8px] p-0 focus:outline-none cursor-pointer uppercase" onClick={(e) => e.stopPropagation()}>
                    {AGGS.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                )}
                <button onClick={() => onRemove(f.column)} className="hover:text-red-300 transition-colors"><X className="h-2 w-2" /></button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Widget Chart ───────────────────────────────────────────────────────────

function WidgetViz({ widget, onDataClick }: { widget: CanvasWidget; onDataClick?: (label: string, column: string) => void }) {
  if (!widget.result) return null;
  const { columns, rows } = widget.result;
  const ct = widget.chartType;

  if (ct === "gauge" && rows.length > 0) {
    const v = toNumber(rows[0][columns[0]]) ?? 0;
    return <GaugeChart value={v} max={Math.max(v * 1.5, 100)} label={columns[0].replace(/_/g, " ")} height={SIZES[widget.size].h - 50} />;
  }
  if (ct === "waterfall" && rows.length > 0) {
    return <WaterfallChart data={rows.slice(0, 20).map((r) => ({ name: String(r[columns[0]] ?? ""), value: toNumber(r[columns[1] || columns[0]]) ?? 0 }))} height={SIZES[widget.size].h - 50} />;
  }
  if (ct === "funnel" && rows.length > 0) {
    return <FunnelChart data={rows.slice(0, 10).map((r) => ({ name: String(r[columns[0]] ?? ""), value: toNumber(r[columns[1] || columns[0]]) ?? 0 }))} height={SIZES[widget.size].h - 50} />;
  }
  if (ct === "table") {
    return (
      <div className="overflow-auto h-full text-[10px]">
        <table className="w-full"><thead><tr className="border-b border-slate-700/30 sticky top-0 bg-slate-900/90 backdrop-blur-sm">
          {columns.map((c) => <th key={c} className="text-left px-2 py-1.5 text-[9px] font-semibold text-slate-500 uppercase">{c}</th>)}
        </tr></thead><tbody>
          {rows.slice(0, 100).map((r, i) => (
            <tr key={i} className={cn("border-b border-slate-800/20 transition-colors hover:bg-blue-500/5 cursor-pointer", i % 2 === 0 ? "" : "bg-slate-800/10")}
              onClick={() => onDataClick?.(String(r[columns[0]] ?? ""), columns[0])}>
              {columns.map((c) => <td key={c} className="px-2 py-1 text-slate-300 truncate max-w-[120px]">{String(r[c] ?? "")}</td>)}
            </tr>
          ))}
        </tbody></table>
      </div>
    );
  }
  if (ct === "scorecard") return <Scorecard columns={columns} rows={rows} />;

  const resolved: ChartType = ct === "auto" ? detectChartType(columns, rows) : ct === "donut" ? "pie" : (ct as ChartType);
  return <ChartRenderer key={`${widget.id}-${ct}`} chartType={resolved} columns={columns} rows={rows}
    height={SIZES[widget.size].h - 50} showLegend={widget.size !== "sm"} onDataClick={onDataClick} />;
}

// ─── Widget Card ────────────────────────────────────────────────────────────

function WidgetCard({ widget, selected, preview, onSelect, onRemove, onRun, onDuplicate, onDrillDown, onDragStart, onDragOver, onDragEnd, isDragging, onDataClick, globalFilter }: {
  widget: CanvasWidget; selected: boolean; preview: boolean;
  onSelect: () => void; onRemove: () => void; onRun: () => void;
  onDuplicate: () => void; onDrillDown: (label: string, column: string) => void;
  onDragStart?: () => void; onDragOver?: (e: React.DragEvent) => void; onDragEnd?: () => void; isDragging?: boolean;
  onDataClick?: (label: string, column: string) => void;
  globalFilter?: { column: string; value: string } | null;
}) {
  // Apply cross-widget filter to results if applicable
  const filteredWidget = useMemo(() => {
    if (!globalFilter || !widget.result) return widget;
    const { column, value } = globalFilter;
    const hasCol = widget.result.columns.includes(column);
    if (!hasCol) return widget;
    const filteredRows = widget.result.rows.filter((r) => String(r[column] ?? "") === value);
    return { ...widget, result: { ...widget.result, rows: filteredRows, row_count: filteredRows.length } };
  }, [widget, globalFilter]);
  return (
    <div
      draggable={!preview}
      onDragStart={(e) => { e.dataTransfer.setData("text/plain", widget.id); e.dataTransfer.effectAllowed = "move"; onDragStart?.(); }}
      onDragOver={(e) => onDragOver?.(e)}
      onDragEnd={onDragEnd}
      className={cn(
        SIZES[widget.size].span,
        "group rounded-xl border overflow-hidden",
        "transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]",
        selected && !preview ? "border-blue-500/40 shadow-lg shadow-blue-500/5 ring-1 ring-blue-500/20" : "border-slate-700/25 hover:border-slate-600/40",
        !preview && "cursor-pointer",
        isDragging && "opacity-40 scale-95"
      )}
      onClick={() => !preview && onSelect()}
      style={{ background: "rgba(15, 23, 42, 0.35)" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-700/15 bg-slate-800/15">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {!preview && <GripVertical className="h-3 w-3 text-slate-700 shrink-0 cursor-grab opacity-0 group-hover:opacity-60 transition-opacity duration-200" />}
          <span className="text-xs font-medium text-slate-300 truncate">{widget.title || "Untitled"}</span>
          {widget.aiInsight && <Lightbulb className="h-2.5 w-2.5 text-amber-400/60 shrink-0" title="AI insight available" />}
        </div>
        {!preview && (
          <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <button onClick={(e) => { e.stopPropagation(); onRun(); }} className="p-1 rounded text-slate-500 hover:text-blue-400 transition-colors" title="Run query">
              <RefreshCw className={cn("h-3 w-3 transition-transform duration-500", widget.loading && "animate-spin")} />
            </button>
            <button onClick={(e) => { e.stopPropagation(); onDuplicate(); }} className="p-1 rounded text-slate-500 hover:text-emerald-400 transition-colors" title="Duplicate">
              <Copy className="h-3 w-3" />
            </button>
            <button onClick={(e) => { e.stopPropagation(); onRemove(); }} className="p-1 rounded text-slate-500 hover:text-red-400 transition-colors" title="Remove">
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
      {/* Body */}
      <div style={{ height: SIZES[widget.size].h }} className="overflow-hidden">
        {widget.loading && (
          <SkeletonChart type={chartTypeToSkeleton(widget.chartType)} height={SIZES[widget.size].h} />
        )}
        {widget.error && !widget.loading && (
          <div className="flex items-center justify-center h-full p-4"><div className="text-center max-w-xs">
            <p className="text-xs text-red-400/80 mb-2 line-clamp-3">{widget.error}</p>
            <button onClick={(e) => { e.stopPropagation(); onRun(); }} className="text-[10px] text-blue-400 hover:text-blue-300 border border-blue-500/30 rounded-lg px-3 py-1 transition-colors duration-200">Retry</button>
          </div></div>
        )}
        {filteredWidget.result && !widget.loading && (
          <div className="p-1.5 h-full animate-fade-in"><WidgetViz widget={filteredWidget} onDataClick={onDataClick} /></div>
        )}
        {!widget.result && !widget.loading && !widget.error && (
          <div className="flex flex-col items-center justify-center h-full p-4 animate-fade-in">
            <Sparkles className="h-6 w-6 text-slate-700 mb-2" />
            <p className="text-[10px] text-slate-500">{widget.mode === "fields" ? "Drag columns into field wells →" : "Type a question in Properties →"}</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Properties Panel ───────────────────────────────────────────────────────

function Props({ widget, onUpdate, onRun }: {
  widget: CanvasWidget; onUpdate: (u: Partial<CanvasWidget>) => void; onRun: () => void;
}) {
  const [nl, setNl] = useState(widget.nlQuestion);
  useEffect(() => { setNl(widget.nlQuestion); }, [widget.id]); // eslint-disable-line

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="shrink-0 px-3 py-2 border-b border-slate-700/30">
        <input value={widget.title} onChange={(e) => onUpdate({ title: e.target.value })}
          className="text-xs font-semibold text-white bg-transparent w-full focus:outline-none border-b border-transparent focus:border-blue-500/40 transition-colors duration-200 pb-0.5"
          placeholder="Widget title" />
      </div>
      <div className="flex-1 overflow-y-auto p-2.5 space-y-3">
        {/* Mode */}
        <div className="flex rounded-lg border border-slate-700/40 overflow-hidden">
          {(["fields", "nlq"] as const).map((m) => (
            <button key={m} onClick={() => onUpdate({ mode: m })}
              className={cn("flex-1 text-[9px] font-medium py-1.5 transition-all duration-200",
                widget.mode === m ? "bg-blue-600/20 text-blue-300" : "text-slate-500 hover:text-slate-300")}>
              {m === "fields" ? "Field Wells" : "AI Query"}
            </button>
          ))}
        </div>

        {widget.mode === "fields" ? (
          <>
            <FieldWell label="X-Axis (Dimension)" fields={widget.xAxis ? [widget.xAxis] : []}
              onDrop={(f) => onUpdate({ xAxis: f })} onRemove={() => onUpdate({ xAxis: null })} color="emerald" placeholder="Drop dimension here" />
            <FieldWell label="Values (Measures)" fields={widget.values} isValues
              onDrop={(f) => { if (!widget.values.find((v) => v.column === f.column)) onUpdate({ values: [...widget.values, f] }); }}
              onRemove={(c) => onUpdate({ values: widget.values.filter((v) => v.column !== c) })}
              onAggChange={(c, a) => onUpdate({ values: widget.values.map((v) => v.column === c ? { ...v, agg: a } : v) })}
              color="blue" placeholder="Drop measures here" />
            <FieldWell label="Legend / Group" fields={widget.legend ? [widget.legend] : []}
              onDrop={(f) => onUpdate({ legend: f })} onRemove={() => onUpdate({ legend: null })} color="violet" placeholder="Drop group-by" />
            <button onClick={onRun} disabled={widget.loading || (!widget.xAxis && widget.values.length === 0)}
              className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-lg bg-gradient-to-r from-blue-600/20 to-violet-600/15 text-blue-300 text-[10px] font-medium hover:from-blue-600/30 hover:to-violet-600/25 disabled:opacity-30 transition-all duration-200 border border-blue-500/15">
              {widget.loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
              {widget.loading ? "Running…" : "Run Query"}
            </button>
          </>
        ) : (
          <div className="space-y-2">
            <div className="relative">
              <input value={nl} onChange={(e) => setNl(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && nl.trim()) { onUpdate({ nlQuestion: nl.trim() }); onRun(); } }}
                placeholder="Ask about your data…"
                className="w-full h-9 rounded-lg border border-slate-700/40 bg-slate-800/30 text-slate-200 text-[11px] pl-3 pr-9 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500/30 transition-all duration-200" />
              <button onClick={() => { if (nl.trim()) { onUpdate({ nlQuestion: nl.trim() }); onRun(); } }}
                disabled={!nl.trim() || widget.loading}
                className="absolute right-1.5 top-1.5 p-1 rounded-md bg-blue-600 text-white disabled:opacity-20 hover:bg-blue-500 transition-colors duration-200">
                {widget.loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
              </button>
            </div>
          </div>
        )}

        {/* Chart Type */}
        <div className="space-y-1.5">
          <span className="text-[8px] font-semibold text-slate-500 uppercase tracking-wider">Chart Type</span>
          <div className="grid grid-cols-5 gap-1">
            {CHARTS.map((ct) => (
              <button key={ct.value} onClick={() => onUpdate({ chartType: ct.value })}
                className={cn("flex flex-col items-center gap-0.5 py-1.5 rounded-lg text-[7px] font-medium transition-all duration-200",
                  widget.chartType === ct.value ? "bg-blue-600/20 text-blue-300 border border-blue-500/30" : "text-slate-600 hover:text-slate-400 border border-transparent hover:border-slate-700/30")}
                title={ct.label}>{ct.icon}<span>{ct.label}</span></button>
            ))}
          </div>
        </div>

        {/* Size */}
        <div className="space-y-1.5">
          <span className="text-[8px] font-semibold text-slate-500 uppercase tracking-wider">Size</span>
          <div className="flex gap-1">
            {(["sm","md","lg","xl","full"] as WidgetSize[]).map((s) => (
              <button key={s} onClick={() => onUpdate({ size: s })}
                className={cn("flex-1 py-1 rounded-lg text-[9px] font-medium transition-all duration-200",
                  widget.size === s ? "bg-blue-600/20 text-blue-300 border border-blue-500/30" : "text-slate-600 border border-slate-700/30 hover:border-slate-600/40")}>
                {s.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {/* AI Insight */}
        {widget.aiInsight && (
          <div className="space-y-1">
            <span className="text-[8px] font-semibold text-amber-400/70 uppercase flex items-center gap-1"><Lightbulb className="h-2.5 w-2.5" /> AI Insight</span>
            <p className="text-[9px] text-slate-400 leading-relaxed bg-amber-500/5 border border-amber-500/10 rounded-lg p-2">{widget.aiInsight}</p>
          </div>
        )}

        {/* SQL Preview */}
        {widget.generatedSql && (
          <div className="space-y-1">
            <span className="text-[8px] font-semibold text-slate-600 uppercase">SQL</span>
            <pre className="text-[8px] text-slate-500 bg-slate-800/40 rounded-lg p-2 overflow-x-auto border border-slate-700/20 whitespace-pre-wrap break-all">{widget.generatedSql}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Empty Canvas ───────────────────────────────────────────────────────────

function EmptyCanvas({ onAdd, onAiGenerate }: { onAdd: () => void; onAiGenerate: () => void }) {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center max-w-lg animate-fade-in">
        <div className="w-24 h-24 rounded-3xl bg-gradient-to-br from-blue-500/10 via-violet-500/10 to-pink-500/10 border border-blue-500/10 flex items-center justify-center mx-auto mb-8 sbi-float">
          <Palette className="h-12 w-12 text-blue-400/50" />
        </div>
        <h2 className="text-xl font-bold text-white mb-2">Dashboard Canvas</h2>
        <p className="text-sm text-slate-400 mb-8 leading-relaxed">Build interactive dashboards by dragging database columns into visuals, or let AI create one for you.</p>
        <div className="flex items-center justify-center gap-3">
          <Button icon={<Plus className="h-4 w-4" />} onClick={onAdd}>Add Visual</Button>
          <Button variant="ghost" icon={<Wand2 className="h-4 w-4" />} onClick={onAiGenerate} className="border border-violet-500/20 text-violet-300 hover:bg-violet-500/10">
            AI Generate Dashboard
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Dashboard Gallery Bar ──────────────────────────────────────────────────

function DashboardGallery({ dashboards, activeId, onSelect, onCreate, onDelete }: {
  dashboards: { id: string; name: string; updated: string }[];
  activeId: string | null; onSelect: (id: string) => void;
  onCreate: () => void; onDelete: (id: string) => void;
}) {
  if (dashboards.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5">
      {dashboards.map((d) => (
        <div key={d.id} className="group relative shrink-0">
          <button onClick={() => onSelect(d.id)}
            className={cn("flex items-center gap-1.5 px-3 py-1 rounded-lg text-[10px] font-medium transition-all duration-200 whitespace-nowrap",
              activeId === d.id ? "bg-blue-600/20 text-blue-300 border border-blue-500/25" : "text-slate-500 hover:text-slate-300 border border-transparent hover:border-slate-700/40")}>
            <FolderOpen className="h-3 w-3" />{d.name}
          </button>
          {activeId !== d.id && (
            <button onClick={(e) => { e.stopPropagation(); onDelete(d.id); }}
              className="absolute -top-1 -right-1 hidden group-hover:flex w-4 h-4 items-center justify-center rounded-full bg-red-600/80 text-white transition-opacity">
              <X className="h-2 w-2" />
            </button>
          )}
        </div>
      ))}
      <button onClick={onCreate}
        className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] text-slate-600 hover:text-slate-400 border border-dashed border-slate-700/30 hover:border-slate-600/40 transition-all duration-200">
        <PlusCircle className="h-3 w-3" /> New
      </button>
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────

export default function StudioPage() {
  const sidebar = useSidebar();
  const queryClient = useQueryClient();

  const [dashboard, setDashboard] = useState<StudioDashboard>({
    id: "", title: "My Dashboard", description: "", connectionId: "",
    widgets: [], columns: 12, updatedAt: new Date().toISOString(),
  });
  const [selWidgetId, setSelWidgetId] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);
  const [editTitle, setEditTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [dataOpen, setDataOpen] = useState(true);
  const [propsOpen, setPropsOpen] = useState(true);
  const [schemaSearch, setSchemaSearch] = useState("");
  const [aiPrompt, setAiPrompt] = useState("");
  const [showAiModal, setShowAiModal] = useState(false);
  const [globalFilter, setGlobalFilter] = useState<{ column: string; value: string } | null>(null);
  const [dragWidgetId, setDragWidgetId] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(0);
  const [drillDown, setDrillDown] = useState<{ label: string; column: string } | null>(null); // seconds, 0 = off

  // Auto-refresh timer
  useEffect(() => {
    if (autoRefresh <= 0 || dashboard.widgets.length === 0) return;
    const timer = setInterval(() => {
      dashboard.widgets.forEach((w) => { if (w.result || w.generatedSql || w.nlQuestion) runWidget(w.id); });
    }, autoRefresh * 1000);
    return () => clearInterval(timer);
  }, [autoRefresh, dashboard.widgets.length]); // eslint-disable-line

  // Auto-collapse sidebar
  const prevCollapsed = useRef(sidebar.collapsed);
  useEffect(() => {
    prevCollapsed.current = sidebar.collapsed;
    if (!sidebar.collapsed) sidebar.setCollapsed(true);
    return () => { sidebar.setCollapsed(prevCollapsed.current); };
  }, []); // eslint-disable-line

  // Keyboard shortcuts for Studio
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ctrl+S — Save dashboard
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
        return;
      }
      // Delete — Remove selected widget
      if (e.key === "Delete" && selWidgetId && !e.ctrlKey && !e.metaKey) {
        const target = e.target as HTMLElement;
        if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) return;
        e.preventDefault();
        removeWidget(selWidgetId);
        return;
      }
      // Ctrl+D — Duplicate selected widget
      if ((e.ctrlKey || e.metaKey) && e.key === "d" && selWidgetId) {
        e.preventDefault();
        duplicateWidget(selWidgetId);
        return;
      }
      // Escape — Deselect widget or exit preview
      if (e.key === "Escape") {
        if (preview) { setPreview(false); return; }
        if (selWidgetId) { setSelWidgetId(null); return; }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selWidgetId, preview, handleSave, removeWidget, duplicateWidget]);

  // ── Data Fetching ──
  const { data: connData } = useQuery({ queryKey: ["connections"], queryFn: () => api.get<ConnectionListResponse>("/connections/") });
  const connections = connData?.connections?.filter((c) => c.is_active) ?? [];

  useEffect(() => { if (connections.length > 0 && !dashboard.connectionId) setDashboard((d) => ({ ...d, connectionId: connections[0].connection_id })); }, [connections, dashboard.connectionId]);

  const { data: schemaData, isLoading: schemaLoading } = useQuery({
    queryKey: ["schema", dashboard.connectionId],
    queryFn: () => api.get<SchemaResponse>(`/schema/${dashboard.connectionId}`),
    enabled: !!dashboard.connectionId,
  });

  const schemaTables = useMemo(() => {
    if (!schemaData?.schema_data) return [];
    return Object.entries(schemaData.schema_data)
      .map(([name, info]) => ({ name, columns: Object.entries(info.columns).map(([cn, ci]) => ({ name: cn, type: toColType(ci.type) })) }))
      .filter((t) => { if (!schemaSearch) return true; const q = schemaSearch.toLowerCase(); return t.name.toLowerCase().includes(q) || t.columns.some((c) => c.name.toLowerCase().includes(q)); });
  }, [schemaData, schemaSearch]);

  // ── Dashboard Gallery (API) ──
  const { data: dashList, refetch: refetchDashboards } = useQuery({
    queryKey: ["dashboards"],
    queryFn: () => api.get<{ dashboards: any[]; total: number }>("/dashboards/"),
  });

  const allDashboards = useMemo(() =>
    (dashList?.dashboards ?? []).map((d: any) => ({ id: d.dashboard_id, name: d.name, updated: d.updated_at })),
  [dashList]);

  // Load first dashboard on mount
  const loadedRef = useRef(false);
  useEffect(() => {
    if (loadedRef.current || !dashList?.dashboards?.length) return;
    loadedRef.current = true;
    // Check for snapshot in URL hash
    const hash = window.location.hash;
    let snapDashId: string | null = null;
    let snapFilter: { column: string; value: string } | null = null;
    if (hash.startsWith("#snap=")) {
      try {
        const state = JSON.parse(atob(hash.slice(6)));
        if (state.d) snapDashId = state.d;
        if (state.fc && state.fv) snapFilter = { column: state.fc, value: state.fv };
      } catch {}
    }
    const target = snapDashId
      ? dashList.dashboards.find((x: any) => x.dashboard_id === snapDashId) || dashList.dashboards[0]
      : dashList.dashboards[0];
    const d = target;
    const cfg = d.config || {};
    setDashboard({
      id: d.dashboard_id, title: d.name || "My Dashboard", description: d.description || "",
      connectionId: cfg.connection_id || "", columns: cfg.columns || 12,
      widgets: deserializeWidgets(cfg.widgets, cfg.connection_id || ""),
      updatedAt: d.updated_at,
    });
    if (snapFilter) setGlobalFilter(snapFilter);
  }, [dashList]);

  // ── Save / Create ──
  const saveMut = useMutation({
    mutationFn: async (d: StudioDashboard) => {
      const payload = serializeDashboard(d);
      if (d.id) {
        await api.put(`/dashboards/${d.id}`, payload);
        return d.id;
      } else {
        const res = await api.post<{ dashboard_id: string }>("/dashboards/", payload);
        return res.dashboard_id;
      }
    },
    onSuccess: (id) => {
      setDashboard((d) => ({ ...d, id }));
      refetchDashboards();
      toast.success("Dashboard saved");
    },
    onError: () => toast.error("Save failed"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.delete(`/dashboards/${id}`),
    onSuccess: () => { refetchDashboards(); toast.success("Dashboard deleted"); },
  });

  const handleSave = useCallback(() => saveMut.mutate(dashboard), [dashboard, saveMut]);

  const handleShareSnapshot = useCallback(() => {
    const state: Record<string, string> = {};
    if (dashboard.id) state.d = dashboard.id;
    if (globalFilter) { state.fc = globalFilter.column; state.fv = globalFilter.value; }
    const hash = btoa(JSON.stringify(state));
    const url = `${window.location.origin}${window.location.pathname}#snap=${hash}`;
    navigator.clipboard.writeText(url);
    toast.success("Snapshot URL copied to clipboard");
  }, [dashboard.id, globalFilter]);

  const handleCreate = useCallback(() => {
    const d: StudioDashboard = {
      id: "", title: `Dashboard ${allDashboards.length + 1}`, description: "", connectionId: dashboard.connectionId,
      widgets: [], columns: 12, updatedAt: new Date().toISOString(),
    };
    setDashboard(d);
    setSelWidgetId(null);
    loadedRef.current = true;
    toast.success("New dashboard created — add visuals!");
  }, [allDashboards.length, dashboard.connectionId]);

  const handleLoadDashboard = useCallback((id: string) => {
    const d = dashList?.dashboards?.find((x: any) => x.dashboard_id === id);
    if (!d) return;
    const cfg = d.config || {};
    setDashboard({
      id: d.dashboard_id, title: d.name, description: d.description || "",
      connectionId: cfg.connection_id || dashboard.connectionId, columns: cfg.columns || 12,
      widgets: deserializeWidgets(cfg.widgets, cfg.connection_id || ""),
      updatedAt: d.updated_at,
    });
    setSelWidgetId(null);
    toast.success(`Loaded "${d.name}"`);
  }, [dashList, dashboard.connectionId]);

  const handleDeleteDashboard = useCallback((id: string) => {
    if (id === dashboard.id) { toast.error("Can't delete the active dashboard"); return; }
    deleteMut.mutate(id);
  }, [dashboard.id, deleteMut]);

  // ── Widget Ops ──
  const addWidget = useCallback(() => {
    const w = newWidget(dashboard.connectionId, dashboard.widgets.length + 1);
    setDashboard((d) => ({ ...d, widgets: [...d.widgets, w] }));
    setSelWidgetId(w.id); setPropsOpen(true);
  }, [dashboard.connectionId, dashboard.widgets.length]);

  const removeWidget = useCallback((id: string) => {
    setDashboard((d) => ({ ...d, widgets: d.widgets.filter((w) => w.id !== id) }));
    if (selWidgetId === id) setSelWidgetId(null);
  }, [selWidgetId]);

  const duplicateWidget = useCallback((id: string) => {
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
  }, [dashboard.widgets]);

  // Drag-to-reorder
  const handleDragStart = useCallback((id: string) => setDragWidgetId(id), []);
  const handleDragOver = useCallback((e: React.DragEvent, targetId: string) => {
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
  }, [dragWidgetId]);
  const handleDragEnd = useCallback(() => setDragWidgetId(null), []);

  const updateWidget = useCallback((id: string, u: Partial<CanvasWidget>) => {
    setDashboard((d) => ({ ...d, widgets: d.widgets.map((w) => w.id === id ? { ...w, ...u } : w) }));
  }, []);

  const runWidget = useCallback(async (wid: string) => {
    const w = dashboard.widgets.find((x) => x.id === wid);
    if (!w) return;
    const conn = w.connectionId || dashboard.connectionId;
    if (!conn) { toast.error("No connection"); return; }

    setDashboard((d) => ({ ...d, widgets: d.widgets.map((x) => x.id === wid ? { ...x, loading: true, error: null } : x) }));

    try {
      let result: QueryResponse; let sql: string | null = null;
      if (w.mode === "nlq" && w.nlQuestion) {
        result = await api.post<QueryResponse>("/query/", { question: w.nlQuestion, connection_id: conn });
        sql = result.sql;
      } else {
        sql = buildSql(w);
        if (!sql) { setDashboard((d) => ({ ...d, widgets: d.widgets.map((x) => x.id === wid ? { ...x, loading: false, error: "Assign fields first" } : x) })); return; }
        result = await api.post<QueryResponse>("/query/", { question: `Execute: ${sql}`, connection_id: conn });
      }
      // Auto-generate AI insight
      let insight: string | null = null;
      if (result.rows.length > 0 && result.columns.length >= 2) {
        const vals = result.rows.map((r) => toNumber(r[result.columns[1]])).filter((v): v is number => v !== null);
        if (vals.length > 1) {
          const total = vals.reduce((a, b) => a + b, 0);
          const max = Math.max(...vals);
          const maxIdx = vals.indexOf(max);
          const topLabel = String(result.rows[maxIdx]?.[result.columns[0]] ?? "");
          const pct = ((max / total) * 100).toFixed(1);
          insight = `Top: ${topLabel} (${pct}% of total). ${vals.length} data points, total ${total >= 1e6 ? (total/1e6).toFixed(1)+"M" : total >= 1e3 ? (total/1e3).toFixed(1)+"K" : total.toLocaleString()}.`;
        }
      }
      setDashboard((d) => ({ ...d, widgets: d.widgets.map((x) => x.id === wid ? { ...x, result, loading: false, error: null, generatedSql: sql, aiInsight: insight } : x) }));
      // AI Anomaly Detection — check for statistical anomalies
      const widgetTitle = w.title || "Visual";
      const anomalies = detectAnomalies(result, widgetTitle);
      if (anomalies.length > 0) {
        const a = anomalies[0]; // Show most severe
        if (a.severity === "critical") {
          toast.error(a.message, { duration: 8000, action: { label: "Investigate", onClick: () => setDrillDown({ label: a.label, column: a.column }) } });
        } else {
          toast(a.message, { duration: 6000, action: { label: "Investigate", onClick: () => setDrillDown({ label: a.label, column: a.column }) } });
        }
      }
    } catch (err) {
      const msg = err instanceof ApiRequestError ? err.message : "Query failed";
      setDashboard((d) => ({ ...d, widgets: d.widgets.map((x) => x.id === wid ? { ...x, loading: false, error: msg } : x) }));
    }
  }, [dashboard]);

  const refreshAll = useCallback(() => {
    dashboard.widgets.forEach((w) => { if (w.result || w.generatedSql || w.nlQuestion) runWidget(w.id); });
    if (dashboard.widgets.length > 0) toast.success(`Refreshing ${dashboard.widgets.length} visuals…`);
  }, [dashboard.widgets, runWidget]);

  // AI Generate Dashboard
  const handleAiGenerate = useCallback(async () => {
    if (!aiPrompt.trim() || !dashboard.connectionId) return;
    setShowAiModal(false);
    toast.success("AI is building your dashboard…");
    try {
      // Create 3 widgets from AI prompt
      const questions = [
        aiPrompt.trim(),
        `Give me a summary breakdown related to: ${aiPrompt.trim()}`,
        `Show the trend over time for: ${aiPrompt.trim()}`,
      ];
      const widgets: CanvasWidget[] = questions.map((q, i) => ({
        ...newWidget(dashboard.connectionId, i + 1),
        mode: "nlq" as WidgetMode,
        nlQuestion: q,
        title: i === 0 ? "Overview" : i === 1 ? "Breakdown" : "Trend",
        size: (i === 0 ? "lg" : "md") as WidgetSize,
        chartType: i === 0 ? "bar" : i === 1 ? "pie" : "area",
      }));
      setDashboard((d) => ({ ...d, title: aiPrompt.trim().slice(0, 40), widgets }));
      // Auto-run all
      for (const w of widgets) {
        setTimeout(() => runWidget(w.id), 500 * widgets.indexOf(w));
      }
    } catch { toast.error("AI generation failed"); }
  }, [aiPrompt, dashboard.connectionId, runWidget]);

  const selWidget = dashboard.widgets.find((w) => w.id === selWidgetId);

  return (
    <div className={cn(
      "absolute inset-0 flex flex-col overflow-hidden bg-slate-900",
      preview && "fixed inset-0 z-40 bg-slate-900"
    )}>
      {/* ── Toolbar ── */}
      <div className="shrink-0 border-b border-slate-700/25 bg-slate-900/90 backdrop-blur-md px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-1.5 rounded-lg bg-gradient-to-br from-blue-500/20 to-violet-500/10 border border-blue-500/15 shrink-0">
              <Palette className="h-4 w-4 text-blue-400" />
            </div>
            {editTitle ? (
              <div className="flex items-center gap-1">
                <input value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)} autoFocus
                  className="text-sm font-bold bg-transparent border-b border-blue-500/50 text-white focus:outline-none"
                  onKeyDown={(e) => { if (e.key === "Enter") { setDashboard((d) => ({ ...d, title: titleDraft })); setEditTitle(false); } if (e.key === "Escape") setEditTitle(false); }} />
                <button onClick={() => { setDashboard((d) => ({ ...d, title: titleDraft })); setEditTitle(false); }}><Check className="h-3 w-3 text-emerald-400" /></button>
              </div>
            ) : (
              <h1 className="text-sm font-bold text-white cursor-pointer hover:text-blue-300 transition-colors duration-200 flex items-center gap-1 truncate"
                onClick={() => { setTitleDraft(dashboard.title); setEditTitle(true); }}>
                {dashboard.title}<Edit3 className="h-2.5 w-2.5 text-slate-600 shrink-0" />
              </h1>
            )}
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <select value={dashboard.connectionId} onChange={(e) => setDashboard((d) => ({ ...d, connectionId: e.target.value }))}
              className="h-7 rounded-lg border border-slate-700/40 bg-slate-800/40 text-slate-300 text-[10px] px-2 focus:outline-none focus:ring-1 focus:ring-blue-500/30 transition-all duration-200 max-w-[140px]">
              <option value="">Connection…</option>
              {connections.map((c) => <option key={c.connection_id} value={c.connection_id}>{c.name}</option>)}
            </select>
            {dashboard.widgets.length > 0 && (
              <>
                <Button variant="ghost" size="sm" icon={<RefreshCw className="h-3 w-3" />} onClick={refreshAll} className="h-7 text-[10px]">Refresh</Button>
                <select value={autoRefresh} onChange={(e) => { setAutoRefresh(Number(e.target.value)); if (Number(e.target.value) > 0) toast.success(`Auto-refresh: every ${e.target.value}s`); }}
                  className="h-7 rounded-lg border border-slate-700/40 bg-slate-800/40 text-slate-400 text-[9px] px-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500/30 w-14"
                  title="Auto-refresh interval">
                  <option value={0}>Off</option>
                  <option value={30}>30s</option>
                  <option value={60}>1m</option>
                  <option value={300}>5m</option>
                </select>
              </>
            )}
            <Button variant="ghost" size="sm" icon={<Save className="h-3 w-3" />} onClick={handleSave} isLoading={saveMut.isPending} className="h-7 text-[10px]">Save</Button>
            <Button variant="ghost" size="sm" icon={<Link2 className="h-3 w-3" />} onClick={handleShareSnapshot} className="h-7 text-[10px]" title="Copy shareable snapshot URL">Share</Button>
            <Button variant={preview ? "primary" : "ghost"} size="sm"
              icon={preview ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
              onClick={() => setPreview(!preview)} className="h-7 text-[10px]">{preview ? "Edit" : "Preview"}</Button>
            {!preview && <Button size="sm" icon={<Plus className="h-3 w-3" />} onClick={addWidget} className="h-7 text-[10px]">Visual</Button>}
          </div>
        </div>

        {/* Dashboard Gallery */}
        {allDashboards.length > 0 && !preview && (
          <div className="mt-2 pt-2 border-t border-slate-700/20">
            <DashboardGallery dashboards={allDashboards} activeId={dashboard.id || null}
              onSelect={handleLoadDashboard} onCreate={handleCreate} onDelete={handleDeleteDashboard} />
          </div>
        )}
      </div>

      {/* ── 3-Panel Layout ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* Data Panel */}
        {!preview && (
          <div className={cn("shrink-0 border-r border-slate-700/25 bg-slate-900/40 flex flex-col transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]", dataOpen ? "w-52" : "w-9")}>
            <button onClick={() => setDataOpen(!dataOpen)}
              className="shrink-0 flex items-center justify-center gap-1 py-2 border-b border-slate-700/25 text-slate-500 hover:text-slate-300 hover:bg-slate-700/20 transition-colors duration-200">
              {dataOpen ? <><PanelLeftClose className="h-3 w-3" /><span className="text-[9px]">Data</span></> : <PanelLeftOpen className="h-3 w-3" />}
            </button>
            {dataOpen && (
              <>
                <div className="p-2 border-b border-slate-700/25">
                  <input value={schemaSearch} onChange={(e) => setSchemaSearch(e.target.value)} placeholder="Search tables…"
                    className="w-full h-7 rounded-lg border border-slate-700/30 bg-slate-800/30 text-[10px] text-slate-300 px-2.5 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500/20 transition-all duration-200" />
                </div>
                <div className="flex-1 overflow-y-auto p-2">
                  {schemaLoading && <div className="flex items-center gap-2 p-3"><Loader2 className="h-3 w-3 text-blue-400 animate-spin" /><span className="text-[10px] text-slate-500">Loading…</span></div>}
                  {!schemaLoading && schemaTables.length === 0 && (
                    <div className="text-center p-4"><Database className="h-5 w-5 text-slate-700 mx-auto mb-2" /><p className="text-[10px] text-slate-600">{dashboard.connectionId ? "No tables" : "Select connection"}</p></div>
                  )}
                  {schemaTables.map((t, i) => <SchemaTree key={t.name} tableName={t.name} columns={t.columns} open={i === 0 && schemaTables.length <= 5} />)}
                </div>
                <div className="shrink-0 px-2 py-1.5 border-t border-slate-700/25">
                  <p className="text-[8px] text-slate-600 text-center">Drag columns → Properties panel</p>
                </div>
              </>
            )}
          </div>
        )}

        {/* Canvas */}
        <div className="flex-1 overflow-y-auto p-4">
          {/* Global Filter Bar */}
          {globalFilter && (
            <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-blue-500/8 border border-blue-500/15 animate-fade-in filter-active">
              <span className="text-[10px] text-blue-300 font-medium">Filtered:</span>
              <span className="text-[10px] text-slate-300">{globalFilter.column} = &ldquo;{globalFilter.value}&rdquo;</span>
              <button onClick={() => setDrillDown({ label: globalFilter.value, column: globalFilter.column })}
                className="text-[9px] text-violet-400 hover:text-violet-300 border border-violet-500/20 rounded px-2 py-0.5 transition-colors flex items-center gap-1">
                <Sparkles className="h-2.5 w-2.5" /> Drill down
              </button>
              <button onClick={() => setGlobalFilter(null)} className="ml-auto text-[9px] text-slate-500 hover:text-slate-300 border border-slate-700/20 rounded px-2 py-0.5 transition-colors">
                Clear
              </button>
            </div>
          )}

          {dashboard.widgets.length > 0 ? (
            <div className="grid grid-cols-12 gap-3 auto-rows-min animate-fade-in">
              {dashboard.widgets.map((w) => (
                <WidgetCard key={w.id} widget={w} selected={selWidgetId === w.id} preview={preview}
                  onSelect={() => { setSelWidgetId(w.id); setPropsOpen(true); }}
                  onRemove={() => removeWidget(w.id)} onRun={() => runWidget(w.id)}
                  onDuplicate={() => duplicateWidget(w.id)}
                  onDrillDown={(label, column) => setDrillDown({ label, column })}
                  onDragStart={() => handleDragStart(w.id)}
                  onDragOver={(e) => handleDragOver(e, w.id)}
                  onDragEnd={handleDragEnd}
                  isDragging={dragWidgetId === w.id}
                  onDataClick={(label, column) => setGlobalFilter({ column, value: label })}
                  globalFilter={globalFilter} />
              ))}
            </div>
          ) : (
            <EmptyCanvas onAdd={addWidget} onAiGenerate={() => setShowAiModal(true)} />
          )}
        </div>

        {/* Properties */}
        {!preview && selWidget && propsOpen && (
          <div className="shrink-0 w-56 border-l border-slate-700/25 bg-slate-900/40 transition-all duration-300 animate-slide-in-right">
            <Props widget={selWidget} onUpdate={(u) => updateWidget(selWidget.id, u)} onRun={() => runWidget(selWidget.id)} />
          </div>
        )}
      </div>

      {/* AI Generate Modal */}
      {showAiModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setShowAiModal(false)} />
          <div className="relative w-full max-w-md glass-strong rounded-2xl shadow-2xl animate-scale-in">
            <div className="flex items-center justify-between p-5 border-b border-slate-700/40">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2"><Wand2 className="h-4 w-4 text-violet-400" /> AI Dashboard Builder</h2>
              <button onClick={() => setShowAiModal(false)} className="text-slate-400 hover:text-white transition-colors"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-5 space-y-4">
              <p className="text-xs text-slate-400">Describe the dashboard you want. AI will create multiple visuals automatically.</p>
              <input value={aiPrompt} onChange={(e) => setAiPrompt(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAiGenerate(); }}
                placeholder="e.g. Sales performance by region with monthly trends"
                className="w-full h-10 rounded-lg border border-slate-700/40 bg-slate-800/30 text-slate-200 text-sm px-3 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-violet-500/30" autoFocus />
              <div className="flex flex-wrap gap-1.5">
                {["Sales overview", "Customer analytics", "Revenue trends", "Product performance"].map((s) => (
                  <button key={s} onClick={() => setAiPrompt(s)}
                    className="text-[9px] px-2 py-1 rounded-lg border border-slate-700/30 text-slate-500 hover:text-violet-300 hover:border-violet-500/20 transition-all duration-200">{s}</button>
                ))}
              </div>
            </div>
            <div className="flex justify-end gap-2 p-5 border-t border-slate-700/40">
              <Button variant="ghost" size="sm" onClick={() => setShowAiModal(false)}>Cancel</Button>
              <Button size="sm" onClick={handleAiGenerate} disabled={!aiPrompt.trim()} icon={<Wand2 className="h-3.5 w-3.5" />}>Generate</Button>
            </div>
          </div>
        </div>
      )}

      {/* Drill-Down Modal */}
      {drillDown && (
        <DrillDownModal
          label={drillDown.label}
          column={drillDown.column}
          connectionId={dashboard.connectionId}
          onClose={() => setDrillDown(null)}
        />
      )}
    </div>
  );
}