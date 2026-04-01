/**
 * Smart BI Agent — Shared Query Result Components v2
 * Enhanced: Scorecard, AreaChart, smarter detection, chart download
 *
 * Components:
 *   - ResultsTable — TanStack Table with sort, pagination
 *   - AutoChart — Smart auto-detecting chart (scorecard/bar/line/area/pie)
 *   - Scorecard — Single-value KPI display
 *
 * Helpers:
 *   - toNumber, detectChartType (enhanced)
 */

import { useState, useMemo, useRef, useCallback } from "react";
import {
  useReactTable, getCoreRowModel, getSortedRowModel,
  getPaginationRowModel, flexRender, createColumnHelper,
  type SortingState,
} from "@tanstack/react-table";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, PieChart, Pie, Cell, Legend, AreaChart, Area,
  ScatterChart, Scatter, ZAxis,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from "recharts";
import { ChevronDown, ChevronUp, BarChart3, TrendingUp, TrendingDown, Minus, Download } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Constants ──────────────────────────────────────────────────────────────

export const CHART_COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#06b6d4", "#ec4899", "#f97316", "#14b8a6", "#6366f1",
];

export const CHART_TYPE_OPTIONS = [
  { value: "auto", label: "Auto Detect" },
  { value: "scorecard", label: "Scorecard" },
  { value: "bar", label: "Bar Chart" },
  { value: "horizontal_bar", label: "Horizontal Bar" },
  { value: "stacked_bar", label: "Stacked Bar" },
  { value: "line", label: "Line Chart" },
  { value: "area", label: "Area Chart" },
  { value: "pie", label: "Pie / Donut" },
  { value: "scatter", label: "Scatter Plot" },
];

// ─── Helpers ────────────────────────────────────────────────────────────────

export type ChartType = "bar" | "horizontal_bar" | "stacked_bar" | "line" | "area" | "pie" | "scatter" | "radar" | "scorecard" | "none";

export function toNumber(val: unknown): number | null {
  if (typeof val === "number") return val;
  if (typeof val === "string") {
    const n = parseFloat(val);
    return isNaN(n) ? null : n;
  }
  return null;
}

function isDateLike(val: unknown): boolean {
  if (typeof val !== "string") return false;
  return /^\d{4}[-/]\d{2}/.test(val) || /^\d{2}[-/]\d{2}[-/]\d{4}/.test(val);
}

export function detectChartType(columns: string[], rows: Record<string, unknown>[]): ChartType {
  if (!rows.length) return "none";

  // Single value → scorecard
  if (rows.length === 1 && columns.length === 1) {
    const val = toNumber(rows[0][columns[0]]);
    if (val !== null) return "scorecard";
  }
  // Single row, 1-3 numeric cols → scorecard
  if (rows.length === 1 && columns.length <= 3) {
    const numericCount = columns.filter((c) => toNumber(rows[0][c]) !== null).length;
    if (numericCount >= 1) return "scorecard";
  }

  if (columns.length < 2) return "none";
  if (rows.length > 500) return "bar";

  const sample = rows.slice(0, 15);
  const secondVals = sample.map((r) => toNumber(r[columns[1]]));
  const hasNumbers = secondVals.filter((v) => v !== null).length > sample.length * 0.5;
  if (!hasNumbers) return "none";

  const firstVals = sample.map((r) => r[columns[0]]);
  const firstIsDate = firstVals.filter((v) => isDateLike(v)).length > sample.length * 0.5;
  const firstIsString = firstVals.every((v) => typeof v === "string" || v === null);

  // Time series → area
  if (firstIsDate && rows.length > 3) return "area";
  // Few categories → pie
  if (rows.length <= 6 && firstIsString) return "pie";
  // Moderate categories → bar
  if (rows.length <= 40 && firstIsString) return "bar";
  // Many data points → line
  if (rows.length > 40) return "line";

  return "bar";
}

// ─── Tooltip ────────────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600/60 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      {payload.map((entry: any, i: number) => (
        <p key={i} className="text-sm font-medium" style={{ color: entry.color }}>
          {entry.name}: {typeof entry.value === "number" ? entry.value.toLocaleString() : entry.value}
        </p>
      ))}
    </div>
  );
}

