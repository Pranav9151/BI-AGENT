/**
 * Smart BI Agent — Dashboard Studio (Power BI Experience)
 * Session 12 | Full dashboard builder
 *
 * Features:
 *   - Add widgets from saved queries
 *   - Configurable chart type per widget
 *   - Responsive grid layout (2-col, 3-col)
 *   - Widget resize (small/medium/large)
 *   - Dashboard title + description editing
 *   - Save/load dashboards (sessionStorage → DB in future)
 *   - Preview mode (hide controls)
 *   - Export as image concept
 */

import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Palette, Plus, Trash2, Settings2, Eye, EyeOff,
  Save, BarChart3, Hash, Table2, PieChart, LineChart,
  LayoutGrid, Maximize2, Minimize2, ArrowRightLeft,
  Layers, GripVertical, X, ChevronDown, Loader2,
  Download, Edit3, Check, Sparkles,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Input, Select } from "@/components/ui";
import { AutoChart, Scorecard, ChartRenderer, detectChartType, type ChartType } from "@/components/QueryResults";
import { useAnimateIn, stagger, injectAnimations } from "@/lib/animations";
import type { SavedQueryListResponse, SavedQuery } from "@/types/saved-queries";
import type { QueryRequest, QueryResponse } from "@/types/query";

// ─── Types ──────────────────────────────────────────────────────────────────

interface DashboardWidget {
  id: string;
  queryId: string;
  queryName: string;
  question: string;
  connectionId: string;
  chartType: string; // "auto" | specific type
  title: string;
  size: "sm" | "md" | "lg";
  result?: QueryResponse | null;
  loading?: boolean;
  error?: string;
}

interface DashboardConfig {
  title: string;
  description: string;
  widgets: DashboardWidget[];
  columns: 2 | 3;
  updatedAt: string;
}

const EMPTY_DASHBOARD: DashboardConfig = {
  title: "My Dashboard",
  description: "Custom analytics dashboard",
  widgets: [],
  columns: 2,
  updatedAt: new Date().toISOString(),
};

const SIZE_CLASSES: Record<string, string> = {
  sm: "col-span-1",
  md: "col-span-1 md:col-span-1",
  lg: "col-span-1 md:col-span-2",
};

const SIZE_HEIGHTS: Record<string, number> = {
  sm: 250,
  md: 320,
  lg: 380,
};

const CHART_OPTIONS = [
  { value: "auto", label: "Auto Detect", icon: <Settings2 className="h-3 w-3" /> },
  { value: "bar", label: "Bar", icon: <BarChart3 className="h-3 w-3" /> },
  { value: "horizontal_bar", label: "H-Bar", icon: <ArrowRightLeft className="h-3 w-3" /> },
  { value: "stacked_bar", label: "Stacked", icon: <Layers className="h-3 w-3" /> },
  { value: "line", label: "Line", icon: <LineChart className="h-3 w-3" /> },
  { value: "area", label: "Area", icon: <LineChart className="h-3 w-3" /> },
  { value: "pie", label: "Pie", icon: <PieChart className="h-3 w-3" /> },
  { value: "scorecard", label: "KPI", icon: <Hash className="h-3 w-3" /> },
];

// ─── Persistence ────────────────────────────────────────────────────────────

function loadDashboard(): DashboardConfig {
  try {
    const s = sessionStorage.getItem("sbi_studio_dashboard");
    if (s) return JSON.parse(s);
  } catch {}
  return EMPTY_DASHBOARD;
}

function saveDashboard(config: DashboardConfig) {
  try {
    config.updatedAt = new Date().toISOString();
    sessionStorage.setItem("sbi_studio_dashboard", JSON.stringify(config));
  } catch {}
}

// ─── Add Widget Modal ───────────────────────────────────────────────────────

