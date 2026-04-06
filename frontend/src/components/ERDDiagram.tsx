/**
 * Smart BI Agent — ERD Diagram
 * Interactive entity-relationship diagram rendered with SVG.
 *
 * Features:
 *   - Auto-layout tables in a grid
 *   - FK relationship lines with arrow markers
 *   - Hover highlighting of related tables
 *   - Click to select/focus a table
 *   - Column type badges
 *   - Zoom controls
 */

import { useState, useMemo, useRef, useCallback } from "react";
import { ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface Relationship {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  constraint_name?: string;
}

interface TableSchema {
  name: string;
  columns: { name: string; type: string; primary_key?: boolean }[];
}

interface ERDDiagramProps {
  tables: TableSchema[];
  relationships: Relationship[];
}

// ─── Layout Constants ────────────────────────────────────────────────────────

const TABLE_W = 200;
const HEADER_H = 32;
const COL_H = 22;
const TABLE_PAD = 40;
const MAX_COLS_SHOWN = 12;

function typeColor(type: string): string {
  const t = type.toLowerCase();
  if (/int|numeric|decimal|float|double|real/.test(t)) return "#60a5fa";
  if (/char|text|string|varchar/.test(t)) return "#34d399";
  if (/date|time/.test(t)) return "#fbbf24";
  if (/bool/.test(t)) return "#a78bfa";
  return "#94a3b8";
}

// ─── Layout Algorithm ────────────────────────────────────────────────────────

interface TableBox {
  name: string;
  x: number;
  y: number;
  w: number;
  h: number;
  columns: { name: string; type: string; primary_key?: boolean }[];
}

function layoutTables(tables: TableSchema[]): TableBox[] {
  const cols = Math.ceil(Math.sqrt(tables.length));
  const boxes: TableBox[] = [];

  tables.forEach((t, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const visibleCols = Math.min(t.columns.length, MAX_COLS_SHOWN);
    const h = HEADER_H + visibleCols * COL_H + 8;

    boxes.push({
      name: t.name,
      x: col * (TABLE_W + TABLE_PAD) + TABLE_PAD,
      y: row * (280 + TABLE_PAD) + TABLE_PAD,
      w: TABLE_W,
      h,
      columns: t.columns.slice(0, MAX_COLS_SHOWN),
    });
  });

  return boxes;
}

// ─── Relationship Line Paths ─────────────────────────────────────────────────

interface RelLine {
  from: Relationship;
  path: string;
  fromPt: { x: number; y: number };
  toPt: { x: number; y: number };
}

function buildRelLines(
  boxes: TableBox[],
  relationships: Relationship[]
): RelLine[] {
  const boxMap = new Map(boxes.map((b) => [b.name, b]));

  return relationships
    .map((rel) => {
      const fromBox = boxMap.get(rel.from_table);
      const toBox = boxMap.get(rel.to_table);
      if (!fromBox || !toBox) return null;

      // Find column Y positions
      const fromColIdx = fromBox.columns.findIndex(
        (c) => c.name === rel.from_column
      );
      const toColIdx = toBox.columns.findIndex(
        (c) => c.name === rel.to_column
      );

      const fromY =
        fromBox.y +
        HEADER_H +
        (fromColIdx >= 0 ? fromColIdx : 0) * COL_H +
        COL_H / 2;
      const toY =
        toBox.y +
        HEADER_H +
        (toColIdx >= 0 ? toColIdx : 0) * COL_H +
        COL_H / 2;

      // Determine connection side
      let fromX: number, toX: number;
      const fromCenterX = fromBox.x + fromBox.w / 2;
      const toCenterX = toBox.x + toBox.w / 2;

      if (fromCenterX < toCenterX) {
        fromX = fromBox.x + fromBox.w;
        toX = toBox.x;
      } else {
        fromX = fromBox.x;
        toX = toBox.x + toBox.w;
      }

      // Bezier curve
      const midX = (fromX + toX) / 2;
      const path = `M ${fromX} ${fromY} C ${midX} ${fromY}, ${midX} ${toY}, ${toX} ${toY}`;

      return {
        from: rel,
        path,
        fromPt: { x: fromX, y: fromY },
        toPt: { x: toX, y: toY },
      };
    })
    .filter((r): r is RelLine => r !== null);
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ERDDiagram({ tables, relationships }: ERDDiagramProps) {
  const [zoom, setZoom] = useState(1);
  const [hoveredTable, setHoveredTable] = useState<string | null>(null);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const boxes = useMemo(() => layoutTables(tables), [tables]);
  const relLines = useMemo(
    () => buildRelLines(boxes, relationships),
    [boxes, relationships]
  );

  // Calculate SVG viewBox
  const maxX = Math.max(...boxes.map((b) => b.x + b.w), 600) + TABLE_PAD;
  const maxY = Math.max(...boxes.map((b) => b.y + b.h), 400) + TABLE_PAD;

  // Highlight logic
  const relatedTables = useMemo(() => {
    const target = hoveredTable || selectedTable;
    if (!target) return new Set<string>();
    const related = new Set<string>();
    relationships.forEach((r) => {
      if (r.from_table === target) related.add(r.to_table);
      if (r.to_table === target) related.add(r.from_table);
    });
    return related;
  }, [hoveredTable, selectedTable, relationships]);

  const isHighlighted = useCallback(
    (name: string) => {
      const target = hoveredTable || selectedTable;
      if (!target) return true;
      return name === target || relatedTables.has(name);
    },
    [hoveredTable, selectedTable, relatedTables]
  );

  const isRelHighlighted = useCallback(
    (rel: Relationship) => {
      const target = hoveredTable || selectedTable;
      if (!target) return true;
      return rel.from_table === target || rel.to_table === target;
    },
    [hoveredTable, selectedTable]
  );

  if (tables.length === 0) return null;

  return (
    <div className="relative rounded-xl border border-slate-700/30 bg-slate-900/50 overflow-hidden">
      {/* Zoom Controls */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-1">
        <button
          onClick={() => setZoom((z) => Math.min(z + 0.2, 2))}
          className="p-1.5 rounded-lg bg-slate-800/80 border border-slate-700/40 text-slate-400 hover:text-white transition-colors"
        >
          <ZoomIn className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => setZoom((z) => Math.max(z - 0.2, 0.3))}
          className="p-1.5 rounded-lg bg-slate-800/80 border border-slate-700/40 text-slate-400 hover:text-white transition-colors"
        >
          <ZoomOut className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => setZoom(1)}
          className="p-1.5 rounded-lg bg-slate-800/80 border border-slate-700/40 text-slate-400 hover:text-white transition-colors"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <span className="text-[10px] text-slate-600 ml-1">
          {Math.round(zoom * 100)}%
        </span>
      </div>

      {/* Legend */}
      <div className="absolute bottom-3 left-3 z-10 flex items-center gap-3 px-2.5 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700/40">
        <span className="text-[9px] text-slate-500 uppercase font-semibold">
          {tables.length} tables · {relationships.length} relationships
        </span>
      </div>

      {/* SVG Canvas */}
      <div
        className="overflow-auto"
        style={{ maxHeight: 520 }}
      >
        <svg
          ref={svgRef}
          width={maxX * zoom}
          height={maxY * zoom}
          viewBox={`0 0 ${maxX} ${maxY}`}
          className="select-none"
          onClick={() => setSelectedTable(null)}
        >
          <defs>
            <marker
              id="arrowhead"
              markerWidth="8"
              markerHeight="6"
              refX="8"
              refY="3"
              orient="auto"
            >
              <polygon
                points="0 0, 8 3, 0 6"
                fill="#60a5fa"
                opacity="0.6"
              />
            </marker>
            <marker
              id="arrowhead-active"
              markerWidth="8"
              markerHeight="6"
              refX="8"
              refY="3"
              orient="auto"
            >
              <polygon points="0 0, 8 3, 0 6" fill="#3b82f6" />
            </marker>
          </defs>

          {/* Relationship Lines */}
          {relLines.map((rl, i) => {
            const active = isRelHighlighted(rl.from);
            return (
              <path
                key={i}
                d={rl.path}
                fill="none"
                stroke={active ? "#3b82f6" : "#334155"}
                strokeWidth={active ? 2 : 1}
                strokeDasharray={active ? "none" : "4 2"}
                opacity={active ? 0.8 : 0.3}
                markerEnd={
                  active
                    ? "url(#arrowhead-active)"
                    : "url(#arrowhead)"
                }
                className="transition-all duration-200"
              />
            );
          })}

          {/* Table Boxes */}
          {boxes.map((box) => {
            const highlighted = isHighlighted(box.name);
            const isSelected = selectedTable === box.name;

            return (
              <g
                key={box.name}
                onMouseEnter={() => setHoveredTable(box.name)}
                onMouseLeave={() => setHoveredTable(null)}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedTable(
                    selectedTable === box.name ? null : box.name
                  );
                }}
                className="cursor-pointer"
                opacity={highlighted ? 1 : 0.25}
              >
                {/* Shadow */}
                <rect
                  x={box.x + 2}
                  y={box.y + 2}
                  width={box.w}
                  height={box.h}
                  rx={8}
                  fill="#000"
                  opacity={0.2}
                />

                {/* Body */}
                <rect
                  x={box.x}
                  y={box.y}
                  width={box.w}
                  height={box.h}
                  rx={8}
                  fill="#0f172a"
                  stroke={isSelected ? "#3b82f6" : "#334155"}
                  strokeWidth={isSelected ? 2 : 1}
                  className="transition-all duration-200"
                />

                {/* Header */}
                <rect
                  x={box.x}
                  y={box.y}
                  width={box.w}
                  height={HEADER_H}
                  rx={8}
                  fill={isSelected ? "#1e3a5f" : "#1e293b"}
                  className="transition-all duration-200"
                />
                <rect
                  x={box.x}
                  y={box.y + HEADER_H - 8}
                  width={box.w}
                  height={8}
                  fill={isSelected ? "#1e3a5f" : "#1e293b"}
                />

                {/* Table name */}
                <text
                  x={box.x + 10}
                  y={box.y + 20}
                  fill={isSelected ? "#93c5fd" : "#e2e8f0"}
                  fontSize="12"
                  fontWeight="600"
                  fontFamily="ui-monospace, monospace"
                >
                  {box.name.length > 22
                    ? box.name.slice(0, 20) + "…"
                    : box.name}
                </text>

                {/* Columns */}
                {box.columns.map((col, ci) => {
                  const y = box.y + HEADER_H + ci * COL_H + 15;
                  return (
                    <g key={col.name}>
                      {/* PK indicator */}
                      {col.primary_key && (
                        <circle
                          cx={box.x + 12}
                          cy={y - 3}
                          r={3}
                          fill="#f59e0b"
                          opacity={0.6}
                        />
                      )}

                      {/* Column name */}
                      <text
                        x={box.x + (col.primary_key ? 22 : 10)}
                        y={y}
                        fill="#94a3b8"
                        fontSize="10"
                        fontFamily="ui-monospace, monospace"
                      >
                        {col.name.length > 18
                          ? col.name.slice(0, 16) + "…"
                          : col.name}
                      </text>

                      {/* Type badge */}
                      <text
                        x={box.x + box.w - 10}
                        y={y}
                        fill={typeColor(col.type)}
                        fontSize="8"
                        fontFamily="ui-monospace, monospace"
                        textAnchor="end"
                        opacity={0.6}
                      >
                        {col.type}
                      </text>
                    </g>
                  );
                })}

                {/* Overflow indicator */}
                {(tables.find((t) => t.name === box.name)?.columns.length ?? 0) > MAX_COLS_SHOWN && (
                  <text
                    x={box.x + box.w / 2}
                    y={box.y + box.h - 4}
                    fill="#475569"
                    fontSize="9"
                    textAnchor="middle"
                  >
                    +
                    {tables.find((t) => t.name === box.name)!.columns
                      .length - MAX_COLS_SHOWN}{" "}
                    more
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