// ─── Scorecard ──────────────────────────────────────────────────────────────

export function Scorecard({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  const row = rows[0] || {};

  return (
    <div className="flex items-center justify-center gap-8 py-10 flex-wrap">
      {columns.map((col) => {
        const val = row[col];
        const numVal = toNumber(val);
        const displayVal = numVal !== null
          ? numVal >= 1_000_000 ? `${(numVal / 1_000_000).toFixed(1)}M`
            : numVal >= 1_000 ? `${(numVal / 1_000).toFixed(1)}K`
            : numVal.toLocaleString()
          : String(val ?? "—");

        return (
          <div key={col} className="text-center px-8 py-6 rounded-2xl bg-gradient-to-br from-blue-500/10 to-indigo-500/5 border border-blue-500/15">
            <p className="text-3xl font-bold text-white tracking-tight">{displayVal}</p>
            <p className="text-xs text-slate-400 mt-2 uppercase tracking-wider">{col.replace(/_/g, " ")}</p>
          </div>
        );
      })}
    </div>
  );
}

// ─── Chart Download ─────────────────────────────────────────────────────────

function downloadChartAsPng(containerRef: React.RefObject<HTMLDivElement | null>, filename: string) {
  const container = containerRef.current;
  if (!container) return;

  const svgEl = container.querySelector("svg");
  if (!svgEl) return;

  const svgData = new XMLSerializer().serializeToString(svgEl);
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const img = new Image();
  const svgBlob = new Blob([svgData], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);

  img.onload = () => {
    canvas.width = img.width * 2;
    canvas.height = img.height * 2;
    ctx.scale(2, 2);
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, img.width, img.height);
    ctx.drawImage(img, 0, 0);
    const pngUrl = canvas.toDataURL("image/png");

    const a = document.createElement("a");
    a.href = pngUrl;
    a.download = `${filename}.png`;
    a.click();
    URL.revokeObjectURL(url);
  };
  img.src = url;
}

// ─── Chart Renderer ─────────────────────────────────────────────────────────

interface ChartRendererProps {
  chartType: ChartType;
  columns: string[];
  rows: Record<string, unknown>[];
  xAxis?: string;
  yAxes?: string[];
  showLegend?: boolean;
  showGrid?: boolean;
  height?: number;
  fillContainer?: boolean;
  onDataClick?: (label: string, column: string) => void;
}

