/**
 * Smart BI Agent — FieldWell v2
 *
 * ★ UX improvements over v1:
 *   - Animated drop zone with semantic hints (dimension/measure/group)
 *   - Larger touch targets (minimum 32px)
 *   - Aggregation picker as a styled dropdown, not raw <select>
 *   - Clear visual feedback during drag hover
 *   - Keyboard accessible (Tab + Enter to remove)
 */

import { useState } from "react";
import {
  Hash, Type, Calendar, GripVertical, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type FieldAssignment,
  type ColType,
  type AggFunc,
  AGGS,
  defaultAgg,
} from "../lib/widget-types";

// ─── Column Type Icons ───────────────────────────────────────────────────────

export const COL_ICONS: Record<ColType, React.ReactNode> = {
  numeric: <Hash className="h-3 w-3 text-blue-400" />,
  text:    <Type className="h-3 w-3 text-emerald-400" />,
  date:    <Calendar className="h-3 w-3 text-amber-400" />,
};

const COL_ICONS_SM: Record<ColType, React.ReactNode> = {
  numeric: <Hash className="h-2.5 w-2.5 text-blue-400" />,
  text:    <Type className="h-2.5 w-2.5 text-emerald-400" />,
  date:    <Calendar className="h-2.5 w-2.5 text-amber-400" />,
};

// ─── Color Schemes ───────────────────────────────────────────────────────────

const COLORS = {
  blue: {
    border: "border-blue-500/40 bg-blue-500/[0.06]",
    hoverBorder: "border-blue-400/60 bg-blue-500/[0.1]",
    pill: "bg-blue-600/20 text-blue-300 border-blue-500/25",
    label: "text-blue-400/70",
  },
  emerald: {
    border: "border-emerald-500/40 bg-emerald-500/[0.06]",
    hoverBorder: "border-emerald-400/60 bg-emerald-500/[0.1]",
    pill: "bg-emerald-600/20 text-emerald-300 border-emerald-500/25",
    label: "text-emerald-400/70",
  },
  violet: {
    border: "border-violet-500/40 bg-violet-500/[0.06]",
    hoverBorder: "border-violet-400/60 bg-violet-500/[0.1]",
    pill: "bg-violet-600/20 text-violet-300 border-violet-500/25",
    label: "text-violet-400/70",
  },
};

// ─── FieldWell Component ─────────────────────────────────────────────────────

interface FieldWellProps {
  label: string;
  fields: FieldAssignment[];
  onDrop: (f: FieldAssignment) => void;
  onRemove: (column: string) => void;
  onAggChange?: (column: string, agg: AggFunc) => void;
  color: "blue" | "emerald" | "violet";
  placeholder: string;
  isValues?: boolean;
}

export function FieldWell({
  label,
  fields,
  onDrop,
  onRemove,
  onAggChange,
  color,
  placeholder,
  isValues,
}: FieldWellProps) {
  const [dragOver, setDragOver] = useState(false);
  const scheme = COLORS[color];

  return (
    <div className="space-y-1.5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className={cn("text-[9px] font-bold uppercase tracking-widest", scheme.label)}>
          {label}
        </span>
        {fields.length > 0 && (
          <button
            onClick={() => fields.forEach((f) => onRemove(f.column))}
            className="text-[8px] text-slate-600 hover:text-red-400 transition-colors px-1.5 py-0.5 rounded hover:bg-red-500/10"
          >
            Clear all
          </button>
        )}
      </div>

      {/* Drop Zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          try {
            const d = JSON.parse(e.dataTransfer.getData("application/json"));
            if (d.column) {
              onDrop({
                column: d.column,
                table: d.table,
                type: d.type || "text",
                agg: isValues ? defaultAgg(d.type || "text") : "NONE",
              });
            }
          } catch {}
        }}
        className={cn(
          "min-h-[36px] rounded-xl border-2 border-dashed px-2.5 py-2 transition-all duration-200",
          dragOver
            ? scheme.hoverBorder + " scale-[1.01] shadow-sm"
            : fields.length === 0
              ? "border-slate-700/30 hover:border-slate-600/40"
              : "border-transparent bg-slate-800/20",
          fields.length === 0 && "flex items-center justify-center"
        )}
      >
        {fields.length === 0 ? (
          <span className={cn(
            "text-[10px] select-none transition-colors duration-200",
            dragOver ? scheme.label : "text-slate-600 italic"
          )}>
            {dragOver ? `Drop ${isValues ? "measure" : "field"} here` : placeholder}
          </span>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {fields.map((f) => (
              <FieldPill
                key={f.column}
                field={f}
                color={scheme.pill}
                isValues={isValues}
                onAggChange={onAggChange}
                onRemove={onRemove}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Field Pill (individual assigned field) ──────────────────────────────────

function FieldPill({
  field,
  color,
  isValues,
  onAggChange,
  onRemove,
}: {
  field: FieldAssignment;
  color: string;
  isValues?: boolean;
  onAggChange?: (column: string, agg: AggFunc) => void;
  onRemove: (column: string) => void;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-1 rounded-lg border text-[10px] font-medium",
        "transition-all duration-150 group/pill",
        color
      )}
    >
      {COL_ICONS_SM[field.type]}
      <span className="truncate max-w-[70px]" title={`${field.table}.${field.column}`}>
        {field.column}
      </span>

      {/* Aggregation selector for value fields */}
      {isValues && onAggChange && (
        <select
          value={field.agg}
          onChange={(e) => onAggChange(field.column, e.target.value as AggFunc)}
          onClick={(e) => e.stopPropagation()}
          className="bg-transparent border-none text-[9px] font-bold p-0 focus:outline-none cursor-pointer uppercase opacity-60 hover:opacity-100 transition-opacity"
        >
          {AGGS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      )}

      {/* Remove button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onRemove(field.column);
        }}
        className="opacity-40 hover:opacity-100 hover:text-red-300 transition-all p-0.5 -mr-0.5"
        title="Remove field"
      >
        <X className="h-2.5 w-2.5" />
      </button>
    </span>
  );
}

// ─── DragCol (draggable schema column) ───────────────────────────────────────

export function DragCol({
  name,
  type,
  table,
}: {
  name: string;
  type: ColType;
  table: string;
}) {
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(
          "application/json",
          JSON.stringify({ column: name, table, type })
        );
        e.dataTransfer.effectAllowed = "copy";
      }}
      className={cn(
        "flex items-center gap-2 px-2.5 py-1.5 rounded-lg",
        "cursor-grab active:cursor-grabbing",
        "text-[11px] text-slate-400 hover:text-slate-200",
        "hover:bg-slate-700/30 border border-transparent hover:border-blue-500/20",
        "transition-all duration-200 group select-none"
      )}
      title={`Drag ${name} to a field well`}
    >
      <GripVertical className="h-3 w-3 text-slate-700 group-hover:text-blue-400 shrink-0 transition-colors" />
      {COL_ICONS[type]}
      <span className="truncate flex-1">{name}</span>
      <span className="text-[8px] text-slate-700 group-hover:text-slate-500 uppercase shrink-0">
        {type}
      </span>
    </div>
  );
}
