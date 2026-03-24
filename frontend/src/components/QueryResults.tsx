/**
 * Smart BI Agent — Shared Query Result Components
 * Phase 5 | Session 1
 *
 * Extracted from QueryPage.tsx for reuse across:
 *   - QueryPage (main results view)
 *   - SavedQueriesPage (re-run results modal)
 *
 * Components:
 *   - ResultsTable — TanStack Table with sort, pagination, alternating rows
 *   - AutoChart — Auto-detecting bar/line/pie chart via Recharts
 *
 * Helpers:
 *   - toNumber — safe numeric coercion (handles Decimal strings from PG)
 *   - detectChartType — heuristic chart selection
 */

import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from "@tanstack/react-table";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, PieChart, Pie, Cell, Legend,
} from "recharts";
import {
  ChevronDown,
  ChevronUp,
  BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Constants ──────────────────────────────────────────────────────────────

export const CHART_COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#06b6d4", "#ec4899", "#f97316", "#14b8a6", "#6366f1",
];

// ─── Helpers ────────────────────────────────────────────────────────────────

type ChartType = "bar" | "line" | "pie" | "none";

export function toNumber(val: unknown): number | null {
  if (typeof val === "number") return val;
  if (typeof val === "string") {
    const n = parseFloat(val);
    return isNaN(n) ? null : n;
  }
  return null;
}

export function detectChartType(columns: string[], rows: Record<string, unknown>[]): ChartType {
  if (!rows.length || columns.length < 2) return "none";
  if (rows.length > 500) return "none";

  const sample = rows.slice(0, 15);
  const secondVals = sample.map((r) => toNumber(r[columns[1]]));
  const hasNumbers = secondVals.filter((v) => v !== null).length > sample.length * 0.5;

  if (!hasNumbers) return "none";

  const firstVals = sample.map((r) => r[columns[0]]);
  const firstIsString = firstVals.every((v) => typeof v === "string" || v === null);

  if (rows.length <= 6 && firstIsString) return "pie";
  if (rows.length <= 40 && firstIsString) return "bar";
  if (rows.length > 10) return "line";

  return "bar";
}

// ─── Custom Tooltip ─────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600/60 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      {payload.map((entry: any, i: number) => (
        <p key={i} className="text-sm font-medium" style={{ color: entry.color }}>
          {typeof entry.value === "number" ? entry.value.toLocaleString() : entry.value}
        </p>
      ))}
    </div>
  );
}

// ─── Results Table ──────────────────────────────────────────────────────────

export function ResultsTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const columnHelper = createColumnHelper<Record<string, unknown>>();

  const tableColumns = useMemo(
    () =>
      columns.map((col) =>
        columnHelper.accessor(col, {
          header: col,
          cell: (info) => {
            const val = info.getValue();
            if (val === null || val === undefined)
              return <span className="text-slate-600 italic">null</span>;
            if (typeof val === "boolean")
              return (
                <span className={val ? "text-emerald-400" : "text-red-400"}>
                  {val ? "true" : "false"}
                </span>
              );
            if (typeof val === "number")
              return <span className="text-blue-300">{val.toLocaleString()}</span>;
            if (typeof val === "object") return JSON.stringify(val);
            return String(val);
          },
        })
      ),
    [columns]
  );

  const table = useReactTable({
    data: rows,
    columns: tableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 50 } },
  });

  return (
    <div>
      <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="bg-slate-800/95 backdrop-blur-sm border-b border-slate-700/40">
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className="text-left text-[11px] font-semibold text-slate-400 uppercase tracking-wider px-4 py-3 cursor-pointer hover:text-slate-200 select-none whitespace-nowrap transition-colors"
                  >
                    <span className="flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {{
                        asc: <ChevronUp className="h-3 w-3 text-blue-400" />,
                        desc: <ChevronDown className="h-3 w-3 text-blue-400" />,
                      }[header.column.getIsSorted() as string] ?? null}
                    </span>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-700/20">
            {table.getRowModel().rows.map((row, idx) => (
              <tr
                key={row.id}
                className={cn(
                  "transition-colors hover:bg-blue-500/5",
                  idx % 2 === 0 ? "bg-transparent" : "bg-slate-800/20"
                )}
              >
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className="px-4 py-2.5 text-slate-300 font-mono text-xs whitespace-nowrap max-w-[300px] truncate"
                  >
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
            <button
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              className="text-xs px-3 py-1.5 rounded-md bg-slate-700/60 text-slate-300 hover:bg-slate-600 disabled:opacity-30 transition-colors"
            >
              ← Prev
            </button>
            <button
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              className="text-xs px-3 py-1.5 rounded-md bg-slate-700/60 text-slate-300 hover:bg-slate-600 disabled:opacity-30 transition-colors"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Auto Chart ─────────────────────────────────────────────────────────────

export function AutoChart({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  const chartType = detectChartType(columns, rows);

  if (chartType === "none") {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <BarChart3 className="h-10 w-10 text-slate-600 mb-3" />
        <p className="text-sm text-slate-400 font-medium">No chart available</p>
        <p className="text-xs text-slate-500 mt-1 max-w-sm">
          Charts work best with at least 2 columns where the second column contains numeric values.
          Try a query like "Show revenue by month" or "Count orders by status".
        </p>
      </div>
    );
  }

  const labelKey = columns[0];
  const valueKeys = columns.slice(1).filter((col) => {
    const sample = rows.slice(0, 5).map((r) => toNumber(r[col]));
    return sample.filter((v) => v !== null).length > 0;
  });

  const data = rows.slice(0, 200).map((r) => {
    const entry: Record<string, any> = { name: String(r[labelKey] ?? "") };
    valueKeys.forEach((key) => {
      entry[key] = toNumber(r[key]) ?? 0;
    });
    return entry;
  });

  const primaryKey = valueKeys[0] || "value";

  return (
    <div className="h-[340px] w-full px-2">
      <ResponsiveContainer width="100%" height="100%">
        {chartType === "pie" ? (
          <PieChart>
            <Pie
              data={data}
              dataKey={primaryKey}
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={110}
              innerRadius={50}
              paddingAngle={2}
              label={({ name, percent }) =>
                `${String(name).slice(0, 15)} (${(percent * 100).toFixed(0)}%)`
              }
              labelLine={{ stroke: "#475569", strokeWidth: 1 }}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />
          </PieChart>
        ) : chartType === "line" ? (
          <LineChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#64748b" }} angle={-25} textAnchor="end" height={50} axisLine={{ stroke: "#334155" }} />
            <YAxis tick={{ fontSize: 10, fill: "#64748b" }} axisLine={{ stroke: "#334155" }} tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v)} />
            <Tooltip content={<ChartTooltip />} />
            {valueKeys.map((key, i) => (
              <Line key={key} type="monotone" dataKey={key} stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2.5} dot={{ r: 3, fill: CHART_COLORS[i % CHART_COLORS.length] }} activeDot={{ r: 5 }} />
            ))}
            {valueKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#64748b" }} angle={-25} textAnchor="end" height={60} axisLine={{ stroke: "#334155" }} />
            <YAxis tick={{ fontSize: 10, fill: "#64748b" }} axisLine={{ stroke: "#334155" }} tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v)} />
            <Tooltip content={<ChartTooltip />} />
            {valueKeys.map((key, i) => (
              <Bar key={key} dataKey={key} fill={CHART_COLORS[i % CHART_COLORS.length]} radius={[4, 4, 0, 0]} maxBarSize={50} />
            ))}
            {valueKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} iconSize={8} />}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}