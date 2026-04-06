/**
 * Smart BI Agent — PropertiesPanel
 * Widget configuration: field wells, chart type picker, size, AI query, insight.
 */

import { useState, useEffect } from "react";
import {
  Sparkles, Send, Loader2, Lightbulb,
  BarChart3, LineChart, PieChart, Activity,
  ArrowRightLeft, Layers, Target, Grid3x3,
  Hash, Table2, Triangle, Gauge, Settings2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { FieldWell } from "./FieldWell";
import {
  type CanvasWidget,
  type WidgetSize,
  type AggFunc,
  CHART_OPTIONS,
} from "../lib/widget-types";

// ─── Chart Type Icons ────────────────────────────────────────────────────────

const CHART_ICONS: Record<string, React.ReactNode> = {
  auto: <Settings2 className="h-3.5 w-3.5" />,
  bar: <BarChart3 className="h-3.5 w-3.5" />,
  horizontal_bar: <ArrowRightLeft className="h-3.5 w-3.5" />,
  stacked_bar: <Layers className="h-3.5 w-3.5" />,
  line: <LineChart className="h-3.5 w-3.5" />,
  area: <Activity className="h-3.5 w-3.5" />,
  pie: <PieChart className="h-3.5 w-3.5" />,
  donut: <Target className="h-3.5 w-3.5" />,
  scatter: <Grid3x3 className="h-3.5 w-3.5" />,
  gauge: <Gauge className="h-3.5 w-3.5" />,
  waterfall: <BarChart3 className="h-3.5 w-3.5" />,
  funnel: <Triangle className="h-3.5 w-3.5" />,
  scorecard: <Hash className="h-3.5 w-3.5" />,
  table: <Table2 className="h-3.5 w-3.5" />,
};

// ─── PropertiesPanel ─────────────────────────────────────────────────────────

interface PropertiesPanelProps {
  widget: CanvasWidget;
  onUpdate: (u: Partial<CanvasWidget>) => void;
  onRun: () => void;
}

export function PropertiesPanel({ widget, onUpdate, onRun }: PropertiesPanelProps) {
  const [nl, setNl] = useState(widget.nlQuestion);
  useEffect(() => { setNl(widget.nlQuestion); }, [widget.id]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Title */}
      <div className="shrink-0 px-3 py-2.5 border-b border-slate-700/30">
        <input
          value={widget.title}
          onChange={(e) => onUpdate({ title: e.target.value })}
          className="text-xs font-semibold text-white bg-transparent w-full focus:outline-none border-b border-transparent focus:border-blue-500/40 transition-colors duration-200 pb-0.5"
          placeholder="Widget title"
        />
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {/* Mode Toggle */}
        <div className="flex rounded-xl border border-slate-700/40 overflow-hidden">
          {(["fields", "nlq"] as const).map((m) => (
            <button
              key={m}
              onClick={() => onUpdate({ mode: m })}
              className={cn(
                "flex-1 text-[10px] font-semibold py-2 transition-all duration-200",
                widget.mode === m
                  ? "bg-blue-600/20 text-blue-300"
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/30"
              )}
            >
              {m === "fields" ? "Field Wells" : "AI Query"}
            </button>
          ))}
        </div>

        {/* Field Wells Mode */}
        {widget.mode === "fields" ? (
          <div className="space-y-3">
            <FieldWell
              label="X-Axis (Dimension)"
              fields={widget.xAxis ? [widget.xAxis] : []}
              onDrop={(f) => onUpdate({ xAxis: f })}
              onRemove={() => onUpdate({ xAxis: null })}
              color="emerald"
              placeholder="Drop a dimension here"
            />
            <FieldWell
              label="Values (Measures)"
              fields={widget.values}
              isValues
              onDrop={(f) => {
                if (!widget.values.find((v) => v.column === f.column)) {
                  onUpdate({ values: [...widget.values, f] });
                }
              }}
              onRemove={(c) =>
                onUpdate({ values: widget.values.filter((v) => v.column !== c) })
              }
              onAggChange={(c, a) =>
                onUpdate({
                  values: widget.values.map((v) =>
                    v.column === c ? { ...v, agg: a as AggFunc } : v
                  ),
                })
              }
              color="blue"
              placeholder="Drop one or more measures"
            />
            <FieldWell
              label="Legend / Group By"
              fields={widget.legend ? [widget.legend] : []}
              onDrop={(f) => onUpdate({ legend: f })}
              onRemove={() => onUpdate({ legend: null })}
              color="violet"
              placeholder="Optional: drop a group-by field"
            />

            {/* Run Button */}
            <button
              onClick={onRun}
              disabled={
                widget.loading || (!widget.xAxis && widget.values.length === 0)
              }
              className={cn(
                "w-full flex items-center justify-center gap-2 py-3 rounded-xl",
                "bg-gradient-to-r from-blue-600/20 to-violet-600/15",
                "text-blue-300 text-[11px] font-semibold",
                "hover:from-blue-600/30 hover:to-violet-600/25",
                "disabled:opacity-30 transition-all duration-200",
                "border border-blue-500/15"
              )}
            >
              {widget.loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              {widget.loading ? "Running…" : "Run Query"}
            </button>
          </div>
        ) : (
          /* AI Query Mode */
          <div className="space-y-2">
            <div className="relative">
              <input
                value={nl}
                onChange={(e) => setNl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && nl.trim()) {
                    onUpdate({ nlQuestion: nl.trim() });
                    onRun();
                  }
                }}
                placeholder="Ask about your data…"
                className="w-full h-10 rounded-xl border border-slate-700/40 bg-slate-800/30 text-slate-200 text-[12px] pl-3 pr-10 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500/30 transition-all duration-200"
              />
              <button
                onClick={() => {
                  if (nl.trim()) {
                    onUpdate({ nlQuestion: nl.trim() });
                    onRun();
                  }
                }}
                disabled={!nl.trim() || widget.loading}
                className="absolute right-1.5 top-1.5 p-1.5 rounded-lg bg-blue-600 text-white disabled:opacity-20 hover:bg-blue-500 transition-colors duration-200"
              >
                {widget.loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          </div>
        )}

        {/* Chart Type Picker */}
        <div className="space-y-2">
          <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">
            Chart Type
          </span>
          <div className="grid grid-cols-5 gap-1.5">
            {CHART_OPTIONS.map((ct) => (
              <button
                key={ct.value}
                onClick={() => onUpdate({ chartType: ct.value })}
                className={cn(
                  "flex flex-col items-center gap-1 py-2 rounded-xl text-[8px] font-semibold transition-all duration-200",
                  widget.chartType === ct.value
                    ? "bg-blue-600/20 text-blue-300 border border-blue-500/30 shadow-sm shadow-blue-500/10"
                    : "text-slate-600 hover:text-slate-400 border border-transparent hover:border-slate-700/30"
                )}
                title={ct.label}
              >
                {CHART_ICONS[ct.value] || <BarChart3 className="h-3.5 w-3.5" />}
                <span>{ct.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Size Picker */}
        <div className="space-y-2">
          <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">
            Size
          </span>
          <div className="flex gap-1.5">
            {(["sm", "md", "lg", "xl", "full"] as WidgetSize[]).map((s) => (
              <button
                key={s}
                onClick={() => onUpdate({ size: s })}
                className={cn(
                  "flex-1 py-1.5 rounded-xl text-[10px] font-semibold transition-all duration-200",
                  widget.size === s
                    ? "bg-blue-600/20 text-blue-300 border border-blue-500/30"
                    : "text-slate-600 border border-slate-700/30 hover:border-slate-600/40"
                )}
              >
                {s.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {/* AI Insight */}
        {widget.aiInsight && (
          <div className="space-y-1.5">
            <span className="text-[9px] font-bold text-amber-400/70 uppercase flex items-center gap-1">
              <Lightbulb className="h-3 w-3" /> AI Insight
            </span>
            <p className="text-[10px] text-slate-400 leading-relaxed bg-amber-500/5 border border-amber-500/10 rounded-xl p-2.5">
              {widget.aiInsight}
            </p>
          </div>
        )}

        {/* SQL Preview */}
        {widget.generatedSql && (
          <div className="space-y-1.5">
            <span className="text-[9px] font-bold text-slate-600 uppercase">
              Generated SQL
            </span>
            <pre className="text-[9px] text-slate-500 bg-slate-800/40 rounded-xl p-2.5 overflow-x-auto border border-slate-700/20 whitespace-pre-wrap break-all font-mono">
              {widget.generatedSql}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
