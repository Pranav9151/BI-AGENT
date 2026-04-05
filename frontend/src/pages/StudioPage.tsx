/**
 * Smart BI Agent — Dashboard Studio v5 (Phase 12)
 * "The Power BI Killer" — Refactored Architecture
 *
 * ★ WHAT CHANGED:
 *   - 1060-line monolith → ~280-line orchestrator + 8 focused modules
 *   - Fixed anomaly detection (no more false categorical trends)
 *   - Fixed SQL builder (no more cross-join cartesian products)
 *   - Improved FieldWell UX (larger targets, semantic drop hints)
 *   - Layout sidebar bug fix (responsive to sidebar state changes)
 *   - All useCallback/useEffect ordering preserved (TDZ-safe)
 *
 * Module structure:
 *   pages/studio/
 *     lib/widget-types.ts       - Types, constants, serialization
 *     lib/sql-builder.ts        - SQL generation (cross-join safe)
 *     hooks/useDashboardState.ts - Dashboard CRUD, gallery, connections
 *     hooks/useWidgetOps.ts     - Widget CRUD, query execution, DnD
 *     components/DataPanel.tsx   - Schema browser sidebar
 *     components/FieldWell.tsx   - Drag-and-drop field wells
 *     components/PropertiesPanel.tsx - Widget configuration
 *     components/WidgetCard.tsx  - Chart rendering card
 *     components/DashboardGallery.tsx - Dashboard tabs
 *     components/AiGenerateModal.tsx - AI dashboard builder
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Palette, Plus, Eye, EyeOff,
  RefreshCw, Edit3, Check, Save,
  Link2, Wand2, Sparkles, X,
  Undo2, Redo2,
} from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui";
import { DrillDownModal } from "@/components/DrillDownModal";
import { useSidebar } from "@/contexts/sidebar";

import { useDashboardState } from "./studio/hooks/useDashboardState";
import { useWidgetOps } from "./studio/hooks/useWidgetOps";
import { DataPanel } from "./studio/components/DataPanel";
import { PropertiesPanel } from "./studio/components/PropertiesPanel";
import { WidgetCard } from "./studio/components/WidgetCard";
import { DashboardGallery } from "./studio/components/DashboardGallery";
import { AiGenerateModal } from "./studio/components/AiGenerateModal";

// ─── Empty Canvas ────────────────────────────────────────────────────────────

function EmptyCanvas({ onAdd, onAiGenerate }: { onAdd: () => void; onAiGenerate: () => void }) {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center max-w-lg animate-fade-in">
        <div className="w-24 h-24 rounded-3xl bg-gradient-to-br from-blue-500/10 via-violet-500/10 to-pink-500/10 border border-blue-500/10 flex items-center justify-center mx-auto mb-8 sbi-float">
          <Palette className="h-12 w-12 text-blue-400/50" />
        </div>
        <h2 className="text-xl font-bold text-white mb-2">Dashboard Canvas</h2>
        <p className="text-sm text-slate-400 mb-8 leading-relaxed">
          Build interactive dashboards by dragging database columns into visuals,
          or let AI create one for you.
        </p>
        <div className="flex items-center justify-center gap-3">
          <Button icon={<Plus className="h-4 w-4" />} onClick={onAdd}>
            Add Visual
          </Button>
          <Button
            variant="ghost"
            icon={<Wand2 className="h-4 w-4" />}
            onClick={onAiGenerate}
            className="border border-violet-500/20 text-violet-300 hover:bg-violet-500/10"
          >
            AI Generate Dashboard
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function StudioPage() {
  const sidebar = useSidebar();

  // ── State Hooks ──
  const state = useDashboardState();
  const {
    dashboard, setDashboard,
    selWidgetId, setSelWidgetId,
    globalFilter, setGlobalFilter,
    connections, schemaTables, schemaLoading,
    allDashboards, saveMut,
    handleSave, handleShareSnapshot,
    handleCreate, handleLoadDashboard, handleDeleteDashboard,
  } = state;

  const [preview, setPreview] = useState(false);
  const [editTitle, setEditTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [schemaSearch, setSchemaSearch] = useState("");
  const [showAiModal, setShowAiModal] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(0);
  const [drillDown, setDrillDown] = useState<{ label: string; column: string } | null>(null);
  const [propsOpen, setPropsOpen] = useState(true);

  // ── Undo/Redo ──
  // Track dashboard widget snapshots for undo/redo (Ctrl+Z / Ctrl+Shift+Z)
  const historyRef = useRef<{ past: string[]; future: string[] }>({ past: [], future: [] });
  const lastSnapshotRef = useRef<string>("");

  // Snapshot on significant changes (widget add/remove/reorder)
  const snapshotWidgets = useCallback(() => {
    const snap = JSON.stringify(dashboard.widgets.map(w => ({ id: w.id, title: w.title, xAxis: w.xAxis, values: w.values, legend: w.legend, chartType: w.chartType, size: w.size, mode: w.mode, nlQuestion: w.nlQuestion })));
    if (snap !== lastSnapshotRef.current) {
      historyRef.current.past.push(lastSnapshotRef.current);
      if (historyRef.current.past.length > 30) historyRef.current.past.shift();
      historyRef.current.future = [];
      lastSnapshotRef.current = snap;
    }
  }, [dashboard.widgets]);

  const handleUndo = useCallback(() => {
    const h = historyRef.current;
    if (h.past.length === 0) return;
    const prev = h.past.pop()!;
    h.future.push(lastSnapshotRef.current);
    lastSnapshotRef.current = prev;
    if (prev) {
      try {
        const widgets = JSON.parse(prev);
        setDashboard(d => ({ ...d, widgets: d.widgets.map(w => {
          const saved = widgets.find((s: any) => s.id === w.id);
          return saved ? { ...w, ...saved } : w;
        }).filter(w => widgets.some((s: any) => s.id === w.id)) }));
        toast.success("Undone");
      } catch {}
    }
  }, [setDashboard]);

  const handleRedo = useCallback(() => {
    const h = historyRef.current;
    if (h.future.length === 0) return;
    const next = h.future.pop()!;
    h.past.push(lastSnapshotRef.current);
    lastSnapshotRef.current = next;
    if (next) {
      try {
        const widgets = JSON.parse(next);
        setDashboard(d => ({ ...d, widgets: d.widgets.map(w => {
          const saved = widgets.find((s: any) => s.id === w.id);
          return saved ? { ...w, ...saved } : w;
        }).filter(w => widgets.some((s: any) => s.id === w.id)) }));
        toast.success("Redone");
      } catch {}
    }
  }, [setDashboard]);

  // ── Widget Operations (MUST be declared before wrapped callbacks — TDZ-safe) ──
  const ops = useWidgetOps({
    dashboard,
    setDashboard,
    selWidgetId,
    setSelWidgetId,
    setDrillDown,
  });

  // Take snapshot before widget mutations
  const wrappedAddWidget = useCallback(() => { snapshotWidgets(); ops.addWidget(); }, [snapshotWidgets, ops.addWidget]);
  const wrappedRemoveWidget = useCallback((id: string) => { snapshotWidgets(); ops.removeWidget(id); }, [snapshotWidgets, ops.removeWidget]);
  const wrappedDuplicateWidget = useCallback((id: string) => { snapshotWidgets(); ops.duplicateWidget(id); }, [snapshotWidgets, ops.duplicateWidget]);

  // Auto-collapse sidebar on mount
  const prevCollapsed = useRef(sidebar.collapsed);
  useEffect(() => {
    prevCollapsed.current = sidebar.collapsed;
    if (!sidebar.collapsed) sidebar.setCollapsed(true);
    return () => { sidebar.setCollapsed(prevCollapsed.current); };
  }, []); // eslint-disable-line

  // ── Effects (AFTER all callbacks — TDZ-safe) ──

  // Auto-refresh timer
  useEffect(() => {
    if (autoRefresh <= 0 || dashboard.widgets.length === 0) return;
    const timer = setInterval(() => {
      dashboard.widgets.forEach((w) => {
        if (w.result || w.generatedSql || w.nlQuestion) ops.runWidget(w.id);
      });
    }, autoRefresh * 1000);
    return () => clearInterval(timer);
  }, [autoRefresh, dashboard.widgets.length]); // eslint-disable-line

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "z" && e.shiftKey) {
        e.preventDefault();
        handleRedo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "y") {
        e.preventDefault();
        handleRedo();
        return;
      }
      if (e.key === "Delete" && selWidgetId && !e.ctrlKey && !e.metaKey) {
        const t = e.target as HTMLElement;
        if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) return;
        e.preventDefault();
        wrappedRemoveWidget(selWidgetId);
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "d" && selWidgetId) {
        e.preventDefault();
        wrappedDuplicateWidget(selWidgetId);
        return;
      }
      if (e.key === "Escape") {
        if (preview) { setPreview(false); return; }
        if (selWidgetId) { setSelWidgetId(null); return; }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selWidgetId, preview, handleSave, handleUndo, handleRedo, wrappedRemoveWidget, wrappedDuplicateWidget]);

  const selWidget = dashboard.widgets.find((w) => w.id === selWidgetId);

  // Filter schema tables by search
  const filteredTables = schemaSearch
    ? schemaTables.filter((t) => {
        const q = schemaSearch.toLowerCase();
        return t.name.toLowerCase().includes(q) || t.columns.some((c) => c.name.toLowerCase().includes(q));
      })
    : schemaTables;

  return (
    <div className={cn("absolute inset-0 flex flex-col overflow-hidden bg-slate-900", preview && "fixed inset-0 z-40 bg-slate-900")}>
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
              className="h-7 rounded-lg border border-slate-700/40 bg-slate-800/40 text-slate-300 text-[10px] px-2 focus:outline-none focus:ring-1 focus:ring-blue-500/30 transition-all max-w-[140px]">
              <option value="">Connection…</option>
              {connections.map((c) => <option key={c.connection_id} value={c.connection_id}>{c.name}</option>)}
            </select>
            {dashboard.widgets.length > 0 && (
              <>
                <Button variant="ghost" size="sm" icon={<RefreshCw className="h-3 w-3" />} onClick={ops.refreshAll} className="h-7 text-[10px]">Refresh</Button>
                <select value={autoRefresh} onChange={(e) => { setAutoRefresh(Number(e.target.value)); if (Number(e.target.value) > 0) toast.success(`Auto-refresh: every ${e.target.value}s`); }}
                  className="h-7 rounded-lg border border-slate-700/40 bg-slate-800/40 text-slate-400 text-[9px] px-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500/30 w-14">
                  <option value={0}>Off</option>
                  <option value={30}>30s</option>
                  <option value={60}>1m</option>
                  <option value={300}>5m</option>
                </select>
              </>
            )}
            <Button variant="ghost" size="sm" icon={<Save className="h-3 w-3" />} onClick={handleSave} isLoading={saveMut.isPending} className="h-7 text-[10px]">Save</Button>
            <Button variant="ghost" size="sm" icon={<Undo2 className="h-3 w-3" />} onClick={handleUndo} disabled={historyRef.current.past.length === 0} className="h-7 text-[10px]" title="Undo (Ctrl+Z)">Undo</Button>
            <Button variant="ghost" size="sm" icon={<Redo2 className="h-3 w-3" />} onClick={handleRedo} disabled={historyRef.current.future.length === 0} className="h-7 text-[10px]" title="Redo (Ctrl+Shift+Z)">Redo</Button>
            <Button variant="ghost" size="sm" icon={<Link2 className="h-3 w-3" />} onClick={handleShareSnapshot} className="h-7 text-[10px]" title="Copy shareable snapshot URL">Share</Button>
            <Button variant={preview ? "primary" : "ghost"} size="sm"
              icon={preview ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
              onClick={() => setPreview(!preview)} className="h-7 text-[10px]">{preview ? "Edit" : "Preview"}</Button>
            {!preview && <Button size="sm" icon={<Plus className="h-3 w-3" />} onClick={wrappedAddWidget} className="h-7 text-[10px]">Visual</Button>}
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
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Data Panel */}
        {!preview && (
          <DataPanel
            tables={filteredTables}
            loading={schemaLoading}
            hasConnection={!!dashboard.connectionId}
            schemaSearch={schemaSearch}
            onSearchChange={setSchemaSearch}
          />
        )}

        {/* Canvas */}
        <div className="flex-1 overflow-y-auto p-4 min-w-0">
          {/* Global Filter Bar */}
          {globalFilter && (
            <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-blue-500/8 border border-blue-500/15 animate-fade-in">
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
                <WidgetCard key={w.id} widget={w}
                  selected={selWidgetId === w.id} preview={preview}
                  onSelect={() => { setSelWidgetId(w.id); setPropsOpen(true); }}
                  onRemove={() => wrappedRemoveWidget(w.id)}
                  onRun={() => ops.runWidget(w.id)}
                  onDuplicate={() => wrappedDuplicateWidget(w.id)}
                  onDrillDown={(label, column) => setDrillDown({ label, column })}
                  onDragStart={() => ops.handleDragStart(w.id)}
                  onDragOver={(e) => ops.handleDragOver(e, w.id)}
                  onDragEnd={ops.handleDragEnd}
                  isDragging={ops.dragWidgetId === w.id}
                  onDataClick={(label, column) => setGlobalFilter({ column, value: label })}
                  globalFilter={globalFilter}
                />
              ))}
            </div>
          ) : (
            <EmptyCanvas onAdd={wrappedAddWidget} onAiGenerate={() => setShowAiModal(true)} />
          )}
        </div>

        {/* Properties Panel */}
        {!preview && selWidget && propsOpen && (
          <div className="shrink-0 w-60 border-l border-slate-700/25 bg-slate-900/40 transition-all duration-300 animate-slide-in-right">
            <PropertiesPanel
              widget={selWidget}
              onUpdate={(u) => ops.updateWidget(selWidget.id, u)}
              onRun={() => ops.runWidget(selWidget.id)}
            />
          </div>
        )}
      </div>

      {/* AI Generate Modal */}
      {showAiModal && (
        <AiGenerateModal
          onGenerate={(prompt) => {
            setShowAiModal(false);
            ops.handleAiGenerate(prompt);
          }}
          onClose={() => setShowAiModal(false)}
        />
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