function AddWidgetModal({ onAdd, onClose }: {
  onAdd: (w: Omit<DashboardWidget, "id" | "result" | "loading" | "error">) => void;
  onClose: () => void;
}) {
  const [selectedQuery, setSelectedQuery] = useState<SavedQuery | null>(null);
  const [chartType, setChartType] = useState("auto");
  const [title, setTitle] = useState("");
  const [size, setSize] = useState<"sm" | "md" | "lg">("md");

  const { data } = useQuery({
    queryKey: ["saved-queries-studio"],
    queryFn: () => api.get<SavedQueryListResponse>("/saved-queries/?limit=100"),
  });
  const queries = data?.queries ?? [];

  const handleAdd = () => {
    if (!selectedQuery) { toast.error("Select a query"); return; }
    onAdd({
      queryId: selectedQuery.query_id,
      queryName: selectedQuery.name,
      question: selectedQuery.question,
      connectionId: selectedQuery.connection_id,
      chartType,
      title: title.trim() || selectedQuery.name,
      size,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-700/40">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Plus className="h-4 w-4 text-blue-400" />Add Widget
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          {/* Query Selector */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Data Source (Saved Query)</label>
            <div className="max-h-48 overflow-y-auto space-y-1 rounded-lg border border-slate-700/40 p-2">
              {queries.length === 0 && <p className="text-xs text-slate-500 p-2">No saved queries. Go to AI Query → run a query → save it first.</p>}
              {queries.map((q) => (
                <button key={q.query_id} onClick={() => { setSelectedQuery(q); if (!title) setTitle(q.name); }}
                  className={cn("w-full text-left p-2.5 rounded-lg transition-all text-xs",
                    selectedQuery?.query_id === q.query_id
                      ? "bg-blue-600/20 border border-blue-500/30 text-blue-300"
                      : "hover:bg-slate-700/40 text-slate-400 border border-transparent"
                  )}>
                  <p className="font-medium text-slate-300">{q.name}</p>
                  <p className="text-slate-500 truncate mt-0.5">{q.question}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Title */}
          <Input label="Widget Title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Chart title…" />

          {/* Chart Type */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Chart Type</label>
            <div className="grid grid-cols-4 gap-1.5">
              {CHART_OPTIONS.map((opt) => (
                <button key={opt.value} onClick={() => setChartType(opt.value)}
                  className={cn("flex flex-col items-center gap-1 p-2 rounded-lg text-[10px] font-medium transition-all",
                    chartType === opt.value
                      ? "bg-blue-600/20 text-blue-300 border border-blue-500/30"
                      : "bg-slate-700/30 text-slate-500 hover:text-slate-300 border border-transparent"
                  )}>
                  {opt.icon}{opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Size */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Size</label>
            <div className="grid grid-cols-3 gap-2">
              {([["sm", "Small"], ["md", "Medium"], ["lg", "Large (Full Width)"]] as const).map(([val, label]) => (
                <button key={val} onClick={() => setSize(val)}
                  className={cn("p-2 rounded-lg text-xs font-medium transition-all border",
                    size === val ? "bg-blue-600/20 text-blue-300 border-blue-500/30" : "bg-slate-700/30 text-slate-500 border-transparent hover:border-slate-600/40"
                  )}>{label}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 p-5 border-t border-slate-700/40">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handleAdd} disabled={!selectedQuery}>Add Widget</Button>
        </div>
      </div>
    </div>
  );
}

// ─── Widget Component ───────────────────────────────────────────────────────

function Widget({ widget, onRemove, onUpdate, preview }: {
  widget: DashboardWidget;
  onRemove: () => void;
  onUpdate: (w: Partial<DashboardWidget>) => void;
  preview: boolean;
}) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(widget.title);

  // Auto-run query on mount
  useEffect(() => {
    if (widget.result || widget.loading) return;
    runWidget();
  }, [widget.queryId]);

  const runWidget = async () => {
    onUpdate({ loading: true, error: undefined });
    try {
      const res = await api.post<QueryResponse>("/query/", {
        question: widget.question,
        connection_id: widget.connectionId,
      } as QueryRequest);
      onUpdate({ result: res, loading: false });
    } catch (err) {
      onUpdate({ loading: false, error: err instanceof ApiRequestError ? err.message : "Query failed" });
    }
  };

  const resolvedChartType: ChartType = widget.chartType === "auto" && widget.result
    ? detectChartType(widget.result.columns, widget.result.rows)
    : (widget.chartType as ChartType);

  const isScorecard = resolvedChartType === "scorecard" || (widget.result && widget.result.rows.length === 1 && widget.result.columns.length <= 3);

  return (
    <Card className={cn(
      "overflow-hidden transition-all duration-300 group",
      SIZE_CLASSES[widget.size],
      "hover:border-slate-600/60",
    )}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700/30 bg-slate-800/30">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {!preview && <GripVertical className="h-3 w-3 text-slate-700 shrink-0" />}
          {editingTitle ? (
            <div className="flex items-center gap-1 flex-1">
              <input value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)} autoFocus
                className="flex-1 h-6 bg-transparent border-b border-blue-500/50 text-xs text-slate-200 focus:outline-none"
                onKeyDown={(e) => { if (e.key === "Enter") { onUpdate({ title: titleDraft }); setEditingTitle(false); } }} />
              <button onClick={() => { onUpdate({ title: titleDraft }); setEditingTitle(false); }} className="text-emerald-400"><Check className="h-3 w-3" /></button>
            </div>
          ) : (
            <p className="text-xs font-medium text-slate-300 truncate cursor-pointer" onClick={() => !preview && setEditingTitle(true)}>
              {widget.title}
            </p>
          )}
        </div>
        {!preview && (
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
            <button onClick={runWidget} className="p-1 rounded text-slate-500 hover:text-blue-400" title="Refresh">
              <Loader2 className={cn("h-3 w-3", widget.loading && "animate-spin")} />
            </button>
            <select value={widget.size} onChange={(e) => onUpdate({ size: e.target.value as "sm" | "md" | "lg" })}
              className="h-5 text-[9px] bg-transparent text-slate-500 border-none focus:outline-none cursor-pointer">
              <option value="sm">S</option><option value="md">M</option><option value="lg">L</option>
            </select>
            <button onClick={onRemove} className="p-1 rounded text-slate-500 hover:text-red-400"><Trash2 className="h-3 w-3" /></button>
          </div>
        )}
      </div>

      {/* Content */}
      <div style={{ height: SIZE_HEIGHTS[widget.size] }} className="overflow-hidden">
        {widget.loading && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Loader2 className="h-6 w-6 text-blue-400 animate-spin mx-auto mb-2" />
              <p className="text-[10px] text-slate-500">Running query…</p>
            </div>
          </div>
        )}
        {widget.error && (
          <div className="flex items-center justify-center h-full p-4">
            <div className="text-center"><p className="text-xs text-red-400">{widget.error}</p>
              <button onClick={runWidget} className="text-[10px] text-blue-400 hover:text-blue-300 mt-2">Retry</button>
            </div>
          </div>
        )}
        {widget.result && !widget.loading && (
          isScorecard
            ? <Scorecard columns={widget.result.columns} rows={widget.result.rows} />
            : <div className="p-2 h-full">
                <ChartRenderer chartType={resolvedChartType} columns={widget.result.columns}
                  rows={widget.result.rows} height={SIZE_HEIGHTS[widget.size] - 20} showLegend={widget.size !== "sm"} />
              </div>
        )}
      </div>
    </Card>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function StudioPage() {
  const [config, setConfig] = useState<DashboardConfig>(loadDashboard);
  const [showAddModal, setShowAddModal] = useState(false);
  const [preview, setPreview] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(config.title);
  const heroAnim = useAnimateIn("fade-up", 0);

  useEffect(() => { injectAnimations(); }, []);

  const updateConfig = useCallback((updates: Partial<DashboardConfig>) => {
    setConfig((prev) => {
      const next = { ...prev, ...updates };
      saveDashboard(next);
      return next;
    });
  }, []);

  const addWidget = (w: Omit<DashboardWidget, "id" | "result" | "loading" | "error">) => {
    const widget: DashboardWidget = { ...w, id: crypto.randomUUID(), result: null, loading: false, error: undefined };
    updateConfig({ widgets: [...config.widgets, widget] });
    toast.success("Widget added");
  };

  const removeWidget = (id: string) => {
    updateConfig({ widgets: config.widgets.filter((w) => w.id !== id) });
    toast.success("Widget removed");
  };

  const updateWidget = (id: string, updates: Partial<DashboardWidget>) => {
    updateConfig({
      widgets: config.widgets.map((w) => w.id === id ? { ...w, ...updates } : w),
    });
  };

  const hasWidgets = config.widgets.length > 0;

  return (
    <div className={cn("flex flex-col", preview ? "fixed inset-0 z-40 bg-slate-900 p-6 overflow-y-auto" : "min-h-[calc(100vh-7rem)]")}>
      {/* Header */}
      <div className={cn("shrink-0 mb-4", heroAnim)}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-violet-500/20 to-blue-500/10 border border-violet-500/15 sbi-pulse-glow">
              <Palette className="h-5 w-5 text-violet-400" />
            </div>
            <div>
              {editingTitle ? (
                <div className="flex items-center gap-2">
                  <input value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)} autoFocus
                    className="text-xl font-bold bg-transparent border-b-2 border-blue-500/50 text-white focus:outline-none"
                    onKeyDown={(e) => { if (e.key === "Enter") { updateConfig({ title: titleDraft }); setEditingTitle(false); } }} />
                  <button onClick={() => { updateConfig({ title: titleDraft }); setEditingTitle(false); }}><Check className="h-4 w-4 text-emerald-400" /></button>
                </div>
              ) : (
                <h1 className="text-xl font-bold text-white cursor-pointer hover:text-blue-300 transition-colors"
                  onClick={() => { setTitleDraft(config.title); setEditingTitle(true); }}>
                  {config.title}
                </h1>
              )}
              <p className="text-xs text-slate-500">{config.description} · {config.widgets.length} widget{config.widgets.length !== 1 ? "s" : ""}</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select value={config.columns} onChange={(e) => updateConfig({ columns: parseInt(e.target.value) as 2 | 3 })}
              className="h-8 rounded-lg border border-slate-700/50 bg-slate-800/40 text-slate-300 text-xs px-2 focus:outline-none">
              <option value={2}>2 Columns</option>
              <option value={3}>3 Columns</option>
            </select>
            <Button variant={preview ? "primary" : "ghost"} size="sm"
              icon={preview ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              onClick={() => setPreview(!preview)}>
              {preview ? "Edit" : "Preview"}
            </Button>
            {!preview && (
              <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setShowAddModal(true)}>
                Add Widget
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Widget Grid */}
      {hasWidgets ? (
        <div className={cn("grid gap-4", config.columns === 3 ? "grid-cols-1 md:grid-cols-3" : "grid-cols-1 md:grid-cols-2")}>
          {config.widgets.map((w, i) => (
            <div key={w.id} className="transition-all duration-500 ease-out"
              style={{ transitionDelay: stagger(i), opacity: 1, transform: "translateY(0)" }}>
              <Widget widget={w} preview={preview}
                onRemove={() => removeWidget(w.id)}
                onUpdate={(updates) => updateWidget(w.id, updates)} />
            </div>
          ))}
        </div>
      ) : (
        /* Empty State */
        <div className={cn("flex-1 flex items-center justify-center", heroAnim)}>
          <div className="text-center max-w-md">
            <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-violet-500/15 to-blue-500/10 border border-violet-500/10 flex items-center justify-center mx-auto mb-6 sbi-float">
              <Palette className="h-10 w-10 text-violet-400/70" />
            </div>
            <h2 className="text-lg font-bold text-white mb-2">Build Your Dashboard</h2>
            <p className="text-sm text-slate-400 mb-6 leading-relaxed">
              Add widgets from your saved queries to create a custom analytics dashboard.
              Each widget auto-runs its query and displays the results as your chosen chart type.
            </p>
            <div className="grid grid-cols-4 gap-3 mb-8">
              {[
                { icon: <BarChart3 className="h-5 w-5" />, label: "Charts", color: "text-blue-400 bg-blue-500/8" },
                { icon: <Hash className="h-5 w-5" />, label: "KPIs", color: "text-emerald-400 bg-emerald-500/8" },
                { icon: <Table2 className="h-5 w-5" />, label: "Tables", color: "text-amber-400 bg-amber-500/8" },
                { icon: <LayoutGrid className="h-5 w-5" />, label: "Layouts", color: "text-violet-400 bg-violet-500/8" },
              ].map((f) => (
                <div key={f.label} className="flex flex-col items-center gap-2 p-3 rounded-xl border border-slate-700/20 bg-slate-800/20">
                  <span className={cn("p-2 rounded-lg", f.color)}>{f.icon}</span>
                  <span className="text-[10px] text-slate-500">{f.label}</span>
                </div>
              ))}
            </div>
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setShowAddModal(true)}>
              Add Your First Widget
            </Button>
            <p className="text-[10px] text-slate-600 mt-4">
              Tip: Save queries from AI Query first, then add them as widgets here.
            </p>
          </div>
        </div>
      )}

      {/* Add Widget Modal */}
      {showAddModal && <AddWidgetModal onAdd={addWidget} onClose={() => setShowAddModal(false)} />}
    </div>
  );
}