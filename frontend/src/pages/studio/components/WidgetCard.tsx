/**
 * Smart BI Agent — WidgetCard + WidgetViz
 * Dashboard widget card with chart visualization, loading states, and controls.
 */

import { useMemo } from "react";
import {
  GripVertical, RefreshCw, Copy, Trash2,
  Sparkles, Lightbulb,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  ChartRenderer, Scorecard, toNumber, detectChartType,
  type ChartType,
} from "@/components/QueryResults";
import { GaugeChart } from "@/components/charts/GaugeChart";
import { WaterfallChart } from "@/components/charts/WaterfallChart";
import { FunnelChart } from "@/components/charts/FunnelChart";
import { SkeletonChart, chartTypeToSkeleton } from "@/components/SkeletonChart";
import { type CanvasWidget, SIZES } from "../lib/widget-types";

// ─── WidgetViz ───────────────────────────────────────────────────────────────

function WidgetViz({
  widget,
  onDataClick,
}: {
  widget: CanvasWidget;
  onDataClick?: (label: string, column: string) => void;
}) {
  if (!widget.result) return null;
  const { columns, rows } = widget.result;
  const ct = widget.chartType;

  if (ct === "gauge" && rows.length > 0) {
    const v = toNumber(rows[0][columns[0]]) ?? 0;
    return (
      <GaugeChart
        value={v}
        max={Math.max(v * 1.5, 100)}
        label={columns[0].replace(/_/g, " ")}
        height={SIZES[widget.size].h - 50}
      />
    );
  }
  if (ct === "waterfall" && rows.length > 0) {
    return (
      <WaterfallChart
        data={rows.slice(0, 20).map((r) => ({
          name: String(r[columns[0]] ?? ""),
          value: toNumber(r[columns[1] || columns[0]]) ?? 0,
        }))}
        height={SIZES[widget.size].h - 50}
      />
    );
  }
  if (ct === "funnel" && rows.length > 0) {
    return (
      <FunnelChart
        data={rows.slice(0, 10).map((r) => ({
          name: String(r[columns[0]] ?? ""),
          value: toNumber(r[columns[1] || columns[0]]) ?? 0,
        }))}
        height={SIZES[widget.size].h - 50}
      />
    );
  }
  if (ct === "table") {
    return (
      <div className="overflow-auto h-full text-[10px]">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700/30 sticky top-0 bg-slate-900/90 backdrop-blur-sm">
              {columns.map((c) => (
                <th
                  key={c}
                  className="text-left px-2 py-1.5 text-[9px] font-semibold text-slate-500 uppercase"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 100).map((r, i) => (
              <tr
                key={i}
                className={cn(
                  "border-b border-slate-800/20 transition-colors hover:bg-blue-500/5 cursor-pointer",
                  i % 2 !== 0 && "bg-slate-800/10"
                )}
                onClick={() =>
                  onDataClick?.(String(r[columns[0]] ?? ""), columns[0])
                }
              >
                {columns.map((c) => (
                  <td
                    key={c}
                    className="px-2 py-1 text-slate-300 truncate max-w-[120px]"
                  >
                    {String(r[c] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (ct === "scorecard") return <Scorecard columns={columns} rows={rows} />;

  const resolved: ChartType =
    ct === "auto"
      ? detectChartType(columns, rows)
      : ct === "donut"
        ? "pie"
        : (ct as ChartType);

  return (
    <ChartRenderer
      key={`${widget.id}-${ct}`}
      chartType={resolved}
      columns={columns}
      rows={rows}
      height={SIZES[widget.size].h - 50}
      showLegend={widget.size !== "sm"}
      onDataClick={onDataClick}
    />
  );
}

// ─── WidgetCard ──────────────────────────────────────────────────────────────

interface WidgetCardProps {
  widget: CanvasWidget;
  selected: boolean;
  preview: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onRun: () => void;
  onDuplicate: () => void;
  onDrillDown: (label: string, column: string) => void;
  onDragStart?: () => void;
  onDragOver?: (e: React.DragEvent) => void;
  onDragEnd?: () => void;
  isDragging?: boolean;
  onDataClick?: (label: string, column: string) => void;
  globalFilter?: { column: string; value: string } | null;
}

export function WidgetCard({
  widget,
  selected,
  preview,
  onSelect,
  onRemove,
  onRun,
  onDuplicate,
  onDragStart,
  onDragOver,
  onDragEnd,
  isDragging,
  onDataClick,
  globalFilter,
}: WidgetCardProps) {
  // Apply cross-widget filter
  const filteredWidget = useMemo(() => {
    if (!globalFilter || !widget.result) return widget;
    const { column, value } = globalFilter;
    const hasCol = widget.result.columns.includes(column);
    if (!hasCol) return widget;
    const filteredRows = widget.result.rows.filter(
      (r) => String(r[column] ?? "") === value
    );
    return {
      ...widget,
      result: {
        ...widget.result,
        rows: filteredRows,
        row_count: filteredRows.length,
      },
    };
  }, [widget, globalFilter]);

  return (
    <div
      draggable={!preview}
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", widget.id);
        e.dataTransfer.effectAllowed = "move";
        onDragStart?.();
      }}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      className={cn(
        SIZES[widget.size].span,
        "group rounded-xl border overflow-hidden",
        "transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]",
        selected && !preview
          ? "border-blue-500/40 shadow-lg shadow-blue-500/5 ring-1 ring-blue-500/20"
          : "border-slate-700/25 hover:border-slate-600/40",
        !preview && "cursor-pointer",
        isDragging && "opacity-40 scale-95"
      )}
      onClick={() => !preview && onSelect()}
      style={{ background: "rgba(15, 23, 42, 0.35)" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-700/15 bg-slate-800/15">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {!preview && (
            <GripVertical className="h-3 w-3 text-slate-700 shrink-0 cursor-grab opacity-0 group-hover:opacity-60 transition-opacity duration-200" />
          )}
          <span className="text-xs font-medium text-slate-300 truncate">
            {widget.title || "Untitled"}
          </span>
          {widget.aiInsight && (
            <Lightbulb
              className="h-2.5 w-2.5 text-amber-400/60 shrink-0"
              title="AI insight available"
            />
          )}
        </div>
        {!preview && (
          <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRun();
              }}
              className="p-1 rounded text-slate-500 hover:text-blue-400 transition-colors"
              title="Run query"
            >
              <RefreshCw
                className={cn(
                  "h-3 w-3 transition-transform duration-500",
                  widget.loading && "animate-spin"
                )}
              />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDuplicate();
              }}
              className="p-1 rounded text-slate-500 hover:text-emerald-400 transition-colors"
              title="Duplicate"
            >
              <Copy className="h-3 w-3" />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRemove();
              }}
              className="p-1 rounded text-slate-500 hover:text-red-400 transition-colors"
              title="Remove"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>

      {/* Body */}
      <div style={{ height: SIZES[widget.size].h }} className="overflow-hidden">
        {widget.loading && (
          <SkeletonChart
            type={chartTypeToSkeleton(widget.chartType)}
            height={SIZES[widget.size].h}
          />
        )}
        {widget.error && !widget.loading && (
          <div className="flex items-center justify-center h-full p-4">
            <div className="text-center max-w-xs">
              <p className="text-xs text-red-400/80 mb-2 line-clamp-3">
                {widget.error}
              </p>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onRun();
                }}
                className="text-[10px] text-blue-400 hover:text-blue-300 border border-blue-500/30 rounded-lg px-3 py-1 transition-colors duration-200"
              >
                Retry
              </button>
            </div>
          </div>
        )}
        {filteredWidget.result && !widget.loading && (
          <div className="p-1.5 h-full animate-fade-in">
            <WidgetViz widget={filteredWidget} onDataClick={onDataClick} />
          </div>
        )}
        {!widget.result && !widget.loading && !widget.error && (
          <div className="flex flex-col items-center justify-center h-full p-4 animate-fade-in">
            <Sparkles className="h-6 w-6 text-slate-700 mb-2" />
            <p className="text-[10px] text-slate-500">
              {widget.mode === "fields"
                ? "Drag columns into field wells →"
                : "Type a question in Properties →"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
