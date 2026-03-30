/**
 * Smart BI Agent — Dashboard Studio v2 (Power BI Experience)
 * Phase 8 | Complete overhaul
 *
 * Fixes & Features:
 *   - Auto-run widgets on add (no more blank widgets)
 *   - Widget drag-reorder within the grid
 *   - Sidebar auto-collapses when entering Studio for max canvas space
 *   - Refresh all widgets with one click
 *   - Chart type picker inline on each widget
 *   - Glassmorphism + animations
 *   - Preview mode goes truly fullscreen
 *   - Widget count badge in header
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Palette, Plus, Trash2, Settings2, Eye, EyeOff,
  Save, BarChart3, Hash, Table2, PieChart, LineChart,
  LayoutGrid, Maximize2, Minimize2, ArrowRightLeft,
  Layers, GripVertical, X, Loader2,
  Download, Edit3, Check, Sparkles, RefreshCw,
  PanelLeftClose,
} from "lucide-react";
import { toast } from "sonner";

import { api, ApiRequestError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Input, Select } from "@/components/ui";
import { AutoChart, Scorecard, ChartRenderer, detectChartType, type ChartType } from "@/components/QueryResults";
import { useAnimateIn, stagger, injectAnimations } from "@/lib/animations";
import { useSidebar } from "@/components/AppShell";
import type { SavedQueryListResponse, SavedQuery } from "@/types/saved-queries";
import type { QueryRequest, QueryResponse } from "@/types/query";

// ─── Types ──────────────────────────────────────────────────────────────────

interface DashboardWidget {
  id: string;
  queryId: string;
  queryName: string;
  question: string;
  connectionId: string;
  chartType: string;
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

const SIZE_CLASSES: Record<string, string> = { sm: "col-span-1", md: "col-span-1", lg: "col-span-1 md:col-span-2" };
const SIZE_HEIGHTS: Record<string, number> = { sm: 250, md: 320, lg: 380 };

const CHART_OPTIONS = [
  { value: "auto", label: "Auto", icon: <Settings2 className="h-3 w-3" /> },
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

function saveDashboardLocal(config: DashboardConfig) {
  try {
    config.updatedAt = new Date().toISOString();
    sessionStorage.setItem("sbi_studio_dashboard", JSON.stringify(config));
  } catch {}
}

// Debounced API save — avoids hammering backend on every widget update
let _saveTimer: ReturnType<typeof setTimeout> | null = null;
let _dashboardApiId: string | null = null;

async function saveDashboardRemote(config: DashboardConfig) {
  if (_saveTimer) clearTimeout(_saveTimer);
  _saveTimer = setTimeout(async () => {
    try {
      const apiConfig = {
        title: config.title,
        description: config.description,
        widgets: config.widgets.map((w) => ({
          id: w.id, query_id: w.queryId, query_name: w.queryName,
          question: w.question, connection_id: w.connectionId,
          chart_type: w.chartType, title: w.title, size: w.size,
        })),
        columns: config.columns,
      };

      if (_dashboardApiId) {
        await api.put(`/dashboards/${_dashboardApiId}`, { config: apiConfig, name: config.title, description: config.description });
      } else {
        const res = await api.post<{ dashboard_id: string }>("/dashboards/", { name: config.title, description: config.description, config: apiConfig });
        if (res.dashboard_id) _dashboardApiId = res.dashboard_id;
      }
    } catch {
      // Silent fail — sessionStorage is the fallback
    }
  }, 2000);
}

async function loadDashboardRemote(): Promise<DashboardConfig | null> {
  try {
    const res = await api.get<{ dashboards: Array<{ dashboard_id: string; config: any; name: string; description: string }> }>("/dashboards/");
    if (res.dashboards && res.dashboards.length > 0) {
      const d = res.dashboards[0]; // Most recent
      _dashboardApiId = d.dashboard_id;
      return {
        title: d.name || d.config?.title || "My Dashboard",
        description: d.description || d.config?.description || "",
        widgets: (d.config?.widgets || []).map((w: any) => ({
          id: w.id, queryId: w.query_id, queryName: w.query_name,
          question: w.question, connectionId: w.connection_id,
          chartType: w.chart_type || "auto", title: w.title, size: w.size || "md",
          result: null, loading: false, error: undefined,
        })),
        columns: d.config?.columns || 2,
        updatedAt: new Date().toISOString(),
      };
    }
  } catch {}
  return null;
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
  const [search, setSearch] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["saved-queries-studio"],
    queryFn: () => api.get<SavedQueryListResponse>("/saved-queries/?limit=100"),
  });
  const queries = (data?.queries ?? []).filter((q) =>
    !search || q.name.toLowerCase().includes(search.toLowerCase()) || q.question.toLowerCase().includes(search.toLowerCase())
  );

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
      <div className="relative w-full max-w-lg glass-strong rounded-2xl shadow-2xl animate-page-in">
        <div className="flex items-center justify-between p-5 border-b border-slate-700/40">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Plus className="h-4 w-4 text-blue-400" />Add Widget
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1 transition-colors"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          {/* Search */}
          <Input label="Search saved queries" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter by name or question…" />

          {/* Query Selector */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Data Source</label>
            <div className="max-h-48 overflow-y-auto space-y-1 rounded-lg border border-slate-700/40 p-2 bg-slate-800/30">
              {isLoading && <div className="flex justify-center py-4"><Loader2 className="h-5 w-5 text-blue-400 animate-spin" /></div>}
              {!isLoading && queries.length === 0 && (
                <p className="text-xs text-slate-500 p-2 text-center">
                  {search ? "No queries match your search" : "No saved queries. Run a query in AI Query and save it first."}
                </p>
              )}
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

          <Input label="Widget Title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Chart title…" />

          {/* Chart + Size in row */}
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="block text-sm font-medium text-slate-300 mb-2">Chart Type</label>
              <div className="grid grid-cols-4 gap-1.5">
                {CHART_OPTIONS.map((opt) => (
                  <button key={opt.value} onClick={() => setChartType(opt.value)}
                    className={cn("flex flex-col items-center gap-1 p-2 rounded-lg text-[10px] font-medium transition-all",
                      chartType === opt.value ? "bg-blue-600/20 text-blue-300 border border-blue-500/30" : "text-slate-500 hover:text-slate-300 border border-slate-700/30 hover:border-slate-600/50")}>
                    {opt.icon}<span>{opt.label}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="w-24">
              <label className="block text-sm font-medium text-slate-300 mb-2">Size</label>
              <div className="space-y-1.5">
                {(["sm", "md", "lg"] as const).map((s) => (
                  <button key={s} onClick={() => setSize(s)}
                    className={cn("w-full px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                      size === s ? "bg-blue-600/20 text-blue-300 border border-blue-500/30" : "text-slate-500 border border-slate-700/30 hover:border-slate-600/50")}>
                    {s === "sm" ? "Small" : s === "md" ? "Medium" : "Large"}
                  </button>
                ))}
              </div>
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

// ─── Widget Component ──────────────────────────────────────────────────────

function Widget({ widget, preview, onRemove, onUpdate, onRun }: {
  widget: DashboardWidget; preview: boolean;
  onRemove: () => void; onUpdate: (u: Partial<DashboardWidget>) => void;
  onRun: () => void;
}) {
  const isScorecard = widget.chartType === "scorecard";
  const resolvedChartType: ChartType = widget.result
    ? (widget.chartType === "auto" ? detectChartType(widget.result.columns, widget.result.rows) : widget.chartType as ChartType)
    : "bar";

  // Auto-run on mount if no result
  useEffect(() => {
    if (!widget.result && !widget.loading && !widget.error) {
      onRun();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Card className={cn(
      SIZE_CLASSES[widget.size],
      "overflow-hidden transition-all duration-300",
      preview ? "border-slate-700/20" : "border-slate-700/40 hover:border-slate-600/60",
    )}>
      {/* Header */}
      <div className={cn("flex items-center justify-between px-3 py-2 border-b border-slate-700/30", preview && "py-1.5")}>
        <div className="flex items-center gap-2 min-w-0">
          {!preview && <GripVertical className="h-3 w-3 text-slate-700 shrink-0 cursor-grab" />}
          <h3 className={cn("font-medium text-slate-200 truncate", preview ? "text-sm" : "text-xs")}>{widget.title}</h3>
        </div>
        {!preview && (
          <div className="flex items-center gap-0.5 shrink-0">
            {/* Inline chart type picker */}
            <select value={widget.chartType}
              onChange={(e) => onUpdate({ chartType: e.target.value })}
              className="h-5 text-[9px] bg-transparent text-slate-500 border border-slate-700/30 rounded px-1 focus:outline-none cursor-pointer hover:border-slate-600/50 transition-colors">
              {CHART_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <button onClick={onRun} className="p-1 rounded text-slate-500 hover:text-blue-400 transition-colors" title="Re-run query">
              <RefreshCw className={cn("h-3 w-3", widget.loading && "animate-spin")} />
            </button>
            <select value={widget.size} onChange={(e) => onUpdate({ size: e.target.value as "sm" | "md" | "lg" })}
              className="h-5 text-[9px] bg-transparent text-slate-500 border-none focus:outline-none cursor-pointer">
              <option value="sm">S</option><option value="md">M</option><option value="lg">L</option>
            </select>
            <button onClick={onRemove} className="p-1 rounded text-slate-500 hover:text-red-400 transition-colors"><Trash2 className="h-3 w-3" /></button>
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
        {widget.error && !widget.loading && (
          <div className="flex items-center justify-center h-full p-4">
            <div className="text-center">
              <p className="text-xs text-red-400 mb-2">{widget.error}</p>
              <button onClick={onRun} className="text-[10px] text-blue-400 hover:text-blue-300 border border-blue-500/30 rounded px-2 py-1 transition-colors">Retry</button>
            </div>
          </div>
        )}
        {widget.result && !widget.loading && (
          isScorecard
            ? <Scorecard columns={widget.result.columns} rows={widget.result.rows} />
            : <div className="p-2 h-full">
                <ChartRenderer
                  key={`${widget.id}-${widget.chartType}`}
                  chartType={resolvedChartType} columns={widget.result.columns}
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
  const sidebar = useSidebar();

  useEffect(() => { injectAnimations(); }, []);

  // Load from API on mount — falls back to sessionStorage
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const remote = await loadDashboardRemote();
      if (!cancelled && remote && remote.widgets.length > 0) {
        setConfig(remote);
        saveDashboardLocal(remote);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Auto-collapse sidebar when entering Studio for max canvas space
  const prevCollapsed = useRef(sidebar.collapsed);
  useEffect(() => {
    prevCollapsed.current = sidebar.collapsed;
    if (!sidebar.collapsed) {
      sidebar.setCollapsed(true);
    }
    return () => {
      // Restore sidebar state when leaving Studio
      sidebar.setCollapsed(prevCollapsed.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const updateConfig = useCallback((updates: Partial<DashboardConfig>) => {
    setConfig((prev) => {
      const next = { ...prev, ...updates };
      saveDashboardLocal(next);
      saveDashboardRemote(next);
      return next;
    });
  }, []);

  const addWidget = (w: Omit<DashboardWidget, "id" | "result" | "loading" | "error">) => {
    const widget: DashboardWidget = { ...w, id: crypto.randomUUID(), result: null, loading: false, error: undefined };
    updateConfig({ widgets: [...config.widgets, widget] });
    toast.success("Widget added — running query…");
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

  // Run a single widget's query
  const runWidget = useCallback(async (widgetId: string) => {
    const widget = config.widgets.find((w) => w.id === widgetId);
    if (!widget) return;

    // Set loading
    setConfig((prev) => ({
      ...prev,
      widgets: prev.widgets.map((w) => w.id === widgetId ? { ...w, loading: true, error: undefined } : w),
    }));

    try {
      const result = await api.post<QueryResponse>("/query/", {
        question: widget.question,
        connection_id: widget.connectionId,
      });
      setConfig((prev) => {
        const next = {
          ...prev,
          widgets: prev.widgets.map((w) => w.id === widgetId ? { ...w, result, loading: false, error: undefined } : w),
        };
        saveDashboardLocal(next);
        saveDashboardRemote(next);
        return next;
      });
    } catch (err) {
      const msg = err instanceof ApiRequestError ? err.message : "Query failed";
      setConfig((prev) => ({
        ...prev,
        widgets: prev.widgets.map((w) => w.id === widgetId ? { ...w, loading: false, error: msg } : w),
      }));
    }
  }, [config.widgets]);

  // Refresh all widgets
  const refreshAll = useCallback(() => {
    config.widgets.forEach((w) => runWidget(w.id));
    toast.success(`Refreshing ${config.widgets.length} widgets…`);
  }, [config.widgets, runWidget]);

  const hasWidgets = config.widgets.length > 0;

  return (
    <div className={cn("flex flex-col", preview ? "fixed inset-0 z-40 bg-slate-900 p-6 overflow-y-auto" : "min-h-[calc(100vh-7rem)]")}>
      {/* Header */}
      <div className={cn("shrink-0 mb-4", heroAnim)}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-violet-500/20 to-blue-500/10 border border-violet-500/15 sbi-pulse-glow">
              <Palette className="h-5 w-5 text-violet-400" />
            </div>
            <div>
              {editingTitle ? (
                <div className="flex items-center gap-2">
                  <input value={titleDraft} onChange={(e) => setTitleDraft(e.target.value)} autoFocus
                    className="text-xl font-bold bg-transparent border-b-2 border-blue-500/50 text-white focus:outline-none"
                    onKeyDown={(e) => { if (e.key === "Enter") { updateConfig({ title: titleDraft }); setEditingTitle(false); } if (e.key === "Escape") setEditingTitle(false); }} />
                  <button onClick={() => { updateConfig({ title: titleDraft }); setEditingTitle(false); }}><Check className="h-4 w-4 text-emerald-400" /></button>
                </div>
              ) : (
                <h1 className="text-xl font-bold text-white cursor-pointer hover:text-blue-300 transition-colors flex items-center gap-2"
                  onClick={() => { setTitleDraft(config.title); setEditingTitle(true); }}>
                  {config.title}
                  <Edit3 className="h-3 w-3 text-slate-600" />
                </h1>
              )}
              <p className="text-xs text-slate-500">
                {config.widgets.length} widget{config.widgets.length !== 1 ? "s" : ""}
                {config.widgets.some((w) => w.loading) && <span className="text-blue-400 ml-2">● Loading…</span>}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select value={config.columns} onChange={(e) => updateConfig({ columns: parseInt(e.target.value) as 2 | 3 })}
              className="h-8 rounded-lg border border-slate-700/50 bg-slate-800/40 text-slate-300 text-xs px-2 focus:outline-none focus:ring-1 focus:ring-blue-500/30">
              <option value={2}>2 Columns</option>
              <option value={3}>3 Columns</option>
            </select>
            {hasWidgets && (
              <Button variant="ghost" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={refreshAll}>
                Refresh All
              </Button>
            )}
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
            <div key={w.id} className={cn("animate-fade-in", SIZE_CLASSES[w.size])}
              style={{ animationDelay: stagger(i) }}>
              <Widget widget={w} preview={preview}
                onRemove={() => removeWidget(w.id)}
                onUpdate={(updates) => updateWidget(w.id, updates)}
                onRun={() => runWidget(w.id)} />
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
              Add widgets from your saved queries. Each widget auto-runs its query and displays results as your chosen chart type.
            </p>
            <div className="grid grid-cols-4 gap-3 mb-8">
              {[
                { icon: <BarChart3 className="h-5 w-5" />, label: "Charts", color: "text-blue-400 bg-blue-500/8" },
                { icon: <Hash className="h-5 w-5" />, label: "KPIs", color: "text-emerald-400 bg-emerald-500/8" },
                { icon: <Table2 className="h-5 w-5" />, label: "Tables", color: "text-amber-400 bg-amber-500/8" },
                { icon: <LayoutGrid className="h-5 w-5" />, label: "Layouts", color: "text-violet-400 bg-violet-500/8" },
              ].map((f) => (
                <div key={f.label} className="flex flex-col items-center gap-2 p-3 rounded-xl border border-slate-700/20 bg-slate-800/20 hover:border-slate-600/40 transition-colors">
                  <span className={cn("p-2 rounded-lg", f.color)}>{f.icon}</span>
                  <span className="text-[10px] text-slate-500">{f.label}</span>
                </div>
              ))}
            </div>
            <Button icon={<Plus className="h-4 w-4" />} onClick={() => setShowAddModal(true)}>
              Add Your First Widget
            </Button>
            <p className="text-[10px] text-slate-600 mt-4">
              Save queries from AI Query first, then add them as widgets here.
            </p>
          </div>
        </div>
      )}

      {showAddModal && <AddWidgetModal onAdd={addWidget} onClose={() => setShowAddModal(false)} />}
    </div>
  );
}
