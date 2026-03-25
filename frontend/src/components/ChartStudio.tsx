/**
 * Smart BI Agent — Chart Studio v4
 *
 * Fixes:
 *   - Only RESULT columns can be dropped into field wells (schema cols are reference)
 *   - Proper height rendering (no more blank charts)
 *   - Clear visual distinction: result cols = draggable, schema cols = browse only
 *   - Click schema column → copies to clipboard for SQL editing
 */

import { useState, useMemo, type DragEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3, LineChart as LineIcon, PieChart as PieIcon,
  Settings2, LayoutGrid, ArrowRightLeft, GripVertical,
  X, Hash, Type, Calendar, FileDown, Layers, Table2,
  ChevronRight, ChevronDown, Copy,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import {
  ChartRenderer, toNumber, detectChartType,
  type ChartType,
} from "@/components/QueryResults";
import { triggerBlobDownload } from "@/lib/api";
import type { SchemaResponse } from "@/types/schema";

// ─── Types ──────────────────────────────────────────────────────────────────

type ColType = "numeric" | "text" | "date";

function getColumnType(col: string, rows: Record<string, unknown>[]): ColType {
  const sample = rows.slice(0, 10).map((r) => r[col]);
  const dateCount = sample.filter((v) => typeof v === "string" && /^\d{4}[-/]\d{2}/.test(v)).length;
  if (dateCount > sample.length * 0.5) return "date";
  const numericCount = sample.filter((v) => toNumber(v) !== null).length;
  if (numericCount > sample.length * 0.5) return "numeric";
  return "text";
}

function schemaTypeToColType(dbType: string): ColType {
  const t = dbType.toLowerCase();
  if (/int|numeric|decimal|float|double|real|money|serial/.test(t)) return "numeric";
  if (/date|time|timestamp/.test(t)) return "date";
  return "text";
}

const TYPE_ICONS: Record<ColType, React.ReactNode> = {
  numeric: <Hash className="h-3 w-3 text-blue-400" />,
  text: <Type className="h-3 w-3 text-emerald-400" />,
  date: <Calendar className="h-3 w-3 text-amber-400" />,
};

// ─── Chart Types ────────────────────────────────────────────────────────────

const CHART_TYPES: { value: string; label: string; icon: React.ReactNode }[] = [
  { value: "auto", label: "Auto", icon: <Settings2 className="h-3.5 w-3.5" /> },
  { value: "bar", label: "Bar", icon: <BarChart3 className="h-3.5 w-3.5" /> },
  { value: "horizontal_bar", label: "H-Bar", icon: <ArrowRightLeft className="h-3.5 w-3.5" /> },
  { value: "stacked_bar", label: "Stacked", icon: <Layers className="h-3.5 w-3.5" /> },
  { value: "line", label: "Line", icon: <LineIcon className="h-3.5 w-3.5" /> },
  { value: "area", label: "Area", icon: <LineIcon className="h-3.5 w-3.5" /> },
  { value: "pie", label: "Pie", icon: <PieIcon className="h-3.5 w-3.5" /> },
  { value: "scorecard", label: "KPI", icon: <LayoutGrid className="h-3.5 w-3.5" /> },
];

// ─── CSV Export ─────────────────────────────────────────────────────────────

function exportCsv(columns: string[], rows: Record<string, unknown>[]) {
  const header = columns.join(",");
  const lines = rows.map((row) =>
    columns.map((col) => {
      const v = row[col]; if (v == null) return "";
      const s = String(v); return s.includes(",") || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")
  );
  triggerBlobDownload(new Blob([header + "\n" + lines.join("\n")], { type: "text/csv" }), "chart-data.csv");
}

// ─── Draggable Result Column ────────────────────────────────────────────────

function DraggableCol({ name, type }: { name: string; type: ColType }) {
  return (
    <div draggable
      onDragStart={(e) => { e.dataTransfer.setData("text/plain", name); e.dataTransfer.effectAllowed = "copy"; }}
      className="flex items-center gap-1.5 px-2 py-1 rounded border border-slate-600/30 bg-slate-700/20 cursor-grab active:cursor-grabbing hover:border-blue-500/40 hover:bg-blue-500/5 transition-all text-[11px] group">
      <GripVertical className="h-2.5 w-2.5 text-slate-600 group-hover:text-blue-400 shrink-0" />
      {TYPE_ICONS[type]}
      <span className="text-slate-300 truncate">{name}</span>
    </div>
  );
}

// ─── Schema Column (reference only — click to copy) ─────────────────────────

function SchemaCol({ name, type, tableName }: { name: string; type: ColType; tableName: string }) {
  return (
    <button onClick={() => { navigator.clipboard.writeText(`${tableName}.${name}`); toast.success(`Copied ${tableName}.${name}`); }}
      className="w-full flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] text-slate-500 hover:text-slate-300 hover:bg-slate-700/30 transition-all text-left"
      title={`Click to copy: ${tableName}.${name}`}>
      {TYPE_ICONS[type]}
      <span className="truncate">{name}</span>
      <Copy className="h-2 w-2 ml-auto opacity-0 group-hover:opacity-100 text-slate-600" />
    </button>
  );
}

// ─── Schema Table Tree ──────────────────────────────────────────────────────

function SchemaTree({ tableName, columns }: { tableName: string; columns: { name: string; type: ColType }[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-0.5">
      <button onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1 px-1 py-0.5 rounded hover:bg-slate-700/20 transition-colors text-left">
        <span className="text-slate-600 shrink-0">{open ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}</span>
        <Table2 className="h-2.5 w-2.5 text-slate-600 shrink-0" />
        <span className="text-[9px] text-slate-500 truncate">{tableName}</span>
        <span className="text-[8px] text-slate-700 ml-auto">{columns.length}</span>
      </button>
      {open && (
        <div className="ml-3 pl-2 border-l border-slate-800 space-y-0 mt-0.5 group">
          {columns.map((c) => <SchemaCol key={c.name} name={c.name} type={c.type} tableName={tableName} />)}
        </div>
      )}
    </div>
  );
}

// ─── Field Well ─────────────────────────────────────────────────────────────

function FieldWell({ label, icon, fields, onDrop, onRemove, placeholder, multi = true }: {
  label: string; icon: React.ReactNode; fields: string[];
  onDrop: (col: string) => void; onRemove: (col: string) => void;
  placeholder: string; multi?: boolean;
}) {
  const [over, setOver] = useState(false);
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        <span className="text-slate-600">{icon}</span>
        <span className="text-[9px] font-semibold text-slate-500 uppercase tracking-wider">{label}</span>
      </div>
      <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); const c = e.dataTransfer.getData("text/plain"); if (c && !fields.includes(c)) onDrop(c); }}
        className={cn("min-h-[30px] rounded-lg border-2 border-dashed p-1 transition-all flex flex-wrap gap-1",
          over ? "border-blue-500/50 bg-blue-500/5" : fields.length > 0 ? "border-slate-700/40 bg-slate-800/20" : "border-slate-700/30")}>
        {fields.length === 0 && <span className="text-[9px] text-slate-700 px-1">{placeholder}</span>}
        {fields.map((f) => (
          <span key={f} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-600/20 text-[10px] font-medium text-blue-300 border border-blue-500/20">
            {f}<button onClick={() => onRemove(f)} className="text-blue-400/60 hover:text-red-400"><X className="h-2.5 w-2.5" /></button>
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── Main ───────────────────────────────────────────────────────────────────

export default function ChartStudio({ columns, rows, connectionId }: {
  columns: string[]; rows: Record<string, unknown>[]; connectionId?: string;
}) {
  const autoType = detectChartType(columns, rows);
  const [chartType, setChartType] = useState<string>("auto");
  const [xAxis, setXAxis] = useState<string[]>(() => columns.length > 0 ? [columns[0]] : []);
  const [values, setValues] = useState<string[]>(() =>
    columns.slice(1).filter((c) => getColumnType(c, rows) === "numeric").slice(0, 3)
  );
  const [legend, setLegend] = useState<string[]>([]);
  const [showLegend, setShowLegend] = useState(true);
  const [showGrid, setShowGrid] = useState(true);

  const resolvedType: ChartType = chartType === "auto" ? autoType : (chartType as ChartType);

  // Result columns with types (THESE are draggable)
  const resultCols = useMemo(() => columns.map((c) => ({ name: c, type: getColumnType(c, rows) })), [columns, rows]);

  // Schema tables (reference only — browse, click to copy)
  const { data: schemaData } = useQuery({
    queryKey: ["schema", connectionId],
    queryFn: () => api.get<SchemaResponse>(`/schema/${connectionId}`),
    enabled: !!connectionId,
  });

  const schemaTables = useMemo(() => {
    if (!schemaData?.schema_data) return [];
    return Object.entries(schemaData.schema_data).map(([name, info]) => ({
      name,
      columns: Object.entries(info.columns).map(([cn, ci]) => ({ name: cn, type: schemaTypeToColType(ci.type) })),
    }));
  }, [schemaData]);

  return (
    <div className="flex" style={{ height: "100%" }}>
      {/* ── Left Panel ── */}
      <div className="w-52 shrink-0 border-r border-slate-700/40 flex flex-col overflow-hidden">

        {/* Result Columns (draggable) */}
        <div className="p-2 border-b border-slate-700/30">
          <div className="text-[9px] font-semibold text-blue-400 uppercase tracking-wider mb-1.5 px-0.5">
            Result Columns · drag to wells ↓
          </div>
          <div className="space-y-1 max-h-36 overflow-y-auto">
            {resultCols.map((c) => <DraggableCol key={c.name} name={c.name} type={c.type} />)}
          </div>
        </div>

        {/* Field Wells */}
        <div className="p-2 space-y-2 border-b border-slate-700/30">
          <FieldWell label="X-Axis" icon={<ArrowRightLeft className="h-2.5 w-2.5" />}
            fields={xAxis} onDrop={(c) => setXAxis([c])} onRemove={(c) => setXAxis((f) => f.filter((x) => x !== c))}
            placeholder="Drop dimension" multi={false} />
          <FieldWell label="Values" icon={<Hash className="h-2.5 w-2.5" />}
            fields={values} onDrop={(c) => setValues((f) => [...f, c])} onRemove={(c) => setValues((f) => f.filter((x) => x !== c))}
            placeholder="Drop measures" />
          <FieldWell label="Legend" icon={<Layers className="h-2.5 w-2.5" />}
            fields={legend} onDrop={(c) => setLegend([c])} onRemove={(c) => setLegend((f) => f.filter((x) => x !== c))}
            placeholder="Drop group" multi={false} />
        </div>

        {/* Options */}
        <div className="p-2 border-b border-slate-700/30 flex items-center gap-3">
          <label className="flex items-center gap-1 text-[9px] text-slate-500 cursor-pointer">
            <input type="checkbox" checked={showLegend} onChange={(e) => setShowLegend(e.target.checked)}
              className="rounded border-slate-600 bg-slate-700 text-blue-500 h-3 w-3" /> Legend
          </label>
          <label className="flex items-center gap-1 text-[9px] text-slate-500 cursor-pointer">
            <input type="checkbox" checked={showGrid} onChange={(e) => setShowGrid(e.target.checked)}
              className="rounded border-slate-600 bg-slate-700 text-blue-500 h-3 w-3" /> Grid
          </label>
          <button onClick={() => exportCsv(columns, rows)}
            className="ml-auto flex items-center gap-0.5 text-[9px] text-slate-600 hover:text-slate-300">
            <FileDown className="h-2.5 w-2.5" />CSV
          </button>
        </div>

        {/* Schema Browser (reference — click to copy) */}
        <div className="flex-1 overflow-y-auto p-2">
          <div className="text-[8px] font-semibold text-slate-600 uppercase tracking-wider mb-1 px-0.5">
            Schema · click to copy
          </div>
          {schemaTables.map((t) => <SchemaTree key={t.name} tableName={t.name} columns={t.columns} />)}
          {schemaTables.length === 0 && <p className="text-[9px] text-slate-700 px-1">Loading schema…</p>}
        </div>
      </div>

      {/* ── Right: Chart ── */}
      <div className="flex-1 flex flex-col min-w-0" style={{ height: "100%" }}>
        {/* Chart Type Bar */}
        <div className="shrink-0 flex items-center gap-1 px-2 py-1.5 border-b border-slate-700/30 overflow-x-auto no-scrollbar">
          {CHART_TYPES.map((ct) => (
            <button key={ct.value} onClick={() => setChartType(ct.value)}
              className={cn("shrink-0 flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-all",
                chartType === ct.value ? "bg-blue-600/20 text-blue-300 border border-blue-500/30"
                  : "text-slate-500 hover:text-slate-300 border border-transparent hover:border-slate-600/40")}>
              {ct.icon}{ct.label}
            </button>
          ))}
          <span className="flex-1" />
          <span className="text-[9px] text-slate-600">{rows.length}r · {chartType === "auto" ? `→${autoType}` : chartType}</span>
        </div>

        {/* Chart — explicit min-height so ResponsiveContainer never collapses */}
        <div className="flex-1 p-2" style={{ minHeight: 350 }}>
          <ChartRenderer chartType={resolvedType} columns={columns} rows={rows}
            xAxis={xAxis[0]} yAxes={values.length > 0 ? values : undefined}
            showLegend={showLegend} showGrid={showGrid} height={450} />
        </div>
      </div>
    </div>
  );
}