export function ChartRenderer({
  chartType, columns, rows, xAxis, yAxes, showLegend = true, showGrid = true, height = 380, fillContainer = false, onDataClick,
}: ChartRendererProps) {
  const chartRef = useRef<HTMLDivElement>(null);

  if (chartType === "scorecard") {
    return <Scorecard columns={columns} rows={rows} />;
  }

  if (chartType === "none") {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <BarChart3 className="h-10 w-10 text-slate-600 mb-3" />
        <p className="text-sm text-slate-400 font-medium">No chart available</p>
        <p className="text-xs text-slate-500 mt-1 max-w-sm">
          Charts work best with at least 2 columns where one contains numeric values.
        </p>
      </div>
    );
  }

  const labelKey = xAxis || columns[0];
  const valueKeys = (yAxes && yAxes.length > 0 ? yAxes : columns.slice(1)).filter((col) => {
    const sample = rows.slice(0, 5).map((r) => toNumber(r[col]));
    return sample.filter((v) => v !== null).length > 0;
  });

  const data = rows.slice(0, 500).map((r) => {
    const entry: Record<string, any> = { name: String(r[labelKey] ?? "") };
    valueKeys.forEach((key) => { entry[key] = toNumber(r[key]) ?? 0; });
    return entry;
  });

  const primaryKey = valueKeys[0] || "value";
  const gridProps = showGrid ? { strokeDasharray: "3 3", stroke: "#1e293b" } : { stroke: "transparent" };
  const xTickProps = { fontSize: 10, fill: "#64748b" };
  const yTickProps = { fontSize: 10, fill: "#64748b" };
  const yFmt = (v: number) => (v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v));

  return (
    <div ref={chartRef} className={cn("w-full px-2 relative group", fillContainer && "h-full")} style={fillContainer ? undefined : { height }}>
      <button onClick={() => downloadChartAsPng(chartRef, "chart")}
        className="absolute top-2 right-4 z-10 opacity-0 group-hover:opacity-100 p-1.5 rounded-md bg-slate-700/80 text-slate-300 hover:text-white transition-all" title="Download as PNG">
        <Download className="h-3.5 w-3.5" />
      </button>
      <ResponsiveContainer width="100%" height="100%">
        {chartType === "pie" ? (
          <PieChart>
            <Pie data={data} dataKey={primaryKey} nameKey="name" cx="50%" cy="50%"
              outerRadius={Math.min(height * 0.35, 130)} innerRadius={Math.min(height * 0.18, 55)} paddingAngle={2}
              label={({ name, percent }) => `${String(name).slice(0, 15)} (${(percent * 100).toFixed(0)}%)`}
              labelLine={{ stroke: "#475569", strokeWidth: 1 }}
              onClick={(entry) => { if (onDataClick && entry?.name) onDataClick(String(entry.name), labelKey); }}
              className={onDataClick ? "cursor-pointer" : ""}>
              {data.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
            </Pie>
            <Tooltip content={<ChartTooltip />} />
            {showLegend && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </PieChart>
        ) : chartType === "area" ? (
          <AreaChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="name" tick={xTickProps} angle={-25} textAnchor="end" height={50} axisLine={{ stroke: "#334155" }} />
            <YAxis tick={yTickProps} axisLine={{ stroke: "#334155" }} tickFormatter={yFmt} />
            <Tooltip content={<ChartTooltip />} />
            {valueKeys.map((key, i) => (
              <Area key={key} type="monotone" dataKey={key} stroke={CHART_COLORS[i % CHART_COLORS.length]}
                fill={CHART_COLORS[i % CHART_COLORS.length]} fillOpacity={0.15} strokeWidth={2}
                animationDuration={400} animationEasing="ease-out" />
            ))}
            {showLegend && valueKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </AreaChart>
        ) : chartType === "scatter" ? (
          <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="name" tick={xTickProps} name={labelKey} axisLine={{ stroke: "#334155" }} />
            <YAxis dataKey={primaryKey} tick={yTickProps} axisLine={{ stroke: "#334155" }} tickFormatter={yFmt} />
            <ZAxis range={[40, 400]} />
            <Tooltip content={<ChartTooltip />} />
            <Scatter data={data} fill={CHART_COLORS[0]} />
          </ScatterChart>
        ) : chartType === "horizontal_bar" ? (
          <BarChart data={data} layout="vertical" margin={{ top: 10, right: 20, bottom: 10, left: 80 }}>
            <CartesianGrid {...gridProps} />
            <XAxis type="number" tick={yTickProps} axisLine={{ stroke: "#334155" }} tickFormatter={yFmt} />
            <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: "#94a3b8" }} width={75} axisLine={{ stroke: "#334155" }} />
            <Tooltip content={<ChartTooltip />} />
            {valueKeys.map((key, i) => (
              <Bar key={key} dataKey={key} fill={CHART_COLORS[i % CHART_COLORS.length]} radius={[0, 4, 4, 0]} maxBarSize={30} />
            ))}
            {showLegend && valueKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </BarChart>
        ) : chartType === "stacked_bar" ? (
          <BarChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="name" tick={xTickProps} angle={-25} textAnchor="end" height={60} axisLine={{ stroke: "#334155" }} />
            <YAxis tick={yTickProps} axisLine={{ stroke: "#334155" }} tickFormatter={yFmt} />
            <Tooltip content={<ChartTooltip />} />
            {valueKeys.map((key, i) => (
              <Bar key={key} dataKey={key} stackId="stack" fill={CHART_COLORS[i % CHART_COLORS.length]} radius={i === valueKeys.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]} />
            ))}
            {showLegend && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </BarChart>
        ) : chartType === "line" ? (
          <LineChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="name" tick={xTickProps} angle={-25} textAnchor="end" height={50} axisLine={{ stroke: "#334155" }} />
            <YAxis tick={yTickProps} axisLine={{ stroke: "#334155" }} tickFormatter={yFmt} />
            <Tooltip content={<ChartTooltip />} />
            {valueKeys.map((key, i) => (
              <Line key={key} type="monotone" dataKey={key} stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2.5}
                dot={{ r: 3, fill: CHART_COLORS[i % CHART_COLORS.length] }} activeDot={{ r: 5 }} />
            ))}
            {showLegend && valueKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}
            onClick={(e) => { if (onDataClick && e?.activeLabel) onDataClick(String(e.activeLabel), labelKey); }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="name" tick={xTickProps} angle={-25} textAnchor="end" height={60} axisLine={{ stroke: "#334155" }} />
            <YAxis tick={yTickProps} axisLine={{ stroke: "#334155" }} tickFormatter={yFmt} />
            <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(59, 130, 246, 0.08)" }} />
            {valueKeys.map((key, i) => (
              <Bar key={key} dataKey={key} fill={CHART_COLORS[i % CHART_COLORS.length]} radius={[4, 4, 0, 0]} maxBarSize={50}
                className={onDataClick ? "cursor-pointer" : ""} animationDuration={400} animationEasing="ease-out" />
            ))}
            {showLegend && valueKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

// ─── AutoChart (backward compatible wrapper) ────────────────────────────────

export function AutoChart({ columns, rows, fillContainer = false }: { columns: string[]; rows: Record<string, unknown>[]; fillContainer?: boolean }) {
  const chartType = detectChartType(columns, rows);
  return <ChartRenderer chartType={chartType} columns={columns} rows={rows} fillContainer={fillContainer} />;
}

// ─── Results Table ──────────────────────────────────────────────────────────

export function ResultsTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const columnHelper = createColumnHelper<Record<string, unknown>>();

  const tableColumns = useMemo(
    () => columns.map((col) =>
      columnHelper.accessor(col, {
        header: col,
        cell: (info) => {
          const val = info.getValue();
          if (val === null || val === undefined) return <span className="text-slate-600 italic">null</span>;
          if (typeof val === "boolean") return <span className={val ? "text-emerald-400" : "text-red-400"}>{val ? "true" : "false"}</span>;
          if (typeof val === "number") return <span className="text-blue-300">{val.toLocaleString()}</span>;
          if (typeof val === "object") return JSON.stringify(val);
          return String(val);
        },
      })
    ),
    [columns]
  );

  const table = useReactTable({
    data: rows, columns: tableColumns, state: { sorting }, onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 50 } },
  });

  return (
    <div>
      <div className="overflow-x-auto overflow-y-auto" style={{ maxHeight: "calc(100vh - 22rem)" }}>
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="bg-slate-800/95 backdrop-blur-sm border-b border-slate-700/40">
                {hg.headers.map((header) => (
                  <th key={header.id} onClick={header.column.getToggleSortingHandler()}
                    className="text-left text-[11px] font-semibold text-slate-400 uppercase tracking-wider px-4 py-3 cursor-pointer hover:text-slate-200 select-none whitespace-nowrap transition-colors">
                    <span className="flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {{ asc: <ChevronUp className="h-3 w-3 text-blue-400" />, desc: <ChevronDown className="h-3 w-3 text-blue-400" /> }[header.column.getIsSorted() as string] ?? null}
                    </span>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-700/20">
            {table.getRowModel().rows.map((row, idx) => (
              <tr key={row.id} className={cn("transition-colors hover:bg-blue-500/5", idx % 2 === 0 ? "bg-transparent" : "bg-slate-800/20")}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-4 py-2.5 text-slate-300 font-mono text-xs whitespace-nowrap max-w-[300px] truncate">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-700/30 bg-slate-800/30">
          <span className="text-xs text-slate-500">
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
            <span className="ml-2 text-slate-600">({rows.length} rows)</span>
          </span>
          <div className="flex items-center gap-1">
            <button onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}
              className="text-xs px-3 py-1.5 rounded-md bg-slate-700/60 text-slate-300 hover:bg-slate-600 disabled:opacity-30 transition-colors">← Prev</button>
            <button onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}
              className="text-xs px-3 py-1.5 rounded-md bg-slate-700/60 text-slate-300 hover:bg-slate-600 disabled:opacity-30 transition-colors">Next →</button>
          </div>
        </div>
      )}
    </div>
  );
}